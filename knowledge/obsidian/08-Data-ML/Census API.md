---
title: "Census API"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["census_api"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Census API

Census API queries should retain dataset year, variable names, geography predicates, annotations, and the exact request.

## 101XVC workflow

- Inspect the dataset variable dictionary
- Keep leading zeros in FIPS fields
- Retrieve uncertainty and annotation variables where relevant
- Cache responses and record retrieval failures explicitly

## Related notes

[[ACS interpretation]], [[GIS joins]], [[Data provenance]]

## Primary references

- [Census API User Guide: Example Queries](https://www.census.gov/data/developers/guidance/api-user-guide.Example_API_Queries.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
