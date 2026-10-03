---
title: "Data granularity"
kind: "operational_knowledge"
owner: "101XVC"
reviewed_utc: "2026-10-03"
tags: ["real-estate", "data-ml"]
source_ids: ["census_acs"]
evidence_scope: "Original analytical workflow with linked primary domain references"
---

# Data granularity

Granularity describes the smallest supported unit and period of measurement. A model cannot create factual resolution absent from the source.

## 101XVC workflow

- Keep parcel, tract, county, metro, and state levels distinct
- Document aggregation and allocation assumptions
- Avoid assigning survey facts to named individuals
- Flag mismatched geography in joins

## Related notes

[[Margins of error]], [[GIS joins]], [[Natural hazard exposure]]

## Primary references

- [ACS Data via API](https://www.census.gov/programs-surveys/acs/data/data-via-api.html)

Reference scope: the links support the topic domain. The workflow is original 101XVC analysis, not a quotation, jurisdiction-wide legal conclusion, or agency endorsement. Check the current authoritative requirements for the actual transaction.
