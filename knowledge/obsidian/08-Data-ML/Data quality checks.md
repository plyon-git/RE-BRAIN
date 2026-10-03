---
title: "Data quality checks"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["nist_playbook"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Data quality checks

Data-quality checks protect joins and calculations by detecting missing identifiers, duplicate records, impossible values, unit mismatches, and stale observations.

## 101XVC workflow

- Specify field contracts and valid ranges
- Keep rejected rows with reasons
- Compare aggregate totals before and after transformations
- Treat null as unknown rather than zero

## Related notes

[[Entity resolution]], [[Data provenance]], [[Extraction quality]]

## Primary references

- [AI RMF Playbook](https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
