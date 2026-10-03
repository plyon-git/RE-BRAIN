# 101XVC BRAIN knowledge system

The program includes a local Obsidian vault at `knowledge/obsidian`. Open that directory as a vault and select `00-Start/101XVC BRAIN Knowledge Home.md`. Markdown files, YAML metadata, JSON, and CSV remain usable without Obsidian or a hosted AI service. The deployed search/NLP layer can ingest the same notes locally.

## Delivered corpus

| Material | Count | Scope |
|---|---:|---|
| Original operating knowledge notes | 182 | Acquisition, underwriting, financing, diligence, construction, asset management, markets, tax/legal review, data, classical NLP and ML |
| Reusable operating templates | 10 | Intake, investment committee, deal evidence, rehab, closing reconciliation, source registry, records requests, model cards, investor reporting, acquisition experiments |
| Completed transaction evidence records | 53 | Selected issuer-reported completed transactions with positive accounting disposition gains |
| Primary reference records | 70 | Issuer SEC disclosures, regulators, federal agencies, municipal sources, standards, and official technical documentation |
| Markdown files, including maps and indexes | 260 | Linked, searchable notes with source information |

The vault is a curated foundation, not literally all real estate knowledge. It does not establish that every positive-gain case produced positive investor cash profit. It does not contain guessed purchase prices, invented net returns, or copied publisher archives.

The additional `11-Underwriting-Intelligence` workstream has 24 original notes covering all twelve components in the supplied XVCbrain specification. Its explicit `00-Start/XVCbrain 12-component map.md` connects the requirements to operational knowledge, including competing outcomes, right censoring, cash receipt lags, counterfactual acceptance, liquidity, capacity, value of information, marginal spending, demand deterioration, calibration, temporal evaluation, reconciliation, and model promotion. This is knowledge coverage rather than a claim that each mature feature is implemented or statistically validated. The exact supplied specification is preserved in `docs/UNDERWRITING-REQUIREMENTS.md`; implementation boundaries are recorded in `docs/UNDERWRITING.md`.

## Completed deal evidence

Every case has a stable ID, asset, location, seller, actual disclosed closing date or period, source URL, source section, source access date, reported transaction value, value definition, gain, measurement scope, and limitations.

`disclosed_value_type` distinguishes gross sale price, gross contract price, whole-asset valuation, and deemed contribution value. For SL Green partial-interest sales, the reported whole-asset valuation is never relabeled as seller cash proceeds. Exact closing dates remain null where a source provides only a quarter or month. Dollar fields are normalized from the source's stated units.

`reported_gain_usd` is the issuer's accounting disposition gain. `cost_basis_usd`, `net_cash_proceeds_usd`, `realized_cash_profit_usd`, and `realized_irr` are null when the selected source record does not support them. It is invalid to treat sale price less accounting gain as an original purchase price or to calculate holding-period IRR without the dated cash flows.

The corpus contains 51 completed disposition records and two explicitly labeled non-cash joint-venture contribution cases. Among the 51, four are period-level condominium aggregates and one is a three-community aggregate. Other portfolio rows preserve their combined scope. Individual profits are not allocated from an aggregate.

The Park Loggia 2021 nine-month record is a useful negative boundary example: its reported transaction gain is positive before separately reported period costs, but the disclosed selected period costs exceed that gain. Its `evidence_status` explicitly states the negative-after-selected-period-costs result. Do not count it as a net-profitable cash investment.

The two Brandywine JV contribution records are completed non-cash contributions and deconsolidations with recognized gains. They are kept as educational accounting examples and separated from cash property sales.

Selected primary verification sources:

- [AvalonBay 2024 Q3 Form 10-Q](https://www.sec.gov/Archives/edgar/data/915912/000091591224000021/avb-20240930.htm), Note 6.
- [AvalonBay 2026 Q1 Form 10-Q](https://www.sec.gov/Archives/edgar/data/915912/000091591226000012/avb-20260331.htm), Note 6.
- [SL Green 2024 annual joint-venture disposition table](https://www.sec.gov/Archives/edgar/data/1040971/000104097125000019/R26.htm).
- [SL Green 2025 annual joint-venture disposition table](https://www.sec.gov/Archives/edgar/data/1040971/000162828026008669/R50.htm). The later annual One Vanderbilt 5% interest-sale gain is used rather than the earlier quarterly amount.
- [Essex 2024 real-estate interests table](https://www.sec.gov/Archives/edgar/data/920522/000092052225000024/R19.htm).
- [Brandywine 2023 real-estate investments table](https://www.sec.gov/Archives/edgar/data/1060386/000079081624000014/R46.htm), dispositions and contribution footnotes.

## Structured ingestion

The following files are the source of truth for corpus structure:

- `knowledge/obsidian/_data/manifest.json`: note inventory, counts, transaction-type distribution, evidence limits.
- `knowledge/obsidian/_data/sources.json`: source ID, official URL, publisher, locator, access date, redistribution scope.
- `knowledge/obsidian/_data/deals.json`: typed factual records and evidence classifications.
- `knowledge/obsidian/_data/deals.csv`: spreadsheet-ready transaction export; blank unknown fields are not zeros.

Index `.md` notes for text retrieval. Use structured deal facts for numeric filters and source-aware displays. Do not train an investment-performance predictor using accounting gain as a cash-profit target. These institutional disclosures are selected examples, not a representative statistical sample or an underwriting validation dataset for 101XVC's acquisition operation.

## Maintenance and validation

From the repository root:

```bash
python3 knowledge/obsidian/_tools/build_vault.py
python3 knowledge/obsidian/_tools/validate_vault.py
```

The builder runs entirely offline using the included editorial records. The validator checks wikilinks, note inventories, source references, gain signs, exact-date formats, unknown cash-return fields, and non-cash case classifications. It does not claim to verify a remote source's current availability.

## Optional official-source harvesting

```bash
python3 knowledge/obsidian/_tools/harvest_sources.py --dry-run --limit 8
python3 knowledge/obsidian/_tools/harvest_sources.py \
  --user-agent '101XVC BRAIN research your-real-contact@your-domain.com' \
  --source-id avb2024q3 --source-id slg2024jv --source-id bdn2023
```

Use a genuine contact-bearing user agent. The stdlib harvester allows configured official domains over HTTPS, validates public destinations, evaluates robots policy, rate-limits requests, limits response size, validates redirects, and records hashes and failures. It makes no evasive retries on access restrictions. Its default raw-source cache is outside the repository; do not redistribute full cached documents without checking rights.

Network access is necessary to acquire new evidence. Reading the vault and running local retrieval and inference do not require network access or GPT. Failed, oversized, robots-blocked, or unsupported source downloads are recorded as `manual_or_retry_required`. Retrieve unsupported material through the publisher's approved channel, add only supported facts and original summaries, then record the actual source and date.

Refresh legal and lending references before using them for current transactions. Source-domain links support topic context; the workflows are original analytical procedures and do not claim blanket agency endorsement or nationwide legal applicability.
