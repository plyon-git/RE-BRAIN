# 101XVC BRAIN architecture

The platform turns attributable observations into a county-scoped canonical property record. The browser uses the Python API, which persists evidence and selects canonical fields using a documented source-category authority order, timestamp and stable source ID. Different values remain visible as conflicts. A new observation never silently reassigns an existing source record to another parcel.

| Component | Language | Responsibility | Runtime interface |
|---|---|---|---|
| Browser | JavaScript, HTML, CSS | Registry, provenance, scout, sources, watchlist, operations, knowledge | Same-origin `/api/` |
| Core | Python | Auth, SQLite persistence, fusion, deterministic underwriting, source jobs | Port 8080 |
| Collectors | Go | CSV, JSON, ArcGIS and Socrata ingestion, pagination, source hashes | `/collect` on 8081 |
| Resolver | Rust | County/parcel normalization and exact address fallback identities | `/resolve` on 8082 |
| Intelligence | Python | TF-IDF search, local logistic regression, document extraction | `/search`, `/train`, `/predict` on 8083 |
| Storage | SQL / SQLite | Sources, canonical properties, evidence, jobs, watchlist and activity | Local durable volumes |
| Research vault | Markdown / JSON | Source-backed knowledge and completed dispositions | Obsidian and local NLP |

The standalone Python launcher uses the same identity algorithm locally. The Docker stack runs compiled Go and Rust services with the API and local intelligence. Every service can run independently on infrastructure you control. The system has no GPT dependency and no third-party telemetry.

## Identity and evidence

An authoritative parcel key is the five-digit county FIPS plus the normalized parcel ID. Normalization retains ASCII letters and digits and preserves leading zeros. Address fallback uses the county prefix and SHA256 of the normalized address and state. It remains a provisional exact key; abbreviation differences are not guessed into equivalence.

Evidence has a source ID, source record ID, observed timestamp, category, county, parcel/address and an attributes object. Uploaded and collected raw fields can be retained with source-specific names. Do not substitute ingestion time for an actual publication or measurement date when the source supplies one.

Canonical field selection is deterministic, not a learned fact generator. For example, recorder evidence has preference for owner and debt, assessor evidence for assessed value, market evidence for estimated value, and zoning evidence for zoning. Category preference cannot substitute for judgment about an individual source's reliability. Audit retained conflicts before relying on a result.

## Collection and scraping

Go supports direct CSV/JSON and paginated ArcGIS/Socrata endpoints. A configured source includes explicit column mappings and options. The collector only requests HTTPS hosts in its allowlist, validates public DNS addresses, pins its connection to validated addresses, bounds pages and response sizes and rejects unsafe redirects. The Python fallback is designed for small direct CSV/ArcGIS imports; use Go for hardened remote bulk collection.

`scripts/scrape.py` supplies a separate HTML-table scraper and local HTML preprocessor. It fetches a publisher-permitted HTTPS page or reads a downloaded HTML file, extracts the selected table, maps headers to canonical fields and writes NDJSON. It needs no agent. Dynamic JavaScript sites, CAPTCHA gates, document OCR and source-specific pagination require additional adapters. Scheduled collection can use cron, systemd timers or your own workflow runner.

## Operational scope

This is a functional first release, not an assertion of nationwide connected coverage or a completed enterprise hardening audit. It includes real ingestion contracts, independently compiled services, persistence, retrieval, model training, UI operations, a reproducible 1 GiB benchmark, and tests. Live source access and mappings must be configured. The interface reports measured source and record counts and labels synthetic examples.

Single-token access is intended for an operator or trusted gateway. Role-based authorization, multi-tenant isolation, external SSO, background distributed queues, high availability and PostgreSQL migration are extensions. The scout exposes response caps and total matches; CSV export includes all stored properties.
