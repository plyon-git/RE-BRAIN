# XVCbrain Underwriting Intelligence

The underwriting subsystem connects permanent property identities to transaction episodes, evidence, actions, outcomes, economics, and local model versions. It runs on the same locally hosted platform without GPT or a hosted machine-learning service. The user's complete twelve-component specification is preserved in [UNDERWRITING-REQUIREMENTS.md](UNDERWRITING-REQUIREMENTS.md). The Obsidian vault includes a twelve-component map and 24 related operating notes.

This release supplies transaction infrastructure and trainable statistical baselines. It does not establish improved realized contribution, calibrated closing forecasts, causal intervention effects, or an optimal marketing budget for 101XVC. Those are measurable acceptance criteria requiring the company's actual time-stamped transaction evidence and later outcomes.

## Requirement coverage and boundaries

| Component | Implemented foundation | Evidence or extension still required |
|---|---|---|
| 1. Permanent property and transaction record | Canonical parcel identity, linked property episodes, append-only transaction events, and saved decision snapshots. | Review disputed matches and ownership authority; store original documents through an authorized evidence workflow. |
| 2. Acquisition and evidence | Go collection, local ingestion, source provenance, observation times, document-text extraction, and collector status. | Configure each county/feed adapter and ingest CRM, inspection, escrow, and settlement evidence. Public sources alone cannot teach internal operating outcomes. |
| 3. Local valuation and repairs | Separate locally trained valuation and repair regressions, explicit model versions, and evaluation records. | Real comparable transactions, actual repair costs, geography/condition coverage, and separate as-is/ARV labels. A baseline prediction is not an appraisal or a validated ARV range. |
| 4. Offer and negotiation | Transparent ceiling arithmetic, candidate-price observational scoring when supported, acceptance baseline, and configured cash/capacity/rule gates. | Full joint price/terms optimization, causally identified acceptance curves, and prospectively reliable expected contribution. Historical accepted prices do not reveal an unoffered lower price's outcome. |
| 5. Seller response and follow-up | Recorded offers, response events, notes, and local candidate fact extraction. | Source review, workflow-specific seller outcomes, controlled follow-up comparisons, and communication integrations. An extracted amount requires confirmation before it becomes an underwriting fact. |
| 6. Buyer and partner liquidity | Property-specific bid/partner events, executable-versus-interest labels, descriptive bid-deterioration flags, and report/queue evidence. | Verified capacity, bid validity, executable financing and visibility into partner-controlled demand. Stated interest is not funded liquidity. |
| 7. Closing-time and failures | Local competing-risk estimation with closing, cancellation, expiration, and right-censored observations; supported forecasts at 14, 30, 60 and 90 days. | Consistent episode time origins, verified terminal outcomes, sufficient comparable support, noninformative-censoring assumptions and prospective calibration. |
| 8. Execution and intervention | Work queues flag missing evidence, deadlines and transaction blockers; information-value fields show bounded price-scenario sensitivity. | Measured intervention costs and causal effects. Queue scores are prioritization heuristics; they do not prove that a concession, extension or inspection will increase contribution. |
| 9. State, partner and contract rules | Versioned operator-entered rules, effective applicability and rules separated from statistical models. | Qualified review of actual jurisdiction, contract and partner requirements. Default economics are assumptions, not laws or attorney-approved rules. |
| 10. Economics and portfolio | Separate gross spread, partner allocation, retained amounts, costs, actual cash events, and portfolio summaries. | Reconciled settlement/bank records, complete attributable expenses, concentration/capacity inputs and validated marginal-allocation experiments. Forecast fees are not collected cash. |
| 11. Learning ledger and model lifecycle | Immutable decision snapshots, dataset fingerprints, chronological holdout evaluation, candidate registry, promotion gates and rollback. | Complete historical refusals/failures/open episodes, authenticated labels, recurring drift review and prospective operating comparisons. More rows do not establish improvement. |
| 12. Independent platform | Python API/ML/NLP, Go collectors, Rust identity resolver, TypeScript interface, local storage and exports. | PostgreSQL/PostGIS, managed object storage, organization roles/SSO, distributed jobs and high-availability operations are extensions. Default persistence is SQLite and local model files. |

## Reports, assumptions, and unavailable predictions

Reports should show the property identity, current evidence, bids, rule version, explicit arithmetic, model status, missing inputs, and an action queue. The configured minimum spread of $20,000 and partner split of 50% are editable operating assumptions. They are not independently reviewed state requirements or universal deal economics.

