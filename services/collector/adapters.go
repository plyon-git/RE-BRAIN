package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"strconv"
	"strings"
)

func (s *Service) collect(ctx context.Context, request CollectRequest) (CollectResponse, error) {
	source := request.Source
	observed := s.clock().UTC().Format("2006-01-02T15:04:05.000Z")
	result := CollectResponse{Records: make([]Record, 0), Provenance: Provenance{SourceID: source.ID, SourceName: source.Name, SourceURL: provenanceURL(source.URL), Adapter: source.Adapter, RetrievedAt: observed}}
	digest := sha256.New()
	var rows []map[string]any
	appendRows := func(page []map[string]any) {
		remaining := source.Options.MaxRecords - len(rows)
		if len(page) > remaining {
			page = page[:remaining]
			result.Provenance.Truncated = true
		}
		rows = append(rows, page...)
	}
	if source.Adapter == "csv" || source.Adapter == "json" {
		var body []byte
		var err error
		if request.CSVText != "" {
			body = []byte(request.CSVText)
		} else {
			body, err = s.fetch(ctx, source.URL)
		}
		if err != nil {
			return result, err
		}
		digest.Write(body)
		result.Provenance.PagesFetched = 1
		var parsed []map[string]any
		if source.Adapter == "csv" {
			parsed, err = parseCSV(body, source.Options.MaxRecords+1)
		} else {
			parsed, err = parseJSONRows(body)
		}
		if err != nil {
			return result, err
		}
		appendRows(parsed)
	} else {
		seenPages := make(map[string]bool)
		offset := 0
		for page := 0; page < source.Options.MaxPages; page++ {
			if err := ctx.Err(); err != nil {
				return result, errors.New("Collection deadline reached")
			}
			target, err := pagedURL(source, offset)
			if err != nil {
				return result, err
			}
			body, err := s.fetch(ctx, target)
			if err != nil {
				return result, err
			}
			digest.Write(body)
			result.Provenance.PagesFetched++
			var parsed []map[string]any
			var more *bool
			if source.Adapter == "arcgis" {
				parsed, more, err = parseArcGIS(body)
			} else {
				parsed, err = parseJSONRows(body)
			}
			if err != nil {
				return result, err
			}
			if len(parsed) == 0 {
				break
			}
			pageJSON, _ := json.Marshal(parsed)
			pageDigest := sha256.Sum256(pageJSON)
			fingerprint := hex.EncodeToString(pageDigest[:])
			if seenPages[fingerprint] {
				return result, errors.New("Source repeated a page; pagination is unsupported or unstable")
			}
			seenPages[fingerprint] = true
			appendRows(parsed)
			offset += len(parsed)
			hasMore := len(parsed) >= source.Options.PageSize
			if more != nil {
				hasMore = *more
			}
			if !hasMore {
				break
			}
			if len(rows) >= source.Options.MaxRecords || page+1 >= source.Options.MaxPages {
				result.Provenance.Truncated = true
				break
			}
		}
	}
	for _, row := range rows {
		result.Records = append(result.Records, canonicalRecord(source, row, observed))
	}
	result.Count = len(result.Records)
	result.Provenance.InputSHA256 = hex.EncodeToString(digest.Sum(nil))
	if result.Provenance.Truncated {
		result.Provenance.Warnings = append(result.Provenance.Warnings, "Collection stopped at a record/page limit; this is not a complete source snapshot.")
	}
	if source.Adapter == "arcgis" && source.Options.OrderBy == "" {
		result.Provenance.Warnings = append(result.Provenance.Warnings, "Configure order_by with the service's unique object ID field for stable ArcGIS pagination.")
	}
	return result, nil
}

func parseCSV(body []byte, limit int) ([]map[string]any, error) {
	reader := csv.NewReader(bytes.NewReader(bytes.TrimPrefix(body, []byte{0xef, 0xbb, 0xbf})))
	reader.TrimLeadingSpace = true
	headers, err := reader.Read()
	if errors.Is(err, io.EOF) {
		return []map[string]any{}, nil
	}
	if err != nil {
		return nil, errors.New("Invalid CSV header: " + err.Error())
	}
	seen := make(map[string]bool)
	for index, header := range headers {
		header = strings.TrimSpace(header)
		if header == "" || seen[strings.ToLower(header)] {
			return nil, errors.New("CSV headers must be nonempty and unique")
		}
		seen[strings.ToLower(header)] = true
		headers[index] = header
	}
	rows := make([]map[string]any, 0)
	for len(rows) < limit {
		fields, err := reader.Read()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, errors.New("Invalid CSV row: " + err.Error())
		}
		row := make(map[string]any, len(fields))
		for index, field := range fields {
			row[headers[index]] = strings.TrimSpace(field)
		}
		rows = append(rows, row)
	}
	return rows, nil
}

func decodeJSON(body []byte) (any, error) {
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.UseNumber()
	var decoded any
	if err := decoder.Decode(&decoded); err != nil {
		return nil, errors.New("Invalid source JSON: " + err.Error())
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		return nil, errors.New("Source contains trailing JSON data")
	}
	return decoded, nil
}

