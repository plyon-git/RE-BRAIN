#!/usr/bin/env python3
"""Deterministic, synthetic property evidence for 101XVC BRAIN load testing.

This corpus is deliberately synthetic. County names/FIPS are geographic fixtures,
not provenance for public records. No record represents a real property, person,
sale, tax obligation or underwriting opportunity. Only Python's standard library
is required. Run --help for generation, integrity verification and bounded import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
from typing import Any, Iterator
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_BYTES = 1_073_741_824
SHARD_BYTES = 32 * 1024 * 1024
SCHEMA_VERSION = "101xvc-brain.synthetic-evidence.v1"
AS_OF_DATE = "2026-09-30"
CATEGORIES = ("assessor", "recorder", "zoning", "market")

# Geographic fixtures only. Addresses, parcel IDs, owners and records are fictional.
# County centroid, price/sqft and tax rate vary to support realistic workload skew.
COUNTIES = (
    ("AL", "Alabama", "Jefferson", "01073", "Birmingham", 33.5207, -86.8025, 146, .0062),
    ("AZ", "Arizona", "Maricopa", "04013", "Phoenix", 33.4484, -112.0740, 252, .0060),
    ("CO", "Colorado", "Denver", "08031", "Denver", 39.7392, -104.9903, 335, .0056),
    ("FL", "Florida", "Orange", "12095", "Orlando", 28.5383, -81.3792, 236, .0115),
    ("GA", "Georgia", "Fulton", "13121", "Atlanta", 33.7490, -84.3880, 235, .0108),
    ("IL", "Illinois", "Cook", "17031", "Chicago", 41.8781, -87.6298, 225, .0198),
    ("IN", "Indiana", "Marion", "18097", "Indianapolis", 39.7684, -86.1581, 145, .0101),
    ("KS", "Kansas", "Johnson", "20091", "Overland Park", 38.9822, -94.6708, 198, .0142),
    ("MO", "Missouri", "Jackson", "29095", "Kansas City", 39.0997, -94.5786, 165, .0122),
    ("NC", "North Carolina", "Mecklenburg", "37119", "Charlotte", 35.2271, -80.8431, 227, .0098),
    ("OK", "Oklahoma", "Oklahoma", "40109", "Oklahoma City", 35.4676, -97.5164, 140, .0108),
    ("SC", "South Carolina", "Greenville", "45045", "Greenville", 34.8526, -82.3940, 190, .0089),
    ("TN", "Tennessee", "Davidson", "47037", "Nashville", 36.1627, -86.7816, 270, .0076),
    ("TX", "Texas", "Harris", "48201", "Houston", 29.7604, -95.3698, 180, .0218),
    ("UT", "Utah", "Salt Lake", "49035", "Salt Lake City", 40.7608, -111.8910, 285, .0061),
)
STREET_NAMES = (
    "Juniper", "Cedar", "Aspen", "Willow", "Meadow", "Ridge", "Harbor", "Orchard",
    "Linden", "Cypress", "Maple", "Summit", "Hawthorn", "Sycamore", "Magnolia",
    "Prairie", "Brook", "Walnut", "Pine", "Elm", "Chestnut", "Cottonwood",
)
LAST_NAMES = ("Rowan", "Hale", "Vale", "Marlow", "Ashby", "Briar", "Finch", "Lennox", "Oakley", "Wren")
FIRST_NAMES = ("Alex", "Jordan", "Morgan", "Taylor", "Casey", "Riley", "Cameron", "Avery", "Parker", "Reese")
CONDITIONS = ("poor", "fair", "average", "good", "excellent")
CONDITION_FACTOR = {"poor": .58, "fair": .73, "average": .9, "good": 1.04, "excellent": 1.18}


def encode(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def date_between(rng: random.Random, start_year: int, end_year: int) -> str:
    year = rng.randint(start_year, end_year)
    return f"{year:04d}-{rng.randint(1, 9 if year == 2026 else 12):02d}-{rng.randint(1, 28):02d}"


def round_money(value: float) -> int:
    return max(0, int(round(value / 100) * 100))


def evidence_base(category: str, parcel: dict[str, Any], seed: int, index: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        "record_id": f"SYN-{category.upper()}-{seed}-{index:09d}",
        "source_id": f"synthetic-benchmark-{category}",
        "source_record_id": f"SYN-{category.upper()}-{seed}-{index:09d}",
        "parcel_id": parcel["parcel_id"],
        "county_fips": parcel["county_fips"],
        "state": parcel["state"],
        "address": parcel["address"],
        "category": category,
        "observed_at": AS_OF_DATE + "T12:00:00Z",
        "source": {
            "source_type": category,
            "provider": "101XVC BRAIN synthetic benchmark generator",
            "jurisdiction_fips": parcel["county_fips"],
            "source_url": f"https://benchmark.example.invalid/{category}/{parcel['parcel_id']}",
            "retrieved_at": AS_OF_DATE + "T12:00:00Z",
            "effective_date": AS_OF_DATE,
            "license": "101XVC proprietary synthetic test fixture",
            "is_live_public_record": False,
        },
        "quality": {
            "identity_confidence": .99,
            "temporal_status": "synthetic_snapshot",
            "field_basis": "generated_test_data",
            "restrictions": ["load_testing_only", "not_for_investment_decisions", "not_real_personal_data"],
        },
    }


def property_records(seed: int, index: int) -> tuple[dict[str, Any], ...]:
    # Independent PRNG per parcel gives reproducible groups even when partitioned.
    rng = random.Random((seed << 48) ^ index ^ 0x101BC0DE)
    state, state_name, county, fips, city, lat, lon, local_ppsf, tax_rate = COUNTIES[index % len(COUNTIES)]
    parcel_id = f"BRAIN-SYN-{fips}-{seed}-{index:09d}"
    area = rng.randrange(720, 3610, 10)
    beds = max(1, min(6, round(area / 650)))
    baths = rng.choice([1, 1.5, 2, 2.5, 3, 3.5])
    year_built = rng.randint(1940, 2023)
    condition = rng.choices(CONDITIONS, [6, 18, 41, 28, 7])[0]
    lot_sqft = rng.randint(2800, 22500)
    latitude = round(lat + rng.uniform(-.085, .085), 6)
    longitude = round(lon + rng.uniform(-.115, .115), 6)
    street = rng.choice(STREET_NAMES)
    number = 100 + (index * 37) % 9800
    address = f"{number} Synthetic {street} {rng.choice(['Way', 'Lane', 'Court', 'Drive'])}"
    zip_code = f"{10000 + int(fips) % 80000:05d}"
    arv = round_money(area * local_ppsf * rng.uniform(.87, 1.18))
    current_value = round_money(arv * CONDITION_FACTOR[condition] * rng.uniform(.96, 1.04))
    assessed_land = round_money(current_value * rng.uniform(.13, .31))
    assessed_improvements = max(0, current_value - assessed_land)
    annual_tax = round(current_value * tax_rate, 2)
    years_owned = rng.randint(1, 30)
    owner_type = rng.choices(["individual", "trust", "llc"], [70, 12, 18])[0]
    owner_id = f"SYN-OWNER-{seed}-{index:09d}"
    owner_name = (
        f"Synthetic {rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} {index}"
        if owner_type == "individual"
        else f"Synthetic {street} Holdings {index} {'Trust' if owner_type == 'trust' else 'LLC'}"
    )
    absentee = rng.random() < .30
    delinquent = rng.random() < .12
    months_past_due = rng.choice([3, 6, 12, 18, 24]) if delinquent else 0
    delinquent_balance = round(annual_tax * months_past_due / 12 * 1.08, 2)
    purchase_year = max(year_built, 2026 - years_owned)
    purchase_price = round_money(current_value / (1.045 ** (2026 - purchase_year)) * rng.uniform(.75, 1.04))
    repair_per_sqft = {"poor": 73, "fair": 47, "average": 24, "good": 10, "excellent": 4}[condition]
    repair_cost = round_money(area * repair_per_sqft * rng.uniform(.9, 1.12))
    mortgage_principal = round_money(purchase_price * rng.uniform(.45, .85)) if rng.random() < .67 else 0
    mortgage_balance = round_money(mortgage_principal * max(.08, 1 - years_owned / 35))
    parcel = {
        "parcel_id": parcel_id, "county_fips": fips, "state": state, "state_name": state_name,
        "county": county, "city": city, "address": address, "zip": zip_code,
        "latitude": latitude, "longitude": longitude, "owner_id": owner_id,
        "owner_name": owner_name, "owner_type": owner_type, "square_feet": area,
        "lot_square_feet": lot_sqft, "bedrooms": beds, "bathrooms": baths,
        "year_built": year_built, "condition": condition, "property_type": "single_family",
        "assessed_value": current_value, "estimated_arv": arv,
        "repair_estimate": repair_cost, "mortgage_balance": mortgage_balance,
        "tax_delinquent": delinquent, "delinquent_tax_balance": delinquent_balance,
        "absentee_owner": absentee, "synthetic": True,
    }

    assessor = evidence_base("assessor", parcel, seed, index)
    assessor["parcel"] = parcel
    assessor["assessment"] = {
        "assessment_year": 2026, "land_value": assessed_land,
        "improvement_value": assessed_improvements, "total_assessed_value": current_value,
        "taxable_value": round_money(current_value * (0.85 if not absentee else 1)),
        "assessment_ratio": 1, "tax_rate": tax_rate, "currency": "USD",
        "annual_tax": annual_tax, "homestead_exemption": not absentee,
        "delinquent_balance": delinquent_balance, "months_past_due": months_past_due,
        "assessment_history": [
            {"year": y, "land_value": round_money(assessed_land / 1.032 ** (2026-y)),
             "improvement_value": round_money(assessed_improvements / 1.039 ** (2026-y)),
             "tax_paid": not delinquent or y < 2025, "annual_tax": round(annual_tax / 1.04 ** (2026-y), 2)}
            for y in range(2022, 2027)
        ],
    }
    assessor["improvements"] = {
        "building_count": 1, "stories": rng.choice([1, 1, 2]),
        "roof_cover": rng.choice(["composition_shingle", "metal", "tile"]),
        "roof_year": min(2026, year_built + rng.randint(0, 35)),
        "exterior": rng.choice(["brick_veneer", "wood_siding", "stucco", "fiber_cement"]),
        "foundation": rng.choice(["slab", "crawlspace", "basement"]),
        "heating": rng.choice(["heat_pump", "gas_furnace", "electric_forced_air"]),
        "cooling": "central_air", "garage_spaces": rng.choice([0, 1, 2, 2, 3]),
        "pool": rng.random() < .09, "occupied": rng.random() > .11,
        "water": "municipal", "sewer": "municipal",
        "renovation_year": rng.choice([None, rng.randint(max(2000, year_built), 2026)]),
    }
    assessor["mailing"] = {
        "name": owner_name,
        "address": f"{500 + index % 9900} Synthetic Mailing Boulevard" if absentee else address,
        "city": "Synthetic Mailing City" if absentee else city,
        "state": rng.choice(["CO", "TX", "FL", state]) if absentee else state,
        "zip": zip_code,
        "contact_email": f"synthetic-owner-{seed}-{index}@example.invalid",
        "contact_status": "fixture_only_not_contactable",
    }
    assessor["legal_description"] = {
        "subdivision": f"Synthetic {street} Test District {index % 73}",
        "block": str(1 + index % 90), "lot": str(1 + index % 400),
        "plat_reference": f"SYN-PLAT-{fips}-{index // 400:06d}",
        "coordinate_reference_system": "EPSG:4326", "boundary_is_approximation": True,
    }

    recorder = evidence_base("recorder", parcel, seed, index)
    grant_date = f"{purchase_year}-06-{1+index%28:02d}"
    recorder["instruments"] = [
        {
            "instrument_id": f"SYN-DEED-{fips}-{seed}-{index:09d}", "type": "warranty_deed",
            "recorded_date": grant_date, "execution_date": grant_date,
            "grantor": f"Synthetic Prior Owner {index}", "grantee": owner_name,
            "grantee_id": owner_id, "consideration_usd": purchase_price,
            "transfer_tax_usd": round(purchase_price * .002, 2), "arm_length": rng.random() > .08,
            "book": str(9000 + index // 250), "page": str(1 + index % 250),
            "parcel_ids": [parcel_id], "legal_description_match": True,
            "vesting": rng.choice(["sole_owner", "joint_tenants", "trustee", "entity"]),
            "signatures_verified": False, "signature_status": "synthetic_fixture",
        },
        {
            "instrument_id": f"SYN-MORTGAGE-{fips}-{seed}-{index:09d}",
            "type": "deed_of_trust" if state in ["CO", "NC", "TN", "TX", "UT", "AZ"] else "mortgage",
            "recorded_date": grant_date, "borrower": owner_name, "borrower_id": owner_id,
            "lender": f"Synthetic Test Lending Entity {1+index%41}",
            "original_principal_usd": mortgage_principal, "estimated_balance_usd": mortgage_balance,
            "interest_rate": round(rng.uniform(.0325, .081), 4), "term_months": 360,
            "maturity_date": f"{purchase_year+30}-06-{1+index%28:02d}",
            "released": mortgage_principal == 0, "seniority": 1,
            "balance_basis": "synthetic_amortization_fixture",
        },
        {
            "instrument_id": f"SYN-LIEN-{fips}-{seed}-{index:09d}", "type": "tax_status",
            "recorded_date": "2026-09-01", "debtor": owner_name,
            "claimant": f"Synthetic {county} County Tax Testing Authority",
            "amount_usd": delinquent_balance, "status": "open" if delinquent else "clear",
            "redemption_deadline": "2027-03-01" if delinquent else None,
            "is_judicial_finding": False, "parcel_ids": [parcel_id],
        },
    ]
    recorder["chain_of_title"] = [
        {"transfer_id": f"SYN-TRANSFER-{seed}-{index}-{n}",
         "year": max(year_built, purchase_year - (n+1)*rng.randint(4, 9)),
         "seller": f"Synthetic Historic Seller {index}-{n}",
         "buyer": f"Synthetic Historic Buyer {index}-{n}",
         "consideration_usd": round_money(purchase_price / 1.045 ** ((n+1)*6)),
         "document_type": rng.choice(["warranty_deed", "quitclaim_deed", "trustee_deed"]),
         "normalized_parcel_id": parcel_id, "synthetic": True}
        for n in range(3)
    ]
    recorder["title_review"] = {
        "unreleased_instrument_count": int(mortgage_principal > 0) + int(delinquent),
        "owner_name_matches_assessor": True, "parcel_reference_matches": True,
        "review_required": delinquent or owner_type == "trust",
        "encumbrance_estimate_usd": round(mortgage_balance + delinquent_balance, 2),
        "review_status": "generated_fixture_not_title_opinion",
    }

    district = rng.choice(["R-1", "R-2", "RS-6", "SF-5", "R-MX-2"])
    flood_probability = rng.uniform(.0005, .025)
    zoning = evidence_base("zoning", parcel, seed, index)
    zoning["district"] = {
        "code": district, "description": "Synthetic residential test zoning district",
        "municipality": city, "ordinance_reference": f"SYN-ORD-{city.upper().replace(' ', '-')}-{index%99}",
        "effective_date": "2026-01-01", "permitted_uses": ["single_family", "home_office"],
        "conditional_uses": ["accessory_dwelling", "duplex"] if district != "R-1" else ["accessory_dwelling"],
        "prohibited_uses": ["industrial", "heavy_manufacturing"],
        "current_use_conforms": True, "historical_overlay": rng.random() < .06,
        "rezoning_case": f"SYN-ZC-{seed}-{index}" if rng.random() < .025 else None,
    }
    zoning["development_standards"] = {
        "minimum_lot_sqft": rng.choice([4000, 5000, 6000, 7500]),
        "maximum_height_feet": rng.choice([30, 35, 40]),
        "maximum_lot_coverage_pct": rng.choice([35, 40, 45, 50]),
        "maximum_floor_area_ratio": rng.choice([.4, .5, .6, .75]),
        "front_setback_feet": rng.choice([15, 20, 25]), "rear_setback_feet": rng.choice([10, 15, 20]),
        "side_setback_feet": rng.choice([5, 7, 10]), "required_parking_spaces": 2,
        "adu_maximum_sqft": rng.choice([600, 800, 1000, 1200]),
        "adu_owner_occupancy_required": rng.choice([True, False]),
        "subdivision_review_required": True,
        "estimated_buildable_sqft": round(lot_sqft * rng.uniform(.28, .52)),
    }
    zoning["hazards"] = {
        "flood_zone": "AE" if flood_probability > .02 else rng.choice(["X", "X", "X", "A"]),
        "annual_flood_probability": round(flood_probability, 5),
        "flood_zone_basis": "synthetic_test_category_not_fema_determination",
        "wildfire_score_0_100": rng.randint(1, 88) if state in ["AZ", "CO", "UT"] else rng.randint(1, 32),
        "wind_score_0_100": rng.randint(15, 92), "heat_score_0_100": rng.randint(15, 97),
        "soil_expansion_category": rng.choice(["low", "moderate", "high"]),
        "wetland_overlap_pct": round(rng.uniform(0, 7), 2) if rng.random() < .09 else 0,
        "slope_pct": round(rng.uniform(0, 16), 2),
        "environmental_review_status": "synthetic_fixture_not_site_assessment",
    }
    zoning["permits"] = [
        {"permit_id": f"SYN-PERMIT-{seed}-{index}-{n}",
         "type": rng.choice(["roof_replacement", "hvac_replacement", "electrical_upgrade", "bath_remodel"]),
         "application_date": date_between(rng, max(2019, year_built), 2026),
         "status": rng.choice(["finaled", "finaled", "issued", "expired"]),
         "declared_value_usd": rng.randrange(2000, 40000, 100),
         "contractor": f"Synthetic Licensed Test Contractor {index%211}-{n}",
         "inspection_result": rng.choice(["pass", "pass", "pending", "correction_required"])}
        for n in range(3)
    ]
    zoning["boundary"] = {
        "type": "Polygon", "coordinates": [[
            [longitude-.0002, latitude-.00015], [longitude+.0002, latitude-.00015],
            [longitude+.0002, latitude+.00015], [longitude-.0002, latitude+.00015],
            [longitude-.0002, latitude-.00015],
        ]], "is_survey": False, "crs": "EPSG:4326",
    }

    market = evidence_base("market", parcel, seed, index)
    market["subject"] = {
        "address": address, "state": state, "county_fips": fips,
        "living_area_sqft": area, "condition": condition,
        "estimated_arv_usd": arv, "estimated_as_is_value_usd": current_value,
        "estimate_basis": "synthetic_test_distribution",
    }
    comps = []
    for n in range(8):
        comp_area = round(area * rng.uniform(.81, 1.19) / 10) * 10
        distance_miles = round(rng.uniform(.12, 2.8), 2)
        comp_price = round_money(comp_area * local_ppsf * rng.uniform(.9, 1.18))
        adjustment = round_money((area - comp_area) * local_ppsf * .55)
        if area < comp_area:
            adjustment = -round_money((comp_area - area) * local_ppsf * .55)
        comps.append({
            "comparable_id": f"SYN-COMP-{fips}-{seed}-{index:09d}-{n}",
            "address": f"{number+n+31} Synthetic Comparable {rng.choice(STREET_NAMES)} Way",
            "city": city, "state": state, "sale_date": date_between(rng, 2025, 2026),
            "sale_price_usd": comp_price, "living_area_sqft": comp_area,
            "bedrooms": beds, "bathrooms": baths, "year_built": max(1930, year_built+rng.randint(-12, 12)),
            "condition": rng.choice(["average", "good", "excellent"]),
            "lot_sqft": round(lot_sqft*rng.uniform(.8, 1.25)),
            "distance_miles": distance_miles,
            "latitude": round(latitude+rng.uniform(-.02, .02), 6),
            "longitude": round(longitude+rng.uniform(-.02, .02), 6),
            "price_per_sqft": round(comp_price/comp_area, 2),
            "living_area_adjustment_usd": adjustment,
            "adjusted_price_usd": comp_price+adjustment,
            "days_on_market": rng.randint(5, 150), "seller_concession_usd": rng.randrange(0, 14000, 100),
            "financing": rng.choice(["conventional", "cash", "fha", "va"]),
            "arm_length": True, "source_type": "synthetic_comparable",
            "matching_score": round(rng.uniform(.67, .99), 3), "synthetic": True,
        })
    market["comparables"] = comps
    market["local_market"] = {
        "observation_month": "2026-09", "geography": f"SYNTHETIC:{fips}:{index%73}",
        "median_sale_price_usd": round_money(local_ppsf*1850*rng.uniform(.95, 1.06)),
        "median_price_per_sqft": round(local_ppsf*rng.uniform(.94, 1.06), 2),
        "median_days_on_market": rng.randint(18, 67), "months_of_inventory": round(rng.uniform(1.6, 6.5), 2),
        "active_listing_count": rng.randint(40, 790), "closed_sales_90d": rng.randint(30, 620),
        "sale_to_list_ratio": round(rng.uniform(.945, 1.022), 4),
        "year_over_year_price_change_pct": round(rng.uniform(-5.2, 8.8), 2),
        "median_rent_monthly_usd": round_money(area*rng.uniform(.9, 1.6)),
        "vacancy_rate": round(rng.uniform(.025, .095), 3),
        "rent_growth_pct": round(rng.uniform(-1.4, 5.8), 2),
    }
    renovation_tasks = (
        ("roof", area*.55, 8.25), ("flooring", area*.82, 6.5),
        ("interior_paint", area*2.4, 1.85), ("kitchen", 1, 16000),
        ("bathroom", baths, 6800), ("hvac", 1, 7600),
        ("electrical", 1, 3400), ("landscaping", lot_sqft*.12, 1.7),
    )
    market["renovation_budget"] = [
        {"trade": trade, "quantity": round(quantity, 2),
         "unit_cost_usd": unit_cost, "scope_fraction": round(rng.uniform(.2, 1), 3),
         "scenario_cost_usd": round_money(quantity*unit_cost*rng.uniform(.35, 1)),
         "basis": "synthetic_cost_fixture"}
        for trade, quantity, unit_cost in renovation_tasks
    ]
    resale_costs = round_money(arv*.08)
    holding_costs = round_money(arv*.025)
    target_profit = round_money(arv*.16)
    max_offer = max(0, arv - repair_cost - resale_costs - holding_costs - target_profit)
    market["underwriting_inputs"] = {
        "currency": "USD", "arv_usd": arv, "repair_estimate_usd": repair_cost,
        "resale_costs_usd": resale_costs, "holding_costs_usd": holding_costs,
        "target_profit_usd": target_profit, "max_allowable_offer_usd": max_offer,
        "assignment_spread_example_usd": rng.randrange(12000, 68000, 500),
        "acquisition_expense_example_usd": rng.randrange(1500, 8000, 100),
        "scenario_assumptions": {"holding_months": 6, "disposition_share_pct": 50,
                                 "minimum_underwritten_gross_spread_usd": 20000},
        "is_offer_or_recommendation": False,
    }
    market["sensitivity"] = [
        {"scenario": label, "arv_multiplier": multiplier, "arv_usd": round_money(arv*multiplier),
         "repair_multiplier": repair_multiplier, "repairs_usd": round_money(repair_cost*repair_multiplier),
         "max_allowable_offer_usd": max(0, round_money(arv*multiplier*.735-repair_cost*repair_multiplier))}
        for label, multiplier, repair_multiplier in [("downside", .9, 1.2), ("base", 1, 1), ("upside", 1.07, .92)]
    ]
    # Normalized API columns coexist with detailed source evidence intentionally.
    assessor.update({"owner": owner_name, "assessed_value": current_value,
                     "bedrooms": beds, "bathrooms": baths, "square_feet": area,
                     "lot_size": lot_sqft, "latitude": latitude, "longitude": longitude,
                     "property_type": "single_family"})
    recorder.update({"debt": mortgage_balance, "sale_price": purchase_price, "sale_date": grant_date})
    zoning["zoning"] = district
    market.update({"estimated_value": arv, "purchase_price": max_offer,
                   "repairs": repair_cost, "holding_costs": holding_costs,
                   "closing_costs": round_money(arv*.02), "selling_cost_pct": 6})
    records = (assessor, recorder, zoning, market)
    base_keys = {"schema_version", "synthetic", "record_id", "source_id", "source_record_id", "parcel_id",
                 "county_fips", "state", "address", "category", "observed_at", "source", "quality"}
    for record in records:
        evidence = {key: record.pop(key) for key in list(record) if key not in base_keys}
        evidence["synthetic"] = True
        record["attributes"] = evidence
    return records


class ShardedWriter:
    """Write bounded files while computing hashes without retaining records."""

    def __init__(self, root: Path, category: str):
        self.root, self.category = root, category
        self.handle = None
        self.digest = None
        self.current_bytes = self.current_count = self.total_bytes = self.total_count = 0
        self.sequence = 0
        self.shards: list[dict[str, Any]] = []
        self.current_path = None

    def _open(self) -> None:
        self.sequence += 1
        self.current_path = self.root / f"{self.category}-{self.sequence:04d}.ndjson"
        self.handle = self.current_path.open("wb", buffering=1024*1024)
        self.digest = hashlib.sha256()
        self.current_bytes = self.current_count = 0

    def _close(self) -> None:
        if self.handle is None:
            return
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        self.shards.append({"path": self.current_path.name, "category": self.category,
                            "bytes": self.current_bytes, "records": self.current_count,
                            "sha256": self.digest.hexdigest()})
        self.handle = None

    def write(self, record: dict[str, Any]) -> None:
        blob = encode(record)
        if len(blob) > SHARD_BYTES:
            raise ValueError("One record exceeds the shard byte limit")
        if self.handle is not None and self.current_bytes + len(blob) > SHARD_BYTES:
            self._close()
        if self.handle is None:
            self._open()
        self.handle.write(blob)
        self.digest.update(blob)
        self.current_bytes += len(blob)
        self.current_count += 1
        self.total_bytes += len(blob)
        self.total_count += 1

    def close(self) -> None:
        self._close()


def generate(output: Path, seed: int, target_bytes: int, quick: bool, overwrite: bool) -> dict[str, Any]:
    if target_bytes <= 0:
        raise ValueError("--target-bytes must be positive")
    output.mkdir(parents=True, exist_ok=True)
    existing = list(output.glob("*.ndjson")) + list(output.glob("manifest.json"))
    if existing and not overwrite:
        raise ValueError(f"{output} already contains benchmark records; use --overwrite to regenerate them")
    for path in existing:
        path.unlink()
    writers = {category: ShardedWriter(output, category) for category in CATEGORIES}
    count = 0
    byte_count = 0
    state_counts: dict[str, int] = {county[0]: 0 for county in COUNTIES}
    target = min(target_bytes, 1024*1024) if quick else target_bytes
    try:
        while byte_count < target:
            records = property_records(seed, count)
            for category, record in zip(CATEGORIES, records):
                writers[category].write(record)
            state_counts[COUNTIES[count % len(COUNTIES)][0]] += 1
            count += 1
            byte_count = sum(writer.total_bytes for writer in writers.values())
            if count % 10000 == 0:
                print(f"Generated {count:,} linked parcels, {byte_count:,} NDJSON bytes", flush=True)
    finally:
        for writer in writers.values():
            writer.close()
    shards = [shard for category in CATEGORIES for shard in writers[category].shards]
    manifest = {
        "name": "101XVC BRAIN synthetic property evidence benchmark",
        "schema_version": SCHEMA_VERSION, "synthetic": True,
        "description": "Deterministic structured property evidence for parser, search, ingestion and underwriting load tests. No live records or investment opportunities.",
        "data_classification": "synthetic_test_data", "license": "101XVC proprietary",
        "generated_at": AS_OF_DATE + "T12:00:00Z", "generation_date_basis": "fixed_for_reproducibility",
        "seed": seed, "requested_target_bytes": target_bytes, "effective_target_bytes": target,
        "quick_sample": quick, "total_ndjson_bytes": byte_count, "parcel_count": count,
        "evidence_record_count": count*len(CATEGORIES), "max_shard_bytes": SHARD_BYTES,
        "categories": {
            category: {"records": writer.total_count, "bytes": writer.total_bytes,
                       "shards": len(writer.shards)} for category, writer in writers.items()
        },
        "state_parcel_counts": state_counts,
        "geographic_fixture_counties": [{"state": c[0], "county": c[2], "fips": c[3]} for c in COUNTIES],
        "relationships": {"join_key": "parcel_id", "records_per_parcel": 4,
                          "embedded_comparables_per_parcel": 8, "recorder_instruments_per_parcel": 3},
        "shards": shards,
        "reproduction": {"python": "3.12", "command": f"python3 scripts/benchmark.py --seed {seed} --target-bytes {target_bytes} --output {output.as_posix()}" + (" --quick" if quick else "")},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify(output: Path, deep: bool = False) -> dict[str, Any]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    total_bytes = total_records = 0
    join_hashes = {category: hashlib.sha256() for category in CATEGORIES}
    category_counts = {category: 0 for category in CATEGORIES}
    expected_files = {shard["path"] for shard in manifest["shards"]}
    found_files = {p.name for p in output.glob("*.ndjson")}
    if expected_files != found_files:
        raise ValueError("Shard file set differs from manifest")
    for shard in manifest["shards"]:
        path = output / shard["path"]
        digest = hashlib.sha256()
        size = count = 0
        with path.open("rb") as handle:
            for line in handle:
                digest.update(line)
                size += len(line)
                count += 1
                if deep:
                    record = json.loads(line)
                    if record.get("synthetic") is not True or record.get("schema_version") != SCHEMA_VERSION:
                        raise ValueError(f"Missing synthetic marker or schema version: {path}:{count}")
                    if record["source"]["is_live_public_record"]:
                        raise ValueError(f"Synthetic record claims live provenance: {path}:{count}")
                    if not record.get("parcel_id", "").startswith("BRAIN-SYN-"):
                        raise ValueError(f"Invalid parcel join key: {path}:{count}")
                    if record.get("category") != shard["category"] or record["source_id"] != "synthetic-benchmark-" + shard["category"]:
                        raise ValueError(f"Evidence category/source mismatch: {path}:{count}")
                    join_hashes[shard["category"]].update((record["parcel_id"] + "\n").encode("ascii"))
        actual = {"bytes": size, "records": count, "sha256": digest.hexdigest()}
        for key, value in actual.items():
            if value != shard[key]:
                raise ValueError(f"Integrity failure for {path.name}: {key}")
        if size > SHARD_BYTES:
            raise ValueError(f"Shard exceeds {SHARD_BYTES} bytes: {path.name}")
        total_bytes += size
        total_records += count
        category_counts[shard["category"]] += count
    if total_bytes != manifest["total_ndjson_bytes"] or total_records != manifest["evidence_record_count"]:
        raise ValueError("Manifest aggregate totals differ from verified data")
    if total_bytes < manifest["effective_target_bytes"]:
        raise ValueError("Corpus does not meet requested effective target")
    if any(count != manifest["parcel_count"] for count in category_counts.values()):
        raise ValueError("Each category must contain exactly one record per parcel")
    if deep and len({digest.hexdigest() for digest in join_hashes.values()}) != 1:
        raise ValueError("Cross-category parcel join keys differ")
    return {"verified": True, "deep": deep, "shards": len(manifest["shards"]),
            "bytes": total_bytes, "records": total_records, "parcels": manifest["parcel_count"]}


def importable_records(output: Path, max_records: int, all_categories: bool = False) -> Iterator[dict[str, Any]]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    counts = {category: 0 for category in CATEGORIES}
    for shard in manifest["shards"]:
        category = shard["category"]
        if category != "assessor" and not all_categories:
            continue
        if counts[category] >= max_records:
            continue
        with (output / shard["path"]).open(encoding="utf-8") as handle:
            for line in handle:
                if counts[category] >= max_records:
                    break
                yield json.loads(line)
                counts[category] += 1


def import_records(output: Path, import_url: str, max_records: int, batch_size: int,
                   api_token: str | None, all_categories: bool = False) -> dict[str, Any]:
    if max_records <= 0 or batch_size <= 0:
        raise ValueError("--max-records and --batch-size must be positive")
    if max_records > 10000:
        raise ValueError("Import is capped at 10,000 parcels per invocation; full corpus is for external load-test infrastructure")
    imported = 0
    batches = 0
    batch: list[dict[str, Any]] = []
    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["X-API-Key"] = api_token
        headers["Authorization"] = "Bearer " + api_token

    parsed = urllib.parse.urlsplit(import_url)
    source_path = parsed.path.rsplit("/", 1)[0] + "/sources"
    source_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, source_path, "", ""))
    for category in CATEGORIES if all_categories else ("assessor",):
        source = {"id": f"synthetic-benchmark-{category}", "name": f"Synthetic benchmark {category}",
                  "category": category, "adapter": "manual", "status": "configured", "state": "", "county_fips": ""}
        req = urllib.request.Request(source_url, data=encode(source).rstrip(b"\n"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as response:
            if not 200 <= response.status < 300:
                raise ValueError(f"Source registration failed: HTTP {response.status}")
            response.read()

    def submit(records: list[dict[str, Any]]) -> None:
        nonlocal imported, batches
        payload = {"source": "synthetic_benchmark", "synthetic": True, "records": records}
        req = urllib.request.Request(import_url, data=encode(payload).rstrip(b"\n"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read() or b"{}")
            if not 200 <= response.status < 300:
                raise ValueError(f"Import failed: HTTP {response.status}")
        if result.get("rejected", 0):
            raise ValueError(f"API rejected benchmark records: {json.dumps(result)}")
        if "accepted" in result and result["accepted"] != len(records):
            raise ValueError(f"API acceptance count differs from submitted batch: {json.dumps(result)}")
        imported += len(records)
        batches += 1
        print(json.dumps({"batch": batches, "submitted_records": imported, "api_result": result}), flush=True)

    for record in importable_records(output, max_records, all_categories):
        batch.append(record)
        if len(batch) >= batch_size:
            submit(batch)
            batch = []
    if batch:
        submit(batch)
    return {"submitted_records": imported, "requested_max_parcels": max_records,
            "categories": list(CATEGORIES) if all_categories else ["assessor"],
            "batches": batches, "synthetic": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path("data/benchmark"))
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--target-bytes", type=int, default=DEFAULT_BYTES)
    parser.add_argument("--quick", action="store_true", help="Generate a sample of at most approximately 1 MiB")
    parser.add_argument("--overwrite", action="store_true", help="Replace only manifest.json and *.ndjson in output")
    parser.add_argument("--verify", action="store_true", help="Verify existing corpus hashes, byte counts and record counts")
    parser.add_argument("--deep", action="store_true", help="Additionally parse and validate every record during --verify")
    parser.add_argument("--import-url", help="Register sources and POST bounded evidence batches to this complete API URL")
    parser.add_argument("--max-records", type=int, default=100, help="Import at most this many parcels (default 100, cap 10000)")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--all-categories", action="store_true", help="Import all four evidence categories for each bounded parcel sample")
    parser.add_argument("--api-token", default=os.environ.get("BRAIN_API_TOKEN"), help="API key; preferably supply BRAIN_API_TOKEN")
    args = parser.parse_args()
    try:
        if args.verify:
            result = verify(args.output, args.deep)
        elif args.import_url:
            result = import_records(args.output, args.import_url, args.max_records, args.batch_size, args.api_token, args.all_categories)
        else:
            manifest = generate(args.output, args.seed, args.target_bytes, args.quick, args.overwrite)
            result = {"generated": True, "synthetic": True, "output": str(args.output),
                      "parcels": manifest["parcel_count"], "records": manifest["evidence_record_count"],
                      "bytes": manifest["total_ndjson_bytes"], "shards": len(manifest["shards"])}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
