package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"
)

var aliases = map[string][]string{
	"source_record_id": {"source_record_id", "OBJECTID", "objectid", "id", "record_id", ":id", "FID"},
	"parcel_id":        {"parcel_id", "parcel", "parcel_number", "parcelid", "apn", "account_number", "PIN"},
	"county_fips":      {"county_fips", "countyfips", "fips"},
	"state":            {"state", "state_code", "st"},
	"address":          {"address", "property_address", "site_address", "situs_address", "situs", "location_address"},
	"owner":            {"owner", "owner_name", "ownername", "taxpayer"},
	"assessed_value":   {"assessed_value", "assessedvalue", "total_assessed", "assessment"},
	"estimated_value":  {"estimated_value", "market_value", "marketvalue", "appraised_value"},
	"debt":             {"debt", "delinquent_amount", "amount_due", "tax_due", "balance"},
	"zoning":           {"zoning", "zoning_code", "zone"},
	"latitude":         {"latitude", "lat"},
	"longitude":        {"longitude", "lon", "lng"},
}

func fieldValue(raw map[string]any, source Source, field string) any {
	if path, mapped := source.Mapping[field]; mapped {
		return lookupPath(raw, path)
	}
	for _, alias := range aliases[field] {
		if value := lookupPath(raw, alias); value != nil && textValue(value) != "" {
			return value
		}
	}
	return nil
}

func lookupPath(raw map[string]any, path string) any {
	// Prefer an exact field so dots within CSV header names do not require escaping.
	if value, ok := raw[path]; ok {
		return value
	}
	for key, value := range raw {
		if strings.EqualFold(key, path) {
			return value
		}
	}
	var cursor any = raw
	for _, part := range strings.Split(path, ".") {
		object, ok := cursor.(map[string]any)
		if !ok {
			return nil
		}
		value, exists := object[part]
		if !exists {
			for key, candidate := range object {
				if strings.EqualFold(key, part) {
					value = candidate
					exists = true
					break
				}
			}
		}
		if !exists {
			return nil
		}
		cursor = value
	}
	return cursor
}

func textValue(value any) string {
	if value == nil {
		return ""
	}
	switch actual := value.(type) {
	case string:
		return strings.TrimSpace(actual)
	case json.Number:
		return actual.String()
	case float64:
		return strconv.FormatFloat(actual, 'f', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(actual), 'f', -1, 32)
	case bool:
		return strconv.FormatBool(actual)
	case int:
		return strconv.Itoa(actual)
	case int64:
		return strconv.FormatInt(actual, 10)
	default:
		return ""
	}
}

func numericValue(value any) (float64, bool) {
	text := textValue(value)
	if text == "" {
		return 0, false
	}
	text = strings.ReplaceAll(strings.ReplaceAll(text, ",", ""), "$", "")
	if strings.HasPrefix(text, "(") && strings.HasSuffix(text, ")") {
		text = "-" + strings.TrimSuffix(strings.TrimPrefix(text, "("), ")")
	}
	number, err := strconv.ParseFloat(strings.TrimSpace(text), 64)
	if err != nil || math.IsNaN(number) || math.IsInf(number, 0) {
		return 0, false
	}
	return number, true
}

func canonicalRecord(source Source, raw map[string]any, observed string) Record {
	attributes := make(map[string]any, len(raw)+len(source.Mapping))
	for key, value := range raw {
		attributes[key] = value
	}
	for _, field := range []string{"owner", "zoning"} {
		if value := fieldValue(raw, source, field); value != nil {
			attributes[field] = value
		}
	}
	for _, field := range []string{"assessed_value", "estimated_value", "debt", "latitude", "longitude"} {
		if number, ok := numericValue(fieldValue(raw, source, field)); ok {
			attributes[field] = number
		}
	}
	standard := map[string]bool{"source_record_id": true, "parcel_id": true, "county_fips": true, "state": true, "address": true}
	for field, path := range source.Mapping {
		if standard[field] {
			continue
		}
		if value := lookupPath(raw, path); value != nil {
			// Numeric canonical fields stay numeric after explicit mapping.
			if field == "assessed_value" || field == "estimated_value" || field == "debt" || field == "latitude" || field == "longitude" {
				continue
			}
			attributes[field] = value
		}
	}
	identifier := textValue(fieldValue(raw, source, "source_record_id"))
	if identifier == "" {
		encoded, _ := json.Marshal(raw)
		digest := sha256.Sum256(encoded)
		identifier = "sha256:" + hex.EncodeToString(digest[:])
	}
	state := strings.ToUpper(textValue(fieldValue(raw, source, "state")))
	if len(state) != 2 {
		state = source.State
	}
	fips := textValue(fieldValue(raw, source, "county_fips"))
	// A numeric FIPS input can lose leading zeroes. Re-pad only integer values.
	if fips != "" && len(fips) < 5 {
		if number, err := strconv.Atoi(fips); err == nil && number >= 0 {
			fips = fmt.Sprintf("%05d", number)
		}
	}
	if !validFIPS(fips) {
		fips = source.CountyFIPS
	}
	return Record{SourceID: source.ID, SourceRecordID: identifier, ParcelID: textValue(fieldValue(raw, source, "parcel_id")), CountyFIPS: fips, State: state, Address: textValue(fieldValue(raw, source, "address")), Category: source.Category, ObservedAt: observed, Attributes: attributes}
}
