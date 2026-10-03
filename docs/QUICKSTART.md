# Run 101XVC BRAIN

1. Clone this repository, open its folder and run `python3 scripts/run.py`. Open http://127.0.0.1:8080. For the complete compiled-service stack, configure `.env` and run `docker compose up --build -d` instead.
2. Choose **Load demo data** to explore 40 clearly synthetic properties. Demo records never become real closing labels. To use your own records, open **Source network**, create a source with the correct category/state/county and import CSV or JSON with explicit column mappings. Preserve leading zeros in parcel numbers.
3. Open a property in **Property registry**. Review its source observations, conflicting fields and selected provenance. Candidate comparable records need independent verification before valuation reliance.
4. Open **Underwriting intelligence** and select the property. Create a transaction episode with asking price, deadlines, partner/buyer identifiers and relevant constraints. Append recorded offers, executable bids, milestone evidence and expenses to the transaction ledger. Stated interest and executable demand remain separate.
5. Read the live report and test price, repair and expense assumptions side by side. It produces opening/target/maximum offers, conditional economics, missing evidence and the next action. Forecast probabilities remain unknown until an eligible local model supports them. Save the decision snapshot before acting; record the actual action and later outcome separately.
6. Store supporting documents through the document tab. Files are content-addressed locally and linked to properties and episodes. A document reference does not independently verify a title finding; capture the qualified professional's status in a milestone.
7. At funded closing, append settlement evidence that reconciles gross spread, partner share and 101XVC receipts, then record actual cash receipt timing and expenses. Settlement corrections append a replacement referencing the previous event. Cancellations, expirations and still-open opportunities belong in the ledger too.
8. Use **Model registry** to train candidate valuation, repair, seller acceptance, closing or cash models from consistently labeled decision snapshots or supplied rows. Read the chronological holdout diagnostics and support limits. Eligible real-data candidates require explicit promotion; previous validated versions remain available for rollback. Synthetic benchmark models cannot be promoted into underwriting production.

Use the daily queue to prioritize unresolved documents, inspections, partner reviews and follow-ups. Portfolio views distinguish estimated spread, retained contribution, funded transactions, collected cash, capacity and concentration. The source-backed Obsidian vault supports offline search and learning; its public-company cases do not substitute for 101XVC transaction outcome labels.

For the performance corpus, `python3 scripts/benchmark.py --verify --deep` checks all files. A bounded four-source import is:

```bash
python3 scripts/benchmark.py --import-url http://127.0.0.1:8080/api/ingest --max-records 100 --all-categories
```

For authenticated deployments, set `BRAIN_API_TOKEN` for that importer. The benchmark intentionally is not imported automatically at startup.

The full-program ZIP contains the source, vault and more than 1 GiB of generated benchmark observations. The Obsidian ZIP opens independently and carries that corpus as explicitly synthetic attachments. Compression makes each download smaller than the extracted data. Exact sizes and hashes are recorded in PACKAGE-MANIFEST and SHA256SUMS release assets.
