# 101XVC BRAIN

Independent property intelligence for 101XVC. Assessor, deed, zoning, permit and market evidence becomes one attributable property record, with deterministic underwriting, deal scouting, local machine learning and a searchable Obsidian knowledge vault.

**No GPT agent or hosted model API is required.** Run it locally, inside Docker or on infrastructure you control.

## Start locally

Requires Python 3.11+ and no extra Python packages.

```bash
python3 scripts/run.py
```

Open http://127.0.0.1:8080 and choose **Load demo** for explicitly synthetic examples. Core services use SQLite and keep records/models under `runtime/`. Configure sources to collect public records. The Python launcher provides local parcel resolution; the full Docker stack runs compiled Go and Rust services.

## Run all services

```bash
cp .env.example .env
# Set your own strong BRAIN_API_KEY and collector host allowlist in .env.
docker compose up --build -d
```

The browser interface, Python API, Go collectors, Rust parcel resolver and local Python ML/NLP run together. Enter your token in the browser. Database and model files persist in volumes.

## What is included

- Property registry, field provenance, retained conflicts and county-scoped parcel identities.
- CSV/JSON, ArcGIS and Socrata collection; independent HTML-table scraper.
- Watchlists, scored deal scout, explicit cost and fee-split underwriting, complete CSV export and operations history.
- Locally trainable logistic regression, TF-IDF vault retrieval and rule-based document extraction.
- XVCbrain Underwriting Intelligence: transaction episodes, offers and bids, settlements, cost and cash reconciliation, versioned rules, immutable decision snapshots, reviewed model promotion and rollback, competing-outcome closing forecasts, cash timing, portfolio scenarios and daily execution priorities.
- Content-addressed local document storage with SHA256 integrity and property/episode links.
- Original real estate knowledge notes and source-backed completed dispositions in an Obsidian vault.
- More than **1 GiB** of deterministic synthetic property evidence for ingestion and fusion load testing, with shard checksums. This is benchmark data, not live county coverage.
- Standalone full-program and Obsidian ZIPs in [Releases](https://github.com/plyon-git/RE-BRAIN/releases).

The bundled ML reference uses synthetic labels and is identified accordingly. Train and validate using your own consistently labeled outcomes before relying on predictions. Public disposition gains retain their disclosed measurement type and do not imply a transaction IRR.

## Read the guides

| Guide | Purpose |
|---|---|
| [Hosting](docs/HOSTING.md) | Local operation, Docker and your own domain |
| [Architecture](docs/ARCHITECTURE.md) | How languages and data contracts work together |
| [Local ML and NLP](docs/LOCAL-ML.md) | Model training, search and limitations |
| [Underwriting intelligence](docs/UNDERWRITING.md) | All 12 components, transaction learning and forecast evidence gates |
| [Quick start](docs/QUICKSTART.md) | Steps from first import to settled outcomes and model validation |
| [Benchmark](docs/BENCHMARK.md) | Generate, verify and bounded-import the full corpus |
| [Knowledge](docs/KNOWLEDGE.md) | Vault structure, source evidence and profitable dispositions |
| [Collector](services/collector/README.md) | Publisher endpoints, mappings and security |
| [Resolver](services/resolver/README.md) | Cross-language identity rules |

## Verify independently

```bash
python3 -m unittest discover -s tests -v
python3 services/resolver/tests/check_python_parity.py
node --input-type=module --check < web/app.js
node --input-type=module --check < web/brain.js
(cd services/collector && go test -race ./...)
(cd services/resolver && cargo test --locked)
python3 scripts/integration.py --collector /path/to/brain-collector --resolver services/resolver/target/release/brain-resolver
python3 scripts/benchmark.py --verify --deep --output data/benchmark
```

The integration script starts actual services and checks authentication, idempotent fusion, persistent watchlists, underwriting math, local ML predictions, NLP retrieval and Go-to-Rust-to-Python ingestion. GitHub Actions repeats checks, regenerates the complete corpus, commits it and publishes downloadable archives with checksums.

## Ownership

Copyright 2026 101XVC. Proprietary software; see [LICENSE](LICENSE). Public source visibility does not create an open-source license. Third-party facts and dependencies retain their own rights. This release is a functioning baseline with documented production extensions, not a promise of universal data access or an audited enterprise deployment.
