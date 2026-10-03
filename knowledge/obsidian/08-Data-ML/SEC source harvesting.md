---
title: "SEC source harvesting"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["sec_access"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# SEC source harvesting

SEC permits scripted access subject to its published fair-access requirements. An operational harvester should use a genuine contact-bearing user agent and conservative rate.

## 101XVC workflow

- Record canonical filing and section URLs
- Stay below published limits and respect errors
- Cache retrieved records and hashes
- Prefer small XBRL note tables for targeted extraction

## Related notes

[[Responsible crawling]], [[Closed deal evidence]], [[Source caching]]

## Primary references

- [SEC Webmaster Frequently Asked Questions](https://www.sec.gov/about/webmaster-frequently-asked-questions)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