If an eligible model has not been trained and explicitly promoted, its prediction remains `null` with an untrained/unsupported status and limitations. Insufficient input or cohort support also requires abstention. Missing observed cash is not zero cash; an absent probability is not a low probability. The legacy synthetic opportunity classifier demonstrates the separate local training pipeline and does not supply validated transaction probabilities to this subsystem.

Keep valuation, assessed value, as-is value, ARV, executable bid price, offer ceiling and expected retained receipts distinct. A seller-acceptance score estimates association at an observed price/terms combination; it cannot establish acceptance under a different intervention. An offer ceiling computed from entered prices and costs is scenario arithmetic, rather than a learned optimum. Predictive uncertainty, missing inspection evidence and unavailable demand information remain visible.

The initial negotiation heuristic opens at 90% and targets 95% of the computed ceiling, subject to recorded asking-price and configured constraints. If promoted acceptance and closing estimates, executable demand, loss exposure, cash requirements and complete recorded expense amounts exist, candidate prices can be ranked by the disclosed observational score `P(acceptance) × P(closing within 90 days | stage) × retained fee − expenses − P(acceptance) × P(no closing within 90 days) × loss exposure`. This combines separate historical fits and entered assumptions; it is not a causal acceptance estimate or a guarantee that the selected price maximizes realized contribution. Closing probability is not independently refitted for every hypothetical term combination.

Bid deterioration compares earlier and later recorded firm-bid medians when enough history exists. Buyer mix and conditions can explain changes. Value-of-information fields calculate a retained-receipt sensitivity bound across entered bid scenarios, and optionally subtract an entered information cost; they do not calculate an expected information benefit. Capacity checks compare recorded active commitments against an entered limit. Unobserved buyer availability and partner workload remain unknown.

## Local model lifecycle

The registry supports the targets `valuation`, `repairs`, `acceptance`, `closing`, and `cash`. Numeric value/repair targets use a local regularized regression baseline. Acceptance uses local logistic regression. Closing uses Aalen–Johansen cumulative incidence for mutually exclusive terminal events; open episodes contribute censoring rather than invented failures. Cash uses an empirical observed collection-lag baseline. None requires scikit-learn, scikit-survival, MLflow or a remote inference provider at runtime.

Training rows must identify the property, decision timestamp, usable features and observed target. Value/repair labels should match a consistently defined realized outcome; acceptance labels should record the actual offered terms and response; closing labels need a duration and terminal event or censoring status; collection labels need actual funded-to-collected cash intervals. Preserve both observation and availability times in the underlying ledger. Training cannot automatically authenticate a user-supplied outcome or recover missing original timestamps.

Training produces a candidate rather than replacing the active model. Evaluation uses later observations and disjoint property identities, with fitted transformations derived from the training period. Each candidate records support, dataset fingerprint, validation split, metrics, limitations and eligibility. Promotion requires the implemented support and quality gates and excludes candidates marked synthetic. Review the returned gate reasons rather than assuming that any trainable candidate is deployable. Retain the previous model and use rollback when warranted.

The initial gates are explicit engineering thresholds rather than a guarantee of operational reliability:

| Gate | Current requirement |
|---|---|
| Overall support | At least 20 usable labeled rows, with at least 12 earlier training and 5 later holdout observations; property identities do not overlap across the split. |
| Acceptance support | A recorded offered-price feature; at least 3 observations of each response class in training and 2 of each class in holdout. Prices outside training support are refused at inference. |
| Closing support | At least 5 closed and 3 competing-terminal observations in training. A stage-specific estimate requires 20 cohort labels; otherwise the report clearly uses the global cohort. |
| Cash cohort support | At least 10 observed receipts per supported partner/state/county cohort and at least two supported cohorts for a differentiated empirical model. Global-only estimates generally cannot beat their identical global baseline. |
| Baseline improvement | At least 1% relative improvement in held-out MAE for continuous targets or Brier loss for probabilities. |
| Calibration/interval check | Probability expected calibration error at most 0.25; where regression intervals are evaluated, observed coverage at least 0.60 for nominal 80% intervals. These permissive small-sample checks do not certify calibration. |
| Synthetic evidence | Synthetic training candidates cannot be promoted. Correctly identify synthetic data; the software cannot detect a false declaration of real outcomes. |
| Replacement and rollback | A replacement must additionally improve on the active incumbent on its later holdout. Rollback can select a previously approved compatible version. |
| Separate ARV | ARV remains null unless separate ARV targets supply at least 12 fit and 5 holdout labels and improve the held-out baseline. As-is targets do not establish ARV. |

