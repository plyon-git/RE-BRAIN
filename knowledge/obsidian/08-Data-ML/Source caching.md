---
title: "Source caching"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["robots", "sec_access"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Source caching

Caching separates evidence retrieval from analysis and reduces repeated traffic. Cache existence alone does not establish source freshness.

## 101XVC workflow

- Store original URL, retrieval time, response type, and SHA-256
- Verify changed content before replacing prior evidence
- Keep failed requests distinguishable from empty documents
- Restrict redistribution according to rights and license

## Related notes

[[Data freshness]], [[Evidence provenance]], [[Responsible crawling]]

## Primary references

- [RFC 9309 Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html)
- [SEC Webmaster Frequently Asked Questions](https://www.sec.gov/about/webmaster-frequently-asked-questions)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
