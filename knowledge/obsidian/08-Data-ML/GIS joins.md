---
title: "GIS joins"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["census_api"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# GIS joins

Spatial joins attach records through a defined coordinate system and geometry relationship. They are not inherently more reliable than the geometry.

## 101XVC workflow

- Record coordinate reference systems
- Check geocoding confidence
- Validate points near jurisdiction boundaries
- Keep address and parcel-identifier joins as independent checks

## Related notes

[[Parcel identity]], [[Data granularity]], [[County source registry]]

## Primary references

- [Census API User Guide: Example Queries](https://www.census.gov/data/developers/guidance/api-user-guide.Example_API_Queries.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
