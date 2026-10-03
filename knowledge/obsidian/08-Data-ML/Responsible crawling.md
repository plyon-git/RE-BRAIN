---
title: "Responsible crawling"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["robots"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Responsible crawling

A crawler is a repeatable data-acquisition process with site-specific access policy, robots handling, rate limits, caching, and visible failures.

## 101XVC workflow

- Use an identifiable user agent
- Respect allowed paths and response backoff
- Avoid bypassing authentication or access restrictions
- Record blocked and unsupported sources without fabricating results

## Related notes

[[Robots policy]], [[SEC source harvesting]], [[Data provenance]]

## Primary references

- [RFC 9309 Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
