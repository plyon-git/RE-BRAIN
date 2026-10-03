# 101XVC BRAIN Obsidian Vault

Open this directory as an Obsidian vault and start at `00-Start/101XVC BRAIN Knowledge Home.md`.

This version contains 158 original topic notes, 10 templates, 53 completed-transaction records, and 66 primary-reference links. It is a curated starting corpus, not literally all real estate knowledge.

`_data/manifest.json` describes all topic and deal notes. `_data/deals.json` and `_data/deals.csv` contain structured case facts. `_data/sources.json` preserves source URLs, locators, access dates, scope, and redistribution notes. `reported_gain_usd` is issuer-reported accounting gain, never invented cash profit. `cost_basis_usd`, `realized_cash_profit_usd`, and `realized_irr` are null when unsupported. `disclosed_value_type` prevents a whole-asset valuation from being read as seller proceeds.

Two JV contribution cases are non-cash educational precedents. The Park Loggia 2021 period has a positive transaction gain but a negative result after the separately reported period operating costs; it is labeled explicitly. Portfolio and condominium aggregates are not unit-level profit records.

Rebuild offline with `python3 _tools/build_vault.py`. Validate with `python3 _tools/validate_vault.py`. Optional source harvesting requires a real identifying user agent and authorized connectivity; run `_tools/harvest_sources.py --help`. It is not required for reading, search, or local ML.

No Obsidian community plugin, GPT API, scraper service, or paid AI account is required. Obsidian itself is optional. Markdown and JSON remain readable independently.