For value and repairs, compare held-out error with a simple baseline. For acceptance, inspect probability loss and reliability across supported cohorts. For closing, inspect horizon-specific errors, calibration and the observation time available at each horizon; a still-open episode before its horizon cannot be labeled a failure. For cash, review observed lag errors and the absence of uncollected-outcome information. A finite metric from a small cohort is not statistical evidence of transportability.

The baseline competing-risk model is cohort-level. It does not fit a complete time-varying hazard model, remove informative censoring, guarantee personal deadline forecasts, or identify why a contract failed. Updating a stage-conditioned forecast requires a consistent landmark definition and appropriate at-risk cohort. Cancellation and expiration should not be treated as independent censoring when estimating closing incidence.

## HTTP interface

The transaction API uses the `/api/brain` namespace alongside the existing ingestion/search APIs. Requests use the same configured Bearer authentication as the platform.

| Route | Purpose |
|---|---|
| `GET /api/brain/episodes` | List transaction episodes. |
| `POST /api/brain/episodes` | Create an episode linked to a property. |
| `GET /api/brain/episodes/:id` | Retrieve episode history and evidence. |
| `POST /api/brain/episodes/:id/events` | Append an offer, bid, milestone, cost, outcome or cash event. |
| `POST /api/brain/episodes/:id/decisions` | Save the immutable evidence/prediction/recommendation/action snapshot. |
| `GET /api/brain/rules`, `POST /api/brain/rules` | Retrieve or create versioned operating rules. |
| `GET /api/brain/report/:propertyid`, `POST /api/brain/report/:propertyid` | Retrieve underwriting or evaluate entered scenario assumptions. |
| `GET /api/brain/portfolio` | Retrieve separate transaction and collected-cash economics. |
| `GET /api/brain/queue` | Retrieve execution priorities and reasons. |
| `GET /api/brain/models` | Inspect candidate and active model status. |
| `POST /api/brain/models/train` | Train a candidate for the specified `kind` using supplied rows, or ledger-derived rows when `rows` is omitted. |
| `POST /api/brain/models/promote` | Promote an eligible candidate explicitly. |
| `POST /api/brain/models/rollback` | Restore a retained model version. |

Use the local browser interface for request forms and returned validation messages. See [HOSTING.md](HOSTING.md) for the standalone launcher, Docker deployment, authentication and backup procedures. Back up the SQLite database and model artifacts together with versioned evidence metadata. An immutable application snapshot is not tamper-proof storage; authorized operating-system/database access can alter underlying files.

## Learning data and acceptance criteria

Record the chain **evidence available → prediction → recommendation → actual action → outcome → settled economics**. Include refusals, rejected partner submissions, renegotiations, cancellations, expirations and open opportunities, not only successful funded closings. Save the original decision cutoff and exact feature/model/rule versions. Later outcomes and settlement amounts must not enter earlier decision features.

The public REIT transaction cases in the knowledge vault are educational source-backed precedents. Their accounting disposition gains do not supply company-level acceptance, closing probability, repair, or cash-profit training labels. The generated reference datasets and unit-test fixtures exercise code and performance; they are not completed 101XVC transactions or evidence of realized profitability.

Measure realized contribution per acquisition dollar, closing-forecast reliability and funded-to-collected cash time against the existing underwriting process on later comparable transactions. Use controlled or carefully designed comparisons before attributing gains to a recommendation. A budget allocator additionally needs incremental response evidence, costs, operational capacity, demand competition and loss exposure. Value-of-information scoring needs possible information outcomes and decision changes; a missing-document flag alone is not a calculated expected information value.

Official methodological references: [competing-risk cumulative incidence](https://scikit-survival.readthedocs.io/en/stable/user_guide/competing-risks.html), [probability calibration](https://scikit-learn.org/stable/modules/calibration.html), [data leakage and preprocessing](https://scikit-learn.org/stable/common_pitfalls.html), and [model registry lineage](https://mlflow.org/docs/latest/ml/model-registry/). These explain the underlying practices; this application's standard-library baselines are its own implementations. The external version strings in the preserved user specification are not declared runtime dependencies.
