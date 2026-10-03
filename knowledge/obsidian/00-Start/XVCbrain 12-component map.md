---
title: "XVCbrain 12-component map"
kind: "map_of_content"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["index", "underwriting"]
---

# XVCbrain 12-component map

The user specification defines twelve connected capabilities. This map organizes the operating knowledge behind those requirements; it is not a claim that every mature capability has been implemented or validated. See repository documents `docs/UNDERWRITING-REQUIREMENTS.md` for the preserved specification and `docs/UNDERWRITING.md` for implementation boundaries.

| Component | Requirement | Operating knowledge |
|---|---|---|
| 1 | Permanent property and transaction record | [[Permanent transaction identity]] |
| 2 | Data acquisition and evidence engine | [[Underwriting evidence acquisition]] |
| 3 | Local valuation and repair models | [[Local value and repair model]] |
| 4 | Offer and negotiation optimizer | [[Offer negotiation optimization]] |
| 5 | Seller response and follow-up intelligence | [[Seller response evidence]] |
| 6 | Buyer and partner liquidity engine | [[Buyer partner liquidity]] |
| 7 | Closing-time and failure models | [[Competing closing outcomes]] |
| 8 | Execution and intervention engine | [[Intervention queue]] |
| 9 | State, partner and contract rule engine | [[Versioned transaction rules]] |
| 10 | Transaction economics and portfolio engine | [[Transaction portfolio economics]] |
| 11 | Permanent learning ledger and model improvement | [[Learning decision ledger]] |
| 12 | Independent operating platform | [[Independent underwriting platform]] |

## Evidence before automation

Reliable identity, time-stamped evidence, actual actions, observed outcomes, and [[Settled economics reconciliation]] precede predictive optimization. Open transactions remain [[Right censoring|right-censored]] at their observation cutoff. [[Counterfactual seller acceptance]], [[Value of information]], [[Marginal marketing allocation]], and [[Capacity aware acquisition]] require additional evidence before historical associations can justify an action.

Monitor [[Demand deterioration detection]], [[Probability calibration audit]], [[Temporal evidence availability]], and [[Model promotion gate]]. [[Cash receipt lag]] connects funded closing to actual collection. [[Time origin and landmark forecasts]] defines what a 14-, 30-, 60-, or 90-day forecast means.

[[Underwriting-Intelligence map]], [[101XVC BRAIN Knowledge Home]]
