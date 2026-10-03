---
title: "Counterfactual seller acceptance"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "underwriting-intelligence"]
source_ids: ["nist_playbook", "sklearn_leakage"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Counterfactual seller acceptance

An observed accepted offer provides evidence about that price and its terms. It does not establish what the same seller would have done under an unobserved alternative.

## 101XVC workflow

- Preserve all offered prices and terms, including refusals
- Record policy and selection effects
- Limit predictions to supported price-term regions
- Use controlled variation or reviewed causal methods before interpreting a negotiation change as an improvement

## Related notes

[[Seller response evidence]], [[Offer negotiation optimization]], [[Feature selection]]

## Primary references

- [AI RMF Playbook](https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook)
- [Common Pitfalls and Recommended Practices](https://scikit-learn.org/stable/common_pitfalls.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
