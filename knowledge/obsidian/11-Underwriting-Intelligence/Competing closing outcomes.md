---
title: "Competing closing outcomes"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "underwriting-intelligence"]
source_ids: ["survival_competing"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Competing closing outcomes

Closing, cancellation, and expiration can be mutually exclusive terminal outcomes for an episode. Cause-specific cumulative incidence preserves that competition.

## 101XVC workflow

- Define outcome causes and episode boundaries consistently
- Keep unfinished episodes right-censored
- Estimate closing probability by each horizon with risk-set support
- Do not treat cancellations as ordinary censoring when estimating actual closing incidence

## Related notes

[[Right censoring]], [[Time origin and landmark forecasts]], [[Cash receipt lag]]

## Primary references

- [Analysis of Competing Risks](https://scikit-survival.readthedocs.io/en/stable/user_guide/competing-risks.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
