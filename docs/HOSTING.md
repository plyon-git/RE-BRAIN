# Local operation and independent hosting

## Local Python installation

Requires Python 3.11 or newer. No third-party Python packages or model downloads are needed.

```bash
git clone https://github.com/plyon-git/RE-BRAIN.git
cd RE-BRAIN
python3 scripts/run.py
```

Open http://127.0.0.1:8080. The launcher starts the API and intelligence service and stops both together on Ctrl+C. Records and models persist under `runtime/`. This mode uses the API's Python parcel resolver and can consume uploaded records without Go or Rust. The Go and Rust services run as part of the complete Docker stack.

## All languages together

Install Docker Engine or Docker Desktop with Compose. Copy `.env.example` to `.env`, replace the secret and configure the collector hosts you intend to use.

```bash
docker compose up --build -d
docker compose logs -f
```

Open http://127.0.0.1:8080 and enter the Bearer token in the interface. Compose runs Python API, Go collectors, Rust resolver, Python ML/NLP and the browser interface. Health checks gate API startup until its private services are ready. Persisted Docker volumes survive container recreation.

## Publish on your own infrastructure

Use a Linux VPS, dedicated server or an internal machine with Docker. Bind the API to loopback and put an HTTPS reverse proxy in front. An Nginx example is in `deploy/nginx.conf`. Provision a certificate for your own domain. The app can use any hostname and has no ChatGPT hosting requirement.

Set a long random BRAIN_API_KEY, allowlist intended collector hosts, apply firewall rules and keep the resolver, collector and intelligence ports private. The bundled token provides single-operator authentication. Multi-user SSO, per-user authorization and organization tenancy require an upstream gateway or additional application work.

Back up the SQLite database with the SQLite backup API, not by copying an actively written database without its journal. Keep backups and model snapshots on durable storage. Rotate secrets, patch runtime images and test restores. For high write concurrency, replace SQLite storage with PostgreSQL before scaling replicas; do not run multiple independent API containers against divergent local databases.

## Data installation

The repository's `data/benchmark/` directory contains over 1 GiB of clearly labeled synthetic linked evidence. This corpus tests record fusion and ingestion throughput; it is not county coverage. Use `python3 scripts/benchmark.py --help` for generation, verification and bounded imports. The app does not automatically import a gigabyte during startup.

The Obsidian release ZIP opens as a standalone vault. The local NLP index reads the same Markdown inside `knowledge/obsidian/`. Source-backed case studies and synthetic benchmark attachments are labeled separately.
