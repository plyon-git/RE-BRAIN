package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

func testService(fetch fetchFunc) *Service {
	return &Service{fetch: fetch, slots: make(chan struct{}, 4), clock: func() time.Time { return time.Date(2026, 10, 3, 2, 0, 0, 0, time.UTC) }}
}

func validatedSource(t *testing.T, adapter string) Source {
	t.Helper()
	request := CollectRequest{Source: Source{ID: "fixture", Name: "Test fixture", Adapter: adapter, URL: "https://data.example.gov/records", Category: "delinquency", State: "TX", CountyFIPS: "48453"}}
	if err := validateRequest(&request); err != nil {
		t.Fatal(err)
	}
	return request.Source
}

func TestCSVQuotedFieldsAndBOM(t *testing.T) {
	rows, err := parseCSV([]byte("\xef\xbb\xbfParcel,Owner,Value\nA-1,\"Lyon, Parrish\",\"$120,500\"\n"), 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 || rows[0]["Owner"] != "Lyon, Parrish" || rows[0]["Value"] != "$120,500" {
		t.Fatalf("Unexpected parsed CSV: %#v", rows)
	}
}

func TestCSVRejectsDuplicateAndMalformedColumns(t *testing.T) {
	for _, input := range []string{"Parcel,parcel\nA,B\n", "Parcel,\nA,B\n", "Parcel,Owner\nA,B,C\n", "Parcel,Owner\n\"unterminated,B\n"} {
		if _, err := parseCSV([]byte(input), 10); err == nil {
			t.Fatalf("Expected rejection for %q", input)
		}
	}
}

func TestCSVRecordLimit(t *testing.T) {
	rows, err := parseCSV([]byte("id\n1\n2\n3\n"), 2)
	if err != nil || len(rows) != 2 {
		t.Fatalf("Limit failed: rows=%d err=%v", len(rows), err)
	}
}

func TestJSONEnvelopesAndGeoJSON(t *testing.T) {
	for _, input := range []string{`[{"id":1}]`, `{"records":[{"id":1}]}`, `{"data":[{"id":1}]}`, `{"results":[{"id":1}]}`} {
		rows, err := parseJSONRows([]byte(input))
		if err != nil || len(rows) != 1 || textValue(rows[0]["id"]) != "1" {
			t.Fatalf("JSON parse failed: %#v %v", rows, err)
		}
	}
	rows, err := parseJSONRows([]byte(`{"type":"FeatureCollection","features":[{"type":"Feature","id":"P1","properties":{"address":"100 Main"},"geometry":{"type":"Point","coordinates":[-97,30]}}]}`))
	if err != nil || rows[0]["id"] != "P1" || rows[0]["address"] != "100 Main" || rows[0]["geometry"] == nil {
		t.Fatalf("GeoJSON properties lost: %#v %v", rows, err)
	}
}

func TestJSONRejectsScalarAndTrailingData(t *testing.T) {
	for _, input := range []string{`{"status":"error"}`, `[1,2]`, `[] {}`, `null`, `not json`} {
		if _, err := parseJSONRows([]byte(input)); err == nil {
			t.Fatalf("Expected rejection for %q", input)
		}
	}
}

func TestCanonicalMappingAndNumericGeography(t *testing.T) {
	source := validatedSource(t, "json")
	source.Mapping = map[string]string{"source_record_id": "Tax.Record", "parcel_id": "property.parcel", "address": "SITE", "estimated_value": "Value", "debt": "Balance", "custom_flag": "Flag"}
	raw := map[string]any{"Tax.Record": "R-1", "property": map[string]any{"parcel": "P-01"}, "SITE": "123 Main", "Value": "$123,456.50", "Balance": "(250)", "Flag": true, "county_fips": json.Number("1001"), "owner_name": "Test Owner"}
	record := canonicalRecord(source, raw, "2026-10-03T02:00:00.000Z")
	if record.SourceRecordID != "R-1" || record.ParcelID != "P-01" || record.Address != "123 Main" || record.CountyFIPS != "01001" || record.State != "TX" {
		t.Fatalf("Bad canonical fields: %#v", record)
	}
	if record.Attributes["estimated_value"] != float64(123456.50) || record.Attributes["debt"] != float64(-250) || record.Attributes["owner"] != "Test Owner" || record.Attributes["custom_flag"] != true {
		t.Fatalf("Bad attributes: %#v", record.Attributes)
	}
	if _, exists := raw["estimated_value"]; exists {
		t.Fatal("canonicalRecord mutated its input")
	}
}

func TestFallbackIDDeterministicAndContentSensitive(t *testing.T) {
	source := validatedSource(t, "json")
	first := canonicalRecord(source, map[string]any{"a": 1, "b": 2}, "one")
	second := canonicalRecord(source, map[string]any{"b": 2, "a": 1}, "two")
	changed := canonicalRecord(source, map[string]any{"a": 1, "b": 3}, "one")
	if first.SourceRecordID != second.SourceRecordID || first.SourceRecordID == changed.SourceRecordID {
		t.Fatal("Fallback IDs are unstable or ignore content")
	}
	if !strings.HasPrefix(first.SourceRecordID, "sha256:") {
		t.Fatal("Fallback ID provenance missing")
	}
}

func TestNonFiniteNumbersAreRejected(t *testing.T) {
	for _, value := range []string{"NaN", "Inf", "-Inf", "none", ""} {
		if _, ok := numericValue(value); ok {
			t.Fatalf("Accepted invalid numeric value %q", value)
		}
	}
}

func TestArcGISPaginationAndProvenance(t *testing.T) {
	source := validatedSource(t, "arcgis")
	source.URL = "https://data.example.gov/FeatureServer/0?where=ACTIVE%3D1"
	source.Options.PageSize = 2
	source.Options.OrderBy = "OBJECTID ASC"
	calls := 0
	service := testService(func(ctx context.Context, target string) ([]byte, error) {
		parsed, err := url.Parse(target)
		if err != nil {
			t.Fatal(err)
		}
		if parsed.Path != "/FeatureServer/0/query" || parsed.Query().Get("where") != "ACTIVE=1" || parsed.Query().Get("resultRecordCount") != "2" || parsed.Query().Get("orderByFields") != "OBJECTID ASC" {
			t.Fatalf("Bad ArcGIS URL: %s", target)
		}
		calls++
		if calls == 1 {
			if parsed.Query().Get("resultOffset") != "0" {
				t.Fatal("Expected first offset 0")
			}
			return []byte(`{"features":[{"attributes":{"OBJECTID":1}},{"attributes":{"OBJECTID":2}}],"exceededTransferLimit":true}`), nil
		}
		if parsed.Query().Get("resultOffset") != "2" {
			t.Fatal("Expected second offset 2")
		}
		return []byte(`{"features":[{"attributes":{"OBJECTID":3}}],"exceededTransferLimit":false}`), nil
	})
	response, err := service.collect(context.Background(), CollectRequest{Source: source})
	if err != nil {
		t.Fatal(err)
	}
	if response.Count != 3 || calls != 2 || response.Provenance.PagesFetched != 2 || len(response.Provenance.InputSHA256) != 64 || response.Provenance.Truncated {
		t.Fatalf("Wrong collection result: %#v", response)
	}
	if response.Records[2].SourceRecordID != "3" {
		t.Fatal("Lost ArcGIS object ID")
	}
}

func TestSocrataPagingPreservesFilter(t *testing.T) {
	source := validatedSource(t, "socrata")
	source.URL = "https://data.example.gov/resource/abcd-1234.json?$where=debt%3E0"
	source.Options.PageSize = 2
	calls := 0
	service := testService(func(ctx context.Context, target string) ([]byte, error) {
		parsed, _ := url.Parse(target)
		query := parsed.Query()
		if query.Get("$where") != "debt>0" || query.Get("$limit") != "2" || query.Get("$order") != ":id ASC" {
			t.Fatalf("Bad Socrata URL: %s", target)
		}
		calls++
		if calls == 1 {
			return []byte(`[{"id":"a"},{"id":"b"}]`), nil
		}
		if query.Get("$offset") != "2" {
			t.Fatalf("Wrong Socrata offset: %s", target)
		}
		return []byte(`[{"id":"c"}]`), nil
	})
	response, err := service.collect(context.Background(), CollectRequest{Source: source})
	if err != nil || response.Count != 3 || calls != 2 {
		t.Fatalf("Pagination failed: %#v err=%v", response, err)
	}
}

func TestPaginationCapAndRepeatedPage(t *testing.T) {
	source := validatedSource(t, "socrata")
	source.URL = "https://data.example.gov/resource/abcd-1234.json"
	source.Options.PageSize = 2
	source.Options.MaxRecords = 1
	service := testService(func(ctx context.Context, target string) ([]byte, error) {
		return []byte(`[{"id":"a"},{"id":"b"}]`), nil
	})
	response, err := service.collect(context.Background(), CollectRequest{Source: source})
	if err != nil || response.Count != 1 || !response.Provenance.Truncated || len(response.Provenance.Warnings) == 0 {
		t.Fatalf("Cap not reported: %#v err=%v", response, err)
	}
	source.Options.MaxRecords = 10
	if _, err := service.collect(context.Background(), CollectRequest{Source: source}); err == nil || !strings.Contains(err.Error(), "repeated a page") {
		t.Fatalf("Repeated pages were not rejected: %v", err)
	}
}

func TestArcGISQueryErrorAndInvalidSocrataURL(t *testing.T) {
	if _, _, err := parseArcGIS([]byte(`{"error":{"code":400,"message":"Invalid query"}}`)); err == nil {
		t.Fatal("ArcGIS error was treated as empty data")
	}
	source := validatedSource(t, "socrata")
	if _, err := pagedURL(source, 0); err == nil {
		t.Fatal("Invalid Socrata path accepted")
	}
	source.URL = "https://data.example.gov/resource/abcd-1234.json?$query=SELECT%20*"
	if _, err := pagedURL(source, 0); err == nil {
		t.Fatal("Unbounded Socrata query accepted")
	}
}

func TestURLAllowlist(t *testing.T) {
	policy := NewURLPolicy([]string{"data.example.gov"})
	for _, target := range []string{"http://data.example.gov/file.csv", "file:///etc/passwd", "https://127.0.0.1/", "https://[::1]/", "https://data.example.gov.evil.test/", "https://user:pass@data.example.gov/", "https://data.example.gov:8443/", "https://data.example.gov/#private", "https://other.example.gov/"} {
		if _, err := policy.Validate(target); err == nil {
			t.Fatalf("Unsafe URL accepted: %s", target)
		}
	}
	for _, target := range []string{"https://data.example.gov/file.csv", "https://DATA.EXAMPLE.GOV:443/file.csv", "https://data.example.gov./file.csv"} {
		if _, err := policy.Validate(target); err != nil {
			t.Fatalf("Valid URL rejected: %s: %v", target, err)
		}
	}
	if _, err := NewURLPolicy(nil).Validate("https://data.example.gov/"); err == nil {
		t.Fatal("Empty allowlist granted network access")
	}
}

func TestPrivateAndReservedIPs(t *testing.T) {
	for _, address := range []string{"0.0.0.0", "10.0.0.1", "100.64.1.1", "127.0.0.1", "169.254.169.254", "172.16.1.1", "192.0.0.1", "192.0.2.2", "192.168.1.1", "198.18.1.1", "198.51.100.2", "203.0.113.3", "224.0.0.1", "240.0.0.1", "::1", "::ffff:127.0.0.1", "fc00::1", "fe80::1", "2001:db8::1", "64:ff9b::7f00:1", "2002:7f00:1::"} {
		if isPublicIP(net.ParseIP(address)) {
			t.Fatalf("Private/reserved address accepted: %s", address)
		}
	}
	for _, address := range []string{"8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"} {
		if !isPublicIP(net.ParseIP(address)) {
			t.Fatalf("Public address rejected: %s", address)
		}
	}
}

func TestRedirectIsRevalidated(t *testing.T) {
	client := newHTTPClient(NewURLPolicy([]string{"data.example.gov"}))
	request, _ := http.NewRequest(http.MethodGet, "https://evil.test/private", nil)
	if err := client.CheckRedirect(request, []*http.Request{{}}); err == nil {
		t.Fatal("Redirect escaped host allowlist")
	}
}

func TestAPIBearerInlineCSVAndStrictJSON(t *testing.T) {
	service := testService(func(ctx context.Context, target string) ([]byte, error) {
		t.Fatal("Inline CSV must not access the network")
		return nil, nil
	})
	service.apiKey = "test-key"
	body := `{"source":{"id":"fixture","adapter":"csv","category":"property","state":"co","county_fips":"08031","mapping":{"parcel_id":"APN","address":"SITE"}},"csv_text":"APN,SITE\n01,123 Main\n"}`
	unauthorized := httptest.NewRecorder()
	service.Handler().ServeHTTP(unauthorized, httptest.NewRequest(http.MethodPost, "/collect", strings.NewReader(body)))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("Missing token status: %d", unauthorized.Code)
	}
	request := httptest.NewRequest(http.MethodPost, "/collect", strings.NewReader(body))
	request.Header.Set("Authorization", "Bearer test-key")
	recorder := httptest.NewRecorder()
	service.Handler().ServeHTTP(recorder, request)
	if recorder.Code != http.StatusOK {
		t.Fatalf("Collection status: %d body=%s", recorder.Code, recorder.Body.String())
	}
	var response CollectResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if response.Count != 1 || response.Records[0].State != "CO" || response.Records[0].ParcelID != "01" {
		t.Fatalf("Bad API response: %#v", response)
	}
	for _, malformed := range []string{body + `{}`, strings.Replace(body, `"csv_text"`, `"unknown"`, 1)} {
		request := httptest.NewRequest(http.MethodPost, "/collect", strings.NewReader(malformed))
		request.Header.Set("Authorization", "Bearer test-key")
		recorder := httptest.NewRecorder()
		service.Handler().ServeHTTP(recorder, request)
		if recorder.Code != http.StatusBadRequest {
			t.Fatalf("Malformed request accepted: %s", malformed)
		}
	}
	health := httptest.NewRecorder()
	service.Handler().ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/health", nil))
	if health.Code != http.StatusOK {
		t.Fatal("Health probe should not require bearer token")
	}
}

func TestRequestValidationAndProvenanceRedaction(t *testing.T) {
	request := CollectRequest{Source: Source{ID: "x", Adapter: "csv"}, CSVText: "id\n1"}
	if err := validateRequest(&request); err != nil {
		t.Fatal(err)
	}
	request.Source.Options.MaxRecords = 10001
	if err := validateRequest(&request); err == nil {
		t.Fatal("Unbounded collection accepted")
	}
	redacted := provenanceURL("https://data.example.gov/file.csv?token=secret&where=active")
	if strings.Contains(redacted, "secret") || !strings.Contains(redacted, "where=active") {
		t.Fatalf("Bad provenance redaction: %s", redacted)
	}
}
