---
title: "Probability calibration audit"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "underwriting-intelligence"]
source_ids: ["sklearn_calibration"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Probability calibration audit

Calibration compares forecast probabilities with observed frequencies over comparable sufficiently observed cases. A rank score is not a calibrated probability.

## 101XVC workflow

- Preserve original horizon predictions
- Evaluate mature or appropriately censoring-adjusted outcomes
- Show bin counts and uncertainty
- Report discrimination and proper scores separately from reliability

## Related notes

[[Model calibration]], [[Competing closing outcomes]], [[Model promotion gate]]

## Primary references

- [Probability Calibration](https://scikit-learn.org/stable/modules/calibration.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
