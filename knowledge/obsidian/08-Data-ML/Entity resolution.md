---
title: "Entity resolution"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["nist_playbook"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Entity resolution

Entity resolution identifies when differently formatted records refer to the same property, company, or person.

## 101XVC workflow

- Normalize for comparison while preserving originals
- Use jurisdiction and parcel keys for property matches
- Assign confidence and review ambiguous candidates
- Avoid merging common names without independent evidence

## Related notes

[[Parcel identity]], [[Contact provenance]], [[Data quality checks]]

## Primary references

- [AI RMF Playbook](https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
