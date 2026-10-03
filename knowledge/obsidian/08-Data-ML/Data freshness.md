---
title: "Data freshness"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["census_api"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Data freshness

Freshness is measured from the relevant observation or effective date, not merely when a scraper downloaded the page.

## 101XVC workflow

- Store publication, effective, and retrieval dates separately
- Set field-specific expiry rules
- Detect stale unchanged files
- Show age in decision views

## Related notes

[[Data vintage]], [[County source registry]], [[Responsible crawling]]

## Primary references

- [Census API User Guide: Example Queries](https://www.census.gov/data/developers/guidance/api-user-guide.Example_API_Queries.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
