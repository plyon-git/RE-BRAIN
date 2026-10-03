# 101XVC BRAIN Collector

A dependency-free Go 1.23 service that retrieves explicitly configured public datasets and normalizes observations for the Python BRAIN API. It does not discover datasets, assert delinquency from parcel ownership, or claim nationwide coverage. Every live source must be selected, allowlisted, mapped, and verified against its publisher's current documentation and terms.

## Run

```bash
export BRAIN_API_KEY='replace-with-a-long-random-secret'
export COLLECTOR_ALLOWED_HOSTS='data.example.gov,services.example.gov'
go test ./...
go run .
```

`COLLECTOR_PORT` defaults to `8081`. With Docker, build from this directory using `docker build -t 101xvc-brain-collector .`; tests execute during the image build. Pass the same environment variables to the container. An empty host allowlist disables all remote retrieval while allowing explicitly supplied inline CSV. `BRAIN_API_KEY` requires the matching bearer token for `POST /collect` when configured. The health endpoint remains public. The repository deployment should configure a key and keep the collector on its internal service network.

## Contract

`GET /health` reports process liveness and implemented adapter names. It does not prove that a particular remote dataset is reachable or correctly mapped.

`POST /collect` accepts the following request. Inline CSV is useful for permitted exports and offline extraction without exposing filesystem paths to the service.

```json
{
  "source": {
    "id": "example-export",
    "name": "Local permitted export",
    "adapter": "csv",
    "category": "delinquency",
    "state": "CO",
    "county_fips": "08031",
    "mapping": {
      "source_record_id": "RECORD_ID",
      "parcel_id": "PARCEL_NUMBER",
      "address": "SITE_ADDRESS",
      "owner": "OWNER_NAME",
      "debt": "BALANCE"
    },
    "options": {"max_records": 10000}
  },
  "csv_text": "RECORD_ID,PARCEL_NUMBER,SITE_ADDRESS,OWNER_NAME,BALANCE\n1,0001,123 Example St,Example Owner,500\n"
}
```

For a remote CSV, JSON, ArcGIS, or Socrata source, set `source.url` and omit `csv_text`. The hostname must appear exactly in `COLLECTOR_ALLOWED_HOSTS`; wildcards are not supported. `source.example.json` is a mapping template with a placeholder URL, not a verified live source.

The response is `{ "records": [...], "count": 1, "provenance": {...} }`. Each record contains `source_id`, `source_record_id`, `parcel_id`, `county_fips`, `state`, `address`, `category`, `observed_at`, and `attributes`. Empty optional top-level fields are omitted. Raw fields are preserved in `attributes`; standard mapped monetary and coordinate fields become finite JSON numbers. Mapping is `canonical_field: raw_field`, with nested JSON paths such as `properties.address` supported. Exact raw names take priority over nested lookup. Source state and FIPS act as fallbacks, not replacements for valid per-row values. Observed time is retrieval time and does not assert the publisher's effective date.

Common aliases cover parcel IDs, source record IDs, owners, addresses, assessed values, estimated values, debt, zoning, latitude, and longitude. Explicit mappings override aliases. A missing source record ID receives a deterministic SHA-256 content ID. That fallback changes when the source row changes; configure a publisher's durable identifier for longitudinal updates. County FIPS remains a five-character string, preserving or restoring leading zeroes where possible.

Provenance contains the source title and URL, adapter, retrieval time, fetched-page count, SHA-256 of retrieved response bytes, truncation status, and warnings. Token/key-like query parameters are redacted from the provenance URL. For multiple pages the hash covers the fetched bodies concatenated in retrieval order. Upstream errors fail the operation rather than returning a silently partial batch; page/record caps return bounded results with an explicit truncation warning.

## Adapter readiness

| Adapter | Implemented input | Pagination and limitations |
| --- | --- | --- |
| `csv` | UTF-8 CSV with a unique header row, standard quoting, optional BOM | One response or inline export. No encoding detection. The row limit can produce a truncated batch. |
| `json` | Object arrays; `records`, `data`, `results`, or `features` envelopes; GeoJSON properties | One bounded response. Arbitrary publisher-specific cursor pagination is not implemented. |
| `arcgis` | ArcGIS FeatureServer/MapServer layer URL or `/query`, feature attributes | `resultOffset` and `resultRecordCount`, honoring `exceededTransferLimit`. Existing `where`/`outFields` filters are preserved. Geometry is omitted by default. Configure `options.order_by` with a unique object ID; endpoints without stable pagination fail on repeated pages. |
| `socrata` | SODA `/resource/<dataset-id>.json` | `$offset`/`$limit`, existing `$where`/`$select`, stable default `$order=:id ASC` or `options.order_by`. Raw `$query` is rejected because it can override bounded paging. No app-token headers are implemented. |

HTML tables and PDF tax notices require an offline extraction step or a dedicated parser before submission as CSV/JSON. CAPTCHA, authentication, JavaScript rendering, publisher-specific signing, and private APIs are not implemented. Configure filters so an observation's category matches actual source evidence. For example, using a parcel roll as a delinquency source without a delinquency field or documented filter is incorrect.

## Bounds and source security

Remote requests allow HTTPS on port 443, exact allowlisted DNS hosts, and public unicast addresses only. URL credentials and fragments are rejected. Every redirect is revalidated. A custom connection dialer resolves DNS, rejects the entire answer if any address is private/reserved, and connects directly to a checked address to resist DNS rebinding. Proxy environment variables are ignored. TLS certificate validation remains enabled.

Limits: 4 MiB inbound JSON, 16 MiB per source response, 1 to 2,000 records requested per paginated page, at most 10,000 collected records, at most 100 pages, four simultaneous collection jobs, 20-second per-request HTTP timeout, and 90-second collection deadline. `options.max_records`, `options.max_pages`, and `options.page_size` may reduce these bounds. A job at capacity receives HTTP 429. Request/schema errors return 400, missing/incorrect bearer tokens 401, and retrieval/parser failures 502. No callback, upload-to-third-party, or filesystem-read endpoint exists.

Run `go test -race ./...` in an environment with Go installed. Tests exercise quoted CSV, malformed input, JSON envelopes, GeoJSON, canonical mappings, stable IDs, finite numbers, ArcGIS and Socrata pagination, repeated-page detection, truncation, request authorization, strict JSON, URL allowlists, redirect validation, and private/reserved IP denial. These tests use deterministic fixtures; they do not certify live source availability.
