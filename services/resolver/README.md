# 101XVC BRAIN resolver

Rust service that turns canonical property records into deterministic, county-scoped identities. It is an exact one-to-one mapper. It does not perform fuzzy matching or discard duplicates.

## Run

```sh
cargo test --locked
cargo run --release --locked
```

The service listens on port 8082. Set `BRAIN_RESOLVER_PORT` or `PORT` to override it. Set `BRAIN_API_KEY` to require `Authorization: Bearer <key>` or `X-API-Key: <key>` for resolution. `/health` remains available for container checks. The Docker image runs as a non-root user.

```sh
curl http://localhost:8082/health
curl -X POST http://localhost:8082/resolve \
  -H 'Content-Type: application/json' \
  -d '{"records":[{"county_fips":"08031","parcel_id":"00-0123","address":"123 Main St.","state":"CO"}]}'
```

## Identity contract, version 1

`county_fips` must be a string containing exactly five ASCII digits. This validates the format rather than verifying the code against a geographic registry.

`normalized_parcel_id` uppercases the input and retains only ASCII A-Z and 0-9. It preserves every leading zero. A nonempty parcel produces `county_fips + '-' + normalized_parcel_id`.

The normalized address uppercases the input, replaces each character outside ASCII A-Z and 0-9 with a space, and collapses whitespace. Punctuation separates words. No street abbreviations or unit designators are inferred. `address_key` appends `|` and the trimmed, uppercase two-letter state when a state is supplied.

An empty normalized parcel requires a nonempty normalized address and a two-letter state. Its identity is `county_fips + '-ADDR-' + SHA256(address_key UTF-8).hex()[:20]`. The county prefix prevents merges across county boundaries. Address identities are exact provisional keys; independently abbreviated addresses can remain separate until authoritative parcel data arrives.

Each request must contain between 1 and 10,000 records. The whole batch is rejected with HTTP 400 if any identity is invalid, including its zero-based `record_index`. Unknown canonical fields are ignored. Optional `parcel_id`, `address`, and `state` accept strings or null. County FIPS accepts only a string.

## Request limits

Requests use `Content-Length`. Transfer encoding and duplicate headers are rejected. Header size is limited to 16 KiB, body size to 2 MiB, and each request has a total read deadline of 5 seconds. A bounded worker pool and connection queue limit resource usage. Parcel IDs are limited to 128 UTF-8 bytes, addresses to 512 bytes, and raw states to 32 bytes. Connections close after each response.

## Cross-language checks

`tests/identity_golden.json` is consumed by the Rust integration test and the dependency-free Python parity checker. Run `python3 tests/check_python_parity.py` to verify fixture consistency. With the service running, `python3 tests/check_python_parity.py --url http://localhost:8082` additionally checks live HTTP parity. The checker reads `BRAIN_API_KEY` from the environment when authentication is configured.
