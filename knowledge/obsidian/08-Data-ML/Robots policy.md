---
title: "Robots policy"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["robots"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Robots policy

Robots directives describe crawler access preferences under the Robots Exclusion Protocol. Site terms and legal access rights require separate review.

## 101XVC workflow

- Fetch and cache robots.txt for the actual origin
- Apply user-agent-specific rules
- Re-check redirected destinations
- Treat unavailable policy conservatively in the included harvester

## Related notes

[[Responsible crawling]], [[Source caching]], [[SEC source harvesting]]

## Primary references

- [RFC 9309 Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
