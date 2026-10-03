# Offline machine learning and NLP

The intelligence service operates with Python's standard library. Its search index and trained model are local files. Neither a GPT agent nor an external language model is involved in retrieval, classification, extraction, underwriting or ingestion.

## What runs

* TF-IDF cosine retrieval indexes Markdown in the Obsidian vault. Results return the original note, source links and a snippet.
* Regularized logistic regression trains from numeric opportunity features and binary outcome labels. Model files retain feature scales, weights, dataset fingerprint and holdout metrics.
* Rule-based NLP extracts candidate parcel IDs, currency amounts, dates and zoning tokens from supplied document text. Candidates retain a review-required flag.
* The original underwriting calculator uses explicit arithmetic. The additional [XVCbrain underwriting module](UNDERWRITING.md) combines those economics with separately validated valuation, repair, acceptance, closing and cash models when supported. A classifier score does not replace valuation, inspection or title review.

The local launcher initializes a 3,000-row **synthetic reference model** to demonstrate an active training and prediction pipeline. Its predictions are simulation outputs, not probabilities validated against actual profitable closings. Start with `--no-reference-model` to require your own labels.

## Train your model

POST `/api/train` with `{"rows":[{"features":{"equity_pct":0.45,"discount_pct":0.18,"repair_ratio":0.12,"ltv":0.55,"days_on_market":90,"tax_delinquent":1,"permit_count":2},"label":1}, ...]}`. At least 20 distinct labeled observations and 3 observations of each class are required. Labels should describe a consistently defined actual outcome after relevant expenses.

Fractions use 0 to 1, days use an integer, and permit count is a count. Missing features become zero. The service scales days by 365 and permit count by 10, caps normalized extremes, rejects nonfinite numbers, deduplicates examples and creates a deterministic stratified holdout. It reports holdout accuracy and Brier score. This small baseline does not establish calibration, causality or transportability across markets.

For production model selection, split by time and property, test separate counties, inspect calibration and class balance, monitor data drift and retain independently observed closed outcomes. Never use accounting gain from a public REIT as a substitute for transaction-level net investor returns.

The underwriting registry additionally requires explicit `label_available_at` knowledge dates. It purges training outcomes and censoring snapshots that were unavailable at the first holdout decision. Missing or contradictory availability dates prevent promotion; `outcome_at` alone cannot prove when the information was known. Old model versions without verified temporal validation cannot be promoted, restored or used for operational predictions.

GET `/api/models` reports the active model. POST `/api/predict` accepts `{"features":{...}}` and returns the estimated probability, feature contributions, model ID, training count and dataset limitations.

The vault can be extended with your own Markdown. Restart intelligence or POST `/reindex` to the internal intelligence service after edits. Its `/extract` endpoint accepts `{"text":"..."}`. These internal endpoints use the same Bearer key when configured.
