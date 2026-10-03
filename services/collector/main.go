// 101XVC BRAIN Collector. All rights reserved. See the repository LICENSE.
package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

const (
	maxInboundBytes  = 4 << 20
	maxResponseBytes = 16 << 20
	maxRecords       = 10000
	maxPages         = 100
)

type Options struct {
	PageSize   int    `json:"page_size,omitempty"`
	MaxRecords int    `json:"max_records,omitempty"`
	MaxPages   int    `json:"max_pages,omitempty"`
	OrderBy    string `json:"order_by,omitempty"`
}

type Source struct {
	ID         string            `json:"id"`
	Name       string            `json:"name"`
	URL        string            `json:"url,omitempty"`
	Adapter    string            `json:"adapter"`
	Category   string            `json:"category"`
	State      string            `json:"state,omitempty"`
	CountyFIPS string            `json:"county_fips,omitempty"`
	Mapping    map[string]string `json:"mapping,omitempty"`
	Options    Options           `json:"options,omitempty"`
}

type CollectRequest struct {
	Source  Source `json:"source"`
	CSVText string `json:"csv_text,omitempty"`
}

type Record struct {
	SourceID       string         `json:"source_id"`
	SourceRecordID string         `json:"source_record_id"`
	ParcelID       string         `json:"parcel_id,omitempty"`
	CountyFIPS     string         `json:"county_fips,omitempty"`
	State          string         `json:"state,omitempty"`
	Address        string         `json:"address,omitempty"`
	Category       string         `json:"category"`
	ObservedAt     string         `json:"observed_at"`
	Attributes     map[string]any `json:"attributes"`
}

type Provenance struct {
	SourceID     string   `json:"source_id"`
	SourceName   string   `json:"source_name"`
	SourceURL    string   `json:"source_url,omitempty"`
	Adapter      string   `json:"adapter"`
	RetrievedAt  string   `json:"retrieved_at"`
	PagesFetched int      `json:"pages_fetched"`
	InputSHA256  string   `json:"input_sha256"`
	Truncated    bool     `json:"truncated"`
	Warnings     []string `json:"warnings,omitempty"`
}

type CollectResponse struct {
	Records    []Record   `json:"records"`
	Count      int        `json:"count"`
	Provenance Provenance `json:"provenance"`
}

type fetchFunc func(context.Context, string) ([]byte, error)

type Service struct {
	fetch  fetchFunc
	apiKey string
	slots  chan struct{}
	clock  func() time.Time
}

func (s *Service) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "service": "101xvc-brain-collector", "adapters": []string{"csv", "json", "arcgis", "socrata"}})
	})
	mux.HandleFunc("POST /collect", s.handleCollect)
	return mux
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func (s *Service) handleCollect(w http.ResponseWriter, r *http.Request) {
	if s.apiKey != "" {
		expected := "Bearer " + s.apiKey
		if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte(expected)) != 1 {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Valid bearer token required"})
			return
		}
	}
	select {
	case s.slots <- struct{}{}:
		defer func() { <-s.slots }()
	default:
		writeJSON(w, http.StatusTooManyRequests, map[string]string{"error": "Collector is at capacity; retry later"})
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxInboundBytes)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	var request CollectRequest
	if err := decoder.Decode(&request); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid JSON request: " + err.Error()})
		return
	}
	var extra any
	if err := decoder.Decode(&extra); err == nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Only one JSON object is permitted"})
		return
	} else if !errors.Is(err, io.EOF) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "Invalid trailing request data"})
		return
	}
	if err := validateRequest(&request); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 90*time.Second)
	defer cancel()
	result, err := s.collect(ctx, request)
	if err != nil {
		// Upstream URLs and response bodies are not logged; they may contain access tokens.
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, result)
}

func validateRequest(request *CollectRequest) error {
	source := &request.Source
	source.ID = strings.TrimSpace(source.ID)
	source.Adapter = strings.ToLower(strings.TrimSpace(source.Adapter))
	source.State = strings.ToUpper(strings.TrimSpace(source.State))
	if source.ID == "" || len(source.ID) > 120 {
		return errors.New("source.id must contain 1 to 120 characters")
	}
	if len(source.Name) > 300 || len(source.Category) > 64 {
		return errors.New("Source name or category is too long")
	}
	if source.Category == "" {
		source.Category = "property"
	}
	if source.State != "" && (len(source.State) != 2 || source.State[0] < 'A' || source.State[0] > 'Z' || source.State[1] < 'A' || source.State[1] > 'Z') {
		return errors.New("source.state must be a two-letter code")
	}
	if source.CountyFIPS != "" && !validFIPS(source.CountyFIPS) {
		return errors.New("source.county_fips must be five digits")
	}
	switch source.Adapter {
	case "csv", "json", "arcgis", "socrata":
	default:
		return errors.New("source.adapter must be csv, json, arcgis, or socrata")
	}
	if source.URL == "" && !(source.Adapter == "csv" && request.CSVText != "") {
		return errors.New("source.url is required except for inline CSV")
	}
	if source.URL != "" && request.CSVText != "" {
		return errors.New("Provide either source.url or csv_text, not both")
	}
	if request.CSVText != "" && source.Adapter != "csv" {
		return errors.New("csv_text requires the csv adapter")
	}
	if len(source.URL) > 4096 {
		return errors.New("Source URL is too long")
	}
	if len(source.Mapping) > 64 {
		return errors.New("At most 64 mapping entries are permitted")
	}
	for key, value := range source.Mapping {
		if len(key) > 120 || len(value) > 300 {
			return errors.New("Mapping field names are too long")
		}
	}
	options := &source.Options
	if options.PageSize == 0 {
		options.PageSize = 1000
	}
	if options.MaxRecords == 0 {
		options.MaxRecords = maxRecords
	}
	if options.MaxPages == 0 {
		options.MaxPages = maxPages
	}
	if options.PageSize < 1 || options.PageSize > 2000 {
		return errors.New("page_size must be between 1 and 2000")
	}
	if options.MaxRecords < 1 || options.MaxRecords > maxRecords {
		return errors.New("max_records must be between 1 and 10000")
	}
	if options.MaxPages < 1 || options.MaxPages > maxPages {
		return errors.New("max_pages must be between 1 and 100")
	}
	if len(options.OrderBy) > 300 {
		return errors.New("order_by is too long")
	}
	return nil
}

func validFIPS(value string) bool {
	if len(value) != 5 {
		return false
	}
	for _, char := range value {
		if char < '0' || char > '9' {
			return false
		}
	}
	return true
}

func main() {
	allowedHosts := strings.Split(os.Getenv("COLLECTOR_ALLOWED_HOSTS"), ",")
	policy := NewURLPolicy(allowedHosts)
	client := newHTTPClient(policy)
	service := &Service{fetch: func(ctx context.Context, target string) ([]byte, error) { return fetchURL(ctx, client, policy, target) }, apiKey: os.Getenv("BRAIN_API_KEY"), slots: make(chan struct{}, 4), clock: time.Now}
	port := os.Getenv("COLLECTOR_PORT")
	if port == "" {
		port = "8081"
	}
	number, err := strconv.Atoi(port)
	if err != nil || number < 1 || number > 65535 {
		log.Fatal("COLLECTOR_PORT must be a valid TCP port")
	}
	server := &http.Server{Addr: ":" + port, Handler: service.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 95 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Printf("101XVC BRAIN Collector listening on %s; HTTPS source hosts explicitly allowlisted: %d", server.Addr, len(policy.allowedHosts))
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(fmt.Errorf("collector server: %w", err))
	}
}