func parseJSONRows(body []byte) ([]map[string]any, error) {
	decoded, err := decodeJSON(body)
	if err != nil {
		return nil, err
	}
	if envelope, ok := decoded.(map[string]any); ok {
		found := false
		for _, key := range []string{"records", "data", "results", "features"} {
			if candidate, ok := envelope[key].([]any); ok {
				decoded = candidate
				found = true
				break
			}
		}
		if !found {
			return nil, errors.New("JSON must be a record array or an envelope containing records/data/results/features")
		}
	}
	array, ok := decoded.([]any)
	if !ok {
		return nil, errors.New("Source JSON must contain an array of records")
	}
	rows := make([]map[string]any, 0, len(array))
	for _, entry := range array {
		row, ok := entry.(map[string]any)
		if !ok {
			return nil, errors.New("Every source JSON record must be an object")
		}
		if properties, ok := row["properties"].(map[string]any); ok && row["type"] == "Feature" {
			copy := make(map[string]any, len(properties)+2)
			for key, value := range properties {
				copy[key] = value
			}
			if geometry, exists := row["geometry"]; exists {
				copy["geometry"] = geometry
			}
			if id, exists := row["id"]; exists {
				copy["id"] = id
			}
			row = copy
		}
		rows = append(rows, row)
	}
	return rows, nil
}

func parseArcGIS(body []byte) ([]map[string]any, *bool, error) {
	decoded, err := decodeJSON(body)
	if err != nil {
		return nil, nil, err
	}
	envelope, ok := decoded.(map[string]any)
	if !ok {
		return nil, nil, errors.New("ArcGIS response must be an object")
	}
	if _, exists := envelope["error"]; exists {
		return nil, nil, errors.New("ArcGIS service returned a query error; verify layer, filter, and pagination support")
	}
	features, ok := envelope["features"].([]any)
	if !ok {
		return nil, nil, errors.New("ArcGIS response does not contain a features array")
	}
	rows := make([]map[string]any, 0, len(features))
	for _, feature := range features {
		object, ok := feature.(map[string]any)
		if !ok {
			return nil, nil, errors.New("Invalid ArcGIS feature")
		}
		attributes, ok := object["attributes"].(map[string]any)
		if !ok {
			return nil, nil, errors.New("ArcGIS feature lacks attributes")
		}
		row := make(map[string]any, len(attributes)+1)
		for key, value := range attributes {
			row[key] = value
		}
		if geometry, exists := object["geometry"]; exists {
			row["geometry"] = geometry
		}
		rows = append(rows, row)
	}
	var more *bool
	if value, ok := envelope["exceededTransferLimit"].(bool); ok {
		more = &value
	}
	return rows, more, nil
}

func pagedURL(source Source, offset int) (string, error) {
	parsed, err := url.Parse(source.URL)
	if err != nil {
		return "", errors.New("Invalid source URL")
	}
	query := parsed.Query()
	if source.Adapter == "arcgis" {
		parsed.Path = strings.TrimRight(parsed.Path, "/")
		if !strings.HasSuffix(strings.ToLower(parsed.Path), "/query") {
			parsed.Path += "/query"
		}
		if query.Get("where") == "" {
			query.Set("where", "1=1")
		}
		if query.Get("outFields") == "" {
			query.Set("outFields", "*")
		}
		query.Set("f", "json")
		query.Set("returnGeometry", "false")
		query.Set("resultOffset", strconv.Itoa(offset))
		query.Set("resultRecordCount", strconv.Itoa(source.Options.PageSize))
		if source.Options.OrderBy != "" {
			query.Set("orderByFields", source.Options.OrderBy)
		}
		// A count/ID-only request would not yield canonical observations.
		query.Del("returnCountOnly")
		query.Del("returnIdsOnly")
	} else if source.Adapter == "socrata" {
		if !strings.HasSuffix(strings.ToLower(parsed.Path), ".json") {
			return "", errors.New("Socrata source.url must be a /resource/<dataset-id>.json endpoint")
		}
		if query.Get("$query") != "" {
			return "", errors.New("Socrata $query is unsupported; use $where/$select and collector paging")
		}
		query.Set("$offset", strconv.Itoa(offset))
		query.Set("$limit", strconv.Itoa(source.Options.PageSize))
		if source.Options.OrderBy != "" {
			query.Set("$order", source.Options.OrderBy)
		} else if query.Get("$order") == "" {
			query.Set("$order", ":id ASC")
		}
	} else {
		return "", fmt.Errorf("Adapter %s does not support paging", source.Adapter)
	}
	parsed.RawQuery = query.Encode()
	return parsed.String(), nil
}

func provenanceURL(target string) string {
	parsed, err := url.Parse(target)
	if err != nil {
		return ""
	}
	query := parsed.Query()
	for key := range query {
		lower := strings.ToLower(key)
		if strings.Contains(lower, "token") || strings.Contains(lower, "key") || strings.Contains(lower, "secret") || strings.Contains(lower, "password") || lower == "signature" {
			query.Set(key, "[REDACTED]")
		}
	}
	parsed.RawQuery = query.Encode()
	return parsed.String()
}
