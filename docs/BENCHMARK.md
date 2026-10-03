# 101XVC BRAIN benchmark corpus

This repository includes more than **1 GiB (1,073,741,824 bytes)** of structured,
synthetic property evidence. The corpus exists to exercise ingestion, schema
normalization, provenance handling, property joins, comparative analysis and
large-file processing. It contains no scraped public records, real property
opportunities, real owner contacts or verified tax liabilities.

The generator uses real county names and five-digit county FIPS values as
geographic fixtures across the 15 101XVC program states: AL, AZ, CO, FL, GA, IL,
IN, KS, MO, NC, OK, SC, TN, TX and UT. Every address is explicitly synthetic;
all contact addresses use `example.invalid`. Generated coordinates approximate
county urban areas and are unsuitable for navigation, parcel surveys or risk
determinations. Zoning and hazard fields are test scenarios, not regulations or
government determinations.

## Useful evidence, not byte padding

Each synthetic parcel has four linked evidence records:

| Category | Evidence | Workload supported |
|---|---|---|
| Assessor | Property attributes, five years of assessments, tax status, owner/mailing fixture, improvements, legal description | Normalization, tax filtering, absentee selection, property features |
| Recorder | Deed, mortgage/deed of trust, tax-status instrument, three historical transfers, title-review flags | Entity matching, chain-of-title processing, encumbrance estimates |
| Zoning | District, permitted uses, dimensional standards, hazard scenarios, three permits, approximate polygon | Constraint filtering, geospatial parsing, provenance-aware review |
| Market | Eight sold comparables, market statistics, eight renovation trades, underwriting inputs, three sensitivity scenarios | Comparable ranking, underwriting arithmetic, scenario analysis |

Records vary by property, county, value distribution, physical attributes,
ownership type, condition, lien status, renovation scope and comparable sales.
They contain no random binary blobs or repeated padding paragraphs. Each parcel
has a deterministic unique ID and four unique evidence IDs. A shared `parcel_id`
and `county_fips` provide cross-category joins; `source_record_id` supports
idempotent ingestion.

All monetary amounts use USD. This corpus models a 50/50 disposition-share
scenario and a $20,000 minimum underwritten gross spread as **test inputs**. It
does not assert that any outcome, realized spread, property count or investment
return is guaranteed.

## Files and integrity

`data/benchmark/manifest.json` is authoritative for actual byte totals, parcel
counts, record counts and category statistics. It lists each shard's SHA-256,
byte length and NDJSON row count. No shard exceeds 32 MiB, which keeps individual
files below GitHub's ordinary Git file limit. All four category families are
tracked in Git, including their actual NDJSON content.

The manifest's generation timestamp is deliberately fixed for reproducibility.
It is not a claim about when government data was retrieved. Every record carries
`synthetic: true`, a generated-data basis and `is_live_public_record: false`.

## Generate and verify

Run commands from the repository root with Python 3.12 or later. Only the Python
standard library is required. Generation streams records to disk, maintaining
one parcel's evidence at a time and one buffered writer per category.

```bash
python3 scripts/benchmark.py --seed 101 --target-bytes 1073741824 --output data/benchmark
python3 scripts/benchmark.py --verify --output data/benchmark
python3 scripts/benchmark.py --verify --deep --output data/benchmark
```

Generation stops after a complete four-record parcel group reaches the target,
so the actual byte size exceeds the requested size slightly. `--verify` checks
every byte against the manifest, counts every row and checks shard limits.
`--deep` also parses every row, checks the schema version, validates synthetic
markers, checks parcel-ID format and compares rolling join-key hashes across
all four categories. Hash verification is the fast integrity
check; deep verification is appropriate after changing the generator/schema.

An existing output directory is protected from accidental replacement. Add
`--overwrite` explicitly to replace only its `manifest.json` and `*.ndjson`
benchmark files. Other files in that directory are untouched.

For a small development sample, use a separate directory:

```bash
python3 scripts/benchmark.py --quick --seed 101 --output /tmp/brain-benchmark-sample
python3 scripts/benchmark.py --verify --deep --output /tmp/brain-benchmark-sample
```

`--quick` caps the effective target at 1 MiB and includes the final complete
parcel group. It does not replace the full repository corpus. The same seed,
target and Python generator produce identical record bytes and shard hashes.

## Bounded API import

The application's default demo database remains small. Benchmark files are not
automatically imported on application startup. This avoids turning a normal
local launch into an expensive database import.

Each row includes the canonical ingestion fields: `source_id`,
`source_record_id`, `parcel_id`, `county_fips`, `state`, `address`, `category`,
`observed_at` and an `attributes` object. Category-specific evidence lives under
`attributes`, alongside normalized scalar columns consumed by the API. The
top-level `source` and `quality` fields preserve synthetic provenance for
external tooling.

The optional importer submits **assessor records only by default**, using the API's
`{"records": [...]}` batch envelope. The first 100 parcels across the 15 states
are imported by default, in batches of 25. It first registers the corresponding
manual synthetic source at the sibling `/api/sources` endpoint. Supply the
complete ingestion endpoint URL:

```bash
python3 scripts/benchmark.py --output data/benchmark \
  --import-url http://localhost:8080/api/ingest \
  --max-records 100 --batch-size 25
```

Add `--all-categories` to import all four linked evidence records for each
sample parcel, including normalized market inputs needed for underwriting:

```bash
python3 scripts/benchmark.py --output data/benchmark \
  --import-url http://localhost:8080/api/ingest \
  --max-records 100 --batch-size 25 --all-categories
```

For deployments requiring a token, set `BRAIN_API_TOKEN` through your normal
secret manager or shell environment. The importer supplies `X-API-Key` and
Bearer authorization headers; tokens are never written into corpus files.
The client permits at most 10,000 parcels per invocation, or 40,000 evidence
records when all categories are selected. Use a
dedicated database and external load-test runner to ingest the entire corpus.
API endpoint shape and validation errors are reported explicitly; HTTP failures
stop the import instead of being counted as successful inserts.

## Suggested load-test measurements

Measure source-row parsing throughput, successful evidence inserts per second,
repeat-import idempotency, memory use, cross-source parcel resolution,
provenance visibility, filtered-search latency and underwriting accuracy on
known fixture inputs. Record hardware and database settings beside results.
Do not compare synthetic values to real investor opportunities or treat this
corpus as a verified lead list.
