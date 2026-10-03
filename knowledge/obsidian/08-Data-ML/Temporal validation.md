---
title: "Temporal validation"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["nist_playbook"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Temporal validation

Temporal validation evaluates predictions on later observations using only information available before the prediction time.

## 101XVC workflow

- Split by date before fitting transformations
- Keep the same property out of conflicting evaluation groups
- Retain dataset vintages
- Compare performance across market regimes

## Related notes

[[Data vintage]], [[Feature selection]], [[Model validation]]

## Primary references

- [AI RMF Playbook](https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
