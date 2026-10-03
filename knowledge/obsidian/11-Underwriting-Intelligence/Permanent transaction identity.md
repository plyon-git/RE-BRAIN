---
title: "Permanent transaction identity"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "underwriting-intelligence"]
source_ids: ["nist_playbook"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Permanent transaction identity

An asset identity and a transaction episode are separate records. A property can be offered, refused, recontracted, and sold across multiple distinct episodes.

## 101XVC workflow

- Link canonical parcel and property IDs to each episode
- Preserve source-specific CRM IDs and owner entities
- Store conflicting fields with evidence
- Prevent duplicate episodes from inflating outcome counts

## Related notes

[[Parcel identity]], [[Entity resolution]], [[Learning decision ledger]]

## Primary references

- [AI RMF Playbook](https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
