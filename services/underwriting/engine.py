"""Transparent local underwriting, operating rules, and transaction economics.

Recorded estimates, executable demand, observed outcomes, and model forecasts stay
separate. An absent or synthetic model never becomes a live probability.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import statistics
from collections import Counter
from .registry import sanitize_features


UTC = dt.timezone.utc
TERMINAL = {"closed", "funded", "settled", "cancelled", "canceled", "expired", "lost", "rejected"}
CONTRACT_STAGES = {"under_contract", "contracted", "submitted", "approved", "buyer_committed", "title", "closing"}
AUTHORITY = {"owner": ["recorder", "assessor", "market", "zoning"], "debt": ["recorder", "assessor", "market", "zoning"], "estimated_value": ["market", "assessor", "recorder", "zoning"], "zoning": ["zoning", "assessor", "recorder", "market"], "assessed_value": ["assessor", "recorder", "market", "zoning"]}


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("$", "")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def first_number(row, *keys):
    for key in keys:
        value = number(row.get(key))
        if value is not None:
            return value
    return None


def timestamp(value):
    if not value:
        return None
    try:
        result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def flat(row):
    if not isinstance(row, dict):
        return {}
    return {**(row.get("data") if isinstance(row.get("data"), dict) else {}), **row}


def items(value):
    if isinstance(value, list):
        return value
    return value.get("items", value.get("episodes", [])) if isinstance(value, dict) else []


def money(value):
    return None if value is None else round(value, 2)


def probability(value):
    value = number(value)
    return value if value is not None and 0 <= value <= 1 else None


def stage_of(episode):
    return str(episode.get("stage", episode.get("status", "lead"))).lower().replace(" ", "_")


def seller_note_facts(text):
    """Extract candidates with exact spans; these are never verified facts."""
    if not isinstance(text, str):
        return []
    patterns = {
        "asking_price": r"(?i)\b(?:asking(?:\s+price)?|asks?|wants?)\s*(?:is|for|of|:)?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?\s*(?:million|thousand|mm|k|m)?)",
        "occupancy": r"(?i)\b(?:vacant|tenant[- ]occupied|owner[- ]occupied|rented|tenants? in place)\b",
        "condition": r"(?i)\b(?:leak(?:ing|y)? roof|roof leak|foundation(?: damage| issue)?|water damage|mold|fire damage|needs? (?:a )?(?:new roof|repairs|renovation)|uninhabitable)\b",
        "requested_date": r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|(?i:\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,?\s+\d{4})?\b)",
        "objection": r"(?i)\b(?:not willing|won't|will not|cannot|concern(?:ed)?|too low|requires?|must have)\b[^.!?\n]{0,120}",
    }
    result = []
    for kind, pattern in patterns.items():
        for match in re.finditer(pattern, text):
            value = match.group(0)
            if kind == "asking_price":
                raw = match.group(1).strip().lower().replace(",", "")
                parsed = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(million|thousand|mm|k|m)?", raw)
                if parsed:
                    value = float(parsed.group(1)) * {None: 1, "k": 1000, "thousand": 1000, "m": 1000000, "mm": 1000000, "million": 1000000}[parsed.group(2)]
            result.append({"kind": kind, "value": value, "text": match.group(0), "start": match.start(), "end": match.end(), "review_required": True})
    return result


class UnderwritingEngine:
    def __init__(self, ledger, registry):
        self.ledger, self.registry = ledger, registry

    def _predict(self, kind, features):
        try:
            result = self.registry.predict(kind, features) if self.registry else {}
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            result = {"status": "insufficient_support", "limitations": [str(exc)]}
        if not isinstance(result, dict):
            result = {}
        result = {"status": "untrained", "model_id": None, "synthetic": False, "prediction": None, "limitations": [], **result}
        result["usable"] = result["status"] == "ready" and not result.get("synthetic") and isinstance(result.get("prediction"), dict)
        if result.get("synthetic"):
            result["status"] = "synthetic_unvalidated"
        return result

    def _episodes(self, property_id=None):
        return [flat(x) for x in items(self.ledger.episodes(property_id=property_id))]

    def _detail(self, property_id, episode_id, as_of=None):
        if episode_id:
            detail = self.ledger.get_episode(episode_id, as_of=as_of) if as_of else self.ledger.get_episode(episode_id)
            if not isinstance(detail, dict):
                raise ValueError("Episode does not exist")
            created = timestamp(detail.get("episode", {}).get("created_at"))
            if as_of and created and created > timestamp(as_of):
                raise ValueError("Episode did not exist at the requested as_of")
            if detail.get("episode", {}).get("property_id") not in (None, property_id):
                raise ValueError("Episode belongs to a different property")
            return detail
        episodes = self._episodes(property_id)
        if as_of:
            cutoff = timestamp(as_of)
            episodes = [x for x in episodes if not timestamp(x.get("created_at")) or timestamp(x.get("created_at")) <= cutoff]
        if episodes:
            episodes.sort(key=lambda x: (str(x.get("updated_at", x.get("created_at", ""))), str(x.get("id", ""))))
            return self.ledger.get_episode(episodes[-1]["id"], as_of=as_of) if as_of else self.ledger.get_episode(episodes[-1]["id"])
        return {"episode": {"id": None, "property_id": property_id, "stage": "lead"}, "events": [], "offers": [], "bids": [], "milestones": [], "expenses": [], "settlements": [], "decisions": []}

    def _rules(self, prop, episode, as_of):
        applicable, excluded, draft = [], [], []
        state = str(prop.get("state", episode.get("state", ""))).upper()
        partner = str(episode.get("partner_id", episode.get("partner", "")))
        county = str(prop.get("county_fips", ""))
        for original in items(self.ledger.rules()):
            rule = flat(original)
            if rule.get("status") != "reviewed" or not rule.get("approved_by"):
                draft.append({**rule, "binding": False, "reason": "not reviewed and approved"})
                continue
            start = timestamp(rule.get("effective_from", rule.get("effective_at")))
            end = timestamp(rule.get("effective_to"))
            recorded = timestamp(rule.get("recorded_at"))
            jurisdiction = str(rule.get("jurisdiction", "")).upper()
            rule_state = str(rule.get("state", "")).upper()
            rule_partner = str(rule.get("partner_id", rule.get("partner", "")))
            match = (not rule_state or rule_state == state) and (not rule_partner or rule_partner == partner)
            if jurisdiction and jurisdiction not in {"US", "USA", "ALL", "FEDERAL", state, county}:
                match = False
            if not start or start > as_of or (end and end < as_of) or (recorded and recorded > as_of) or not match:
                excluded.append({"id": rule.get("id"), "reason": "outside effective date or jurisdiction/partner scope"})
                continue
            applicable.append({**rule, "binding": True})
        # Later reviewed versions take precedence, with stable identity ties.
        applicable.sort(key=lambda x: (str(x.get("effective_from", "")), str(x.get("id", ""))))
        retired = {}
        def scope(rule):
            return (rule.get("jurisdiction"), rule.get("state"), rule.get("partner_id", rule.get("partner")))
        grouped = {}
        for rule in applicable:
            if rule.get("rule_group"):
                key = (scope(rule), rule["rule_group"])
                if key in grouped:
                    retired[grouped[key]["id"]] = rule["id"]
                grouped[key] = rule
            supersedes = rule.get("supersedes_rule_id", rule.get("supersedes"))
            references = supersedes if isinstance(supersedes, list) else [supersedes] if supersedes else []
            for previous in applicable:
                if previous.get("id") in references and scope(previous) == scope(rule) and previous.get("effective_from", "") <= rule.get("effective_from", ""):
                    retired[previous["id"]] = rule["id"]
        excluded.extend({"id": old, "reason": "superseded by reviewed rule version", "superseded_by": new} for old, new in retired.items())
        applicable = [rule for rule in applicable if rule.get("id") not in retired]
        return {"applicable": applicable, "draft": draft, "excluded": excluded}

    @staticmethod
    def _rule_values(rules):
        values = {}
        for rule in rules["applicable"]:
            payload = rule.get("rules", rule.get("constraints", {}))
            if isinstance(payload, dict):
                for key, value in payload.items():
                    if key in {"min_profit", "min_gross_profit", "minimum_spread", "min_contribution"}:
                        target = "min_contribution" if key == "min_contribution" else "min_profit"
                        parsed = number(value)
                        if parsed is not None:
                            values[target] = max(parsed, values.get(target, parsed))
                    elif key in {"capacity", "max_active_contracts", "max_cash_required", "cash_available", "cash_limit"}:
                        target = "capacity" if key in {"capacity", "max_active_contracts"} else "cash_available" if key in {"cash_available", "cash_limit"} else key
                        parsed = number(value)
                        if parsed is not None:
                            values[target] = min(parsed, values.get(target, parsed))
                    elif key in {"required_documents", "required_milestones"}:
                        incoming = [value] if isinstance(value, str) else value
                        if isinstance(incoming, list):
                            values["required_documents"] = list(dict.fromkeys(values.get("required_documents", []) + incoming))
                    elif key == "allowed_structures" and isinstance(value, list):
                        values[key] = [x for x in values[key] if x in value] if key in values else value[:]
                        values["structure_constraints_present"] = True
                    else:
                        values[key] = value
            kind = rule.get("kind")
            if kind and "value" in rule:
                values[kind] = rule["value"]
        return values

    @staticmethod
    def _available(rows, as_of):
        result = []
        for raw in rows or []:
            row = flat(raw)
            available = timestamp(row.get("available_at", row.get("recorded_at", row.get("observed_at"))))
            observed = timestamp(row.get("observed_at"))
            if (available is None or available <= as_of) and (observed is None or observed <= as_of):
                result.append(row)
        return result

    @staticmethod
    def _historical_property(property_detail, prop, as_of):
        """Rebuild from availability-stamped immutable observations, or abstain."""
        historical = {key: prop[key] for key in ("id", "property_id", "parcel_id", "state", "county_fips", "synthetic") if key in prop}
        candidates = {}
        known = []
        for raw in property_detail.get("evidence_history", property_detail.get("evidence", [])):
            row = flat(raw)
            available = timestamp(row.get("available_at", row.get("recorded_at")))
            observed = timestamp(row.get("observed_at"))
            if available is None or available > as_of or (observed and observed > as_of):
                continue
            known.append(row)
            attributes = row.get("attributes", {})
            attributes = attributes if isinstance(attributes, dict) else {}
            values = {**attributes}
            if row.get("address"):
                values["address"] = row["address"]
            for key, value in values.items():
                if value is not None and value != "":
                    candidates.setdefault(key, []).append((row, value, observed or available, available))
        provenance, conflicts = {}, []
        for key, values in candidates.items():
            priority = AUTHORITY.get(key, ["assessor", "recorder", "market", "zoning"])
            values.sort(key=lambda x: (priority.index(x[0].get("category")) if x[0].get("category") in priority else len(priority), -x[2].timestamp(), -x[3].timestamp(), str(x[0].get("source_id", "")), str(x[0].get("source_record_id", ""))))
            row, value, _, _ = values[0]
            historical[key] = value
            provenance[key] = {key: row.get(key) for key in ("source_id", "source_record_id", "category", "observed_at", "available_at", "recorded_at", "evidence_id")}
            provenance[key]["selection_rule"] = "authority then latest observed and available version before cutoff"
            if len({repr(x[1]) for x in values}) > 1:
                conflicts.append({"field": key, "selected": value, "values": [{"value": x[1], "source_id": x[0].get("source_id"), "available_at": x[0].get("available_at", x[0].get("recorded_at"))} for x in values]})
        historical["field_provenance"], historical["conflicts"] = provenance, conflicts
        return historical, known

    @staticmethod
    def _liquidity(bids, as_of):
        executable, interest, historical = [], [], []
        for bid in bids:
            price = first_number(bid, "amount", "price", "bid_price", "exit_price")
            if price is None or price <= 0:
                continue
            row = {**bid, "amount": money(price)}
            status = str(bid.get("status", "")).lower()
            firm = bid.get("executable") is True or status in {"accepted", "committed", "funded"}
            conditions = bid.get("conditions", [])
            clear = not conditions or all(isinstance(x, dict) and x.get("status") in {"cleared", "satisfied", "waived"} for x in conditions)
            expiry = timestamp(bid.get("expires_at"))
            current = firm and clear and status not in {"withdrawn", "rejected", "cancelled", "expired", "interest"} and (expiry is None or expiry >= as_of)
            (executable if current else interest).append(row)
            if firm:
                historical.append(row)
        historical.sort(key=lambda x: (str(x.get("observed_at", x.get("recorded_at", ""))), str(x.get("id", ""))))
        deterioration = {"status": "insufficient_bid_history", "earlier_count": 0, "latest_count": 0, "median_change_pct": None, "causal": False}
        if len(historical) >= 4:
            cut = len(historical) // 2
            before, after = historical[:cut], historical[cut:]
            early, late = statistics.median(x["amount"] for x in before), statistics.median(x["amount"] for x in after)
            change = (late / early - 1) * 100 if early else None
            deterioration = {"status": "deteriorating" if change is not None and change < -5 else "no_material_decline_observed", "earlier_count": len(before), "latest_count": len(after), "earlier_median": early, "latest_median": late, "median_change_pct": round(change, 2) if change is not None else None, "causal": False, "limitation": "Descriptive property-specific bids; changed conditions or buyers can explain differences."}
        return {"executable_bids": executable, "stated_interest": interest, "demand_deterioration": deterioration, "buyer_count": len({x.get("buyer_id") for x in executable if x.get("buyer_id")}), "visibility": "Only recorded property-specific buyer and partner evidence is visible."}

    @staticmethod
    def _expenses(rows):
        attributed, paid, missing = 0.0, 0.0, []
        for row in rows:
            if str(row.get("status", "")).lower() in {"void", "voided", "superseded"}:
                continue
            value = first_number(row, "amount", "cost")
            if value is None:
                missing.append(row.get("id"))
                continue
            attributed += value
            if row.get("paid") is True or row.get("paid_at") or row.get("status") in {"paid", "collected"}:
                paid += value
        if not rows:
            return {"attributable": None, "paid": None, "unpaid": None, "missing_amount_ids": [], "status": "no_expenses_recorded"}
        return {"attributable": money(attributed), "paid": money(paid), "unpaid": money(attributed - paid), "missing_amount_ids": missing, "status": "incomplete" if missing else "recorded"}

    @staticmethod
    def _timeline(model):
        if not model["usable"]:
            return None
        raw = model["prediction"].get("probabilities", {})
        result, previous = {}, {"closed": 0, "cancelled": 0, "expired": 0}
        for days in (14, 30, 60, 90):
            point = raw.get(str(days), raw.get(days))
            if not isinstance(point, dict):
                return None
            parsed = {key: probability(point.get(key)) for key in ("closed", "cancelled", "expired", "still_open")}
            if any(value is None for value in parsed.values()) or abs(sum(parsed.values()) - 1) > 0.005:
                return None
            if any(parsed[key] + 1e-8 < previous[key] for key in previous):
                return None
            previous = {key: parsed[key] for key in previous}
            result[str(days)] = parsed
        return result

    def report(self, property_detail, episode_id=None, scenario=None):
        if not isinstance(property_detail, dict) or (scenario is not None and not isinstance(scenario, dict)):
            raise ValueError("Property detail and scenario must be objects")
        scenario = scenario or {}
        prop = flat(property_detail.get("property", property_detail))
        property_id = prop.get("id", prop.get("property_id"))
        if not property_id:
            raise ValueError("Property identity is required")
        as_of = timestamp(scenario.get("as_of")) or dt.datetime.now(UTC)
        if "as_of" in scenario and timestamp(scenario["as_of"]) is None:
            raise ValueError("as_of must be an ISO date or timestamp")
        if "as_of" in scenario:
            prop, historic_evidence = self._historical_property(property_detail, prop, as_of)
            property_detail = {**property_detail, "property": prop, "evidence": historic_evidence, "field_provenance": prop["field_provenance"], "conflicts": prop["conflicts"], "comps": []}
        detail = self._detail(property_id, episode_id, as_of.isoformat() if "as_of" in scenario else None)
        episode = flat(detail.get("episode", {}))
        meta = episode.get("meta") if isinstance(episode.get("meta"), dict) else {}
        episode = {**meta, **episode}
        stage = stage_of(episode)
        known_settlement = flat(detail.get("current_settlement"))
        funded_at = timestamp(known_settlement.get("closed_at", known_settlement.get("funded_at")))
        if funded_at and funded_at <= as_of and stage not in {"closed", "settled"}:
            stage = "funded"
        evidence = self._available(property_detail.get("evidence", []), as_of)
        events = {key: self._available(detail.get(key, []), as_of) for key in ("offers", "bids", "milestones", "expenses", "events")}
        rules = self._rules(prop, episode, as_of)
        rule_values = self._rule_values(rules)
        assumptions = []
        provenance = property_detail.get("field_provenance", prop.get("field_provenance", {}))
        for field, source in provenance.items() if isinstance(provenance, dict) else []:
            known_at = timestamp(source.get("available_at", source.get("observed_at"))) if isinstance(source, dict) else None
            observed_at = timestamp(source.get("observed_at")) if isinstance(source, dict) else None
            if (known_at and known_at > as_of) or (observed_at and observed_at > as_of):
                prop.pop(field, None)
                assumptions.append({"name": "future_field_excluded", "value": field, "source": "field provenance availability cutoff"})
        if "as_of" in scenario:
            assumptions.append({"name": "historical_view_limit", "value": scenario["as_of"], "source": "user scenario", "note": "Property fields are reconstructed only from availability-stamped evidence. Current episode state and current active model are not a reconstructed historical decision snapshot; use immutable ledger decisions for backtests."})
        min_spread = first_number(rule_values, "min_profit", "min_gross_profit", "minimum_spread")
        if min_spread is None:
            min_spread = 20000.0
            assumptions.append({"name": "minimum_gross_spread", "value": min_spread, "source": "planning default", "note": "An underwriting assumption, not an imported or signed contract rule."})
        split = first_number(rule_values, "partner_split_pct", "partner_share_pct", "partner_share")
        if split is None:
            split = 50.0
            assumptions.append({"name": "partner_share_pct", "value": split, "source": "planning default", "note": "Replace with reviewed partner economics before execution."})
        percentage_key = "partner_split_pct" in rule_values or "partner_share_pct" in rule_values or not any(key in rule_values for key in ("partner_split_pct", "partner_share_pct", "partner_share"))
        share = split / 100 if percentage_key or split > 1 else split
        if not 0 <= share <= 1 or min_spread < 0:
            raise ValueError("Reviewed economics contain an invalid share or minimum spread")
        features = {**prop, **episode, "stage": stage, "state": prop.get("state", episode.get("state")), "county_fips": prop.get("county_fips"), "days_in_stage": max(0, (as_of - (timestamp(episode.get("stage_at", episode.get("created_at"))) or as_of)).days), "as_of": as_of.isoformat()}
        features.pop("id", None)
        features = sanitize_features(features, as_of.isoformat())
        models = {kind: self._predict(kind, features) for kind in ("valuation", "repairs", "closing", "cash")}
        value_prediction = models["valuation"]["prediction"] if models["valuation"]["usable"] else {}
        as_is = first_number(value_prediction, "as_is_value")
        arv = first_number(value_prediction, "arv")
        valuation_status = models["valuation"]["status"]
        if as_is is None:
            as_is = first_number(prop, "as_is_value", "estimated_value")
            valuation_status = "recorded_estimate" if as_is is not None else "insufficient_evidence"
        if arv is None:
            arv = first_number(prop, "arv", "after_repair_value")
        valuation = {"as_is_value": money(as_is), "arv": money(arv), "range": value_prediction.get("interval"), "status": valuation_status, "arv_status": "model_estimate" if models["valuation"]["usable"] and value_prediction.get("arv") is not None else "recorded_estimate" if arv is not None else "insufficient_verified_arv", "assessed_value": money(first_number(prop, "assessed_value")), "comps": property_detail.get("comps", []), "missing": ([] if as_is is not None else ["verified comparable sale evidence or supported valuation model"]) + ([] if arv is not None else ["verified renovated-sale comparables or supported ARV target"]), "model_id": models["valuation"]["model_id"], "limitations": models["valuation"]["limitations"]}
        repair_prediction = models["repairs"]["prediction"] if models["repairs"]["usable"] else {}
        repairs = first_number(repair_prediction, "estimated_cost")
        repair_status = models["repairs"]["status"]
        if repairs is None:
            repairs = first_number(prop, "repairs", "estimated_repairs")
            repair_status = "recorded_estimate" if repairs is not None else "insufficient_inspection_evidence"
        interval = repair_prediction.get("interval")
        repair_scenarios = scenario.get("repair_scenarios", {})
        if not isinstance(repair_scenarios, dict):
            raise ValueError("repair_scenarios must be an object")
        scenarios = {"low": money(first_number(repair_scenarios, "low") if "low" in repair_scenarios else first_number(interval or {}, "lower")), "base": money(repairs), "high": money(first_number(repair_scenarios, "high") if "high" in repair_scenarios else first_number(interval or {}, "upper"))}
        if repair_scenarios:
            assumptions.append({"name": "repair_scenarios", "value": repair_scenarios, "source": "user scenario"})
        condition = {"estimated_repairs": money(repairs), "range": interval, "scenarios": scenarios, "status": repair_status, "missing": [] if repairs is not None else ["itemized inspection and contractor costs"], "inspection_priorities": ["roof, structure, water intrusion, utilities, and access; verify from inspection"], "model_id": models["repairs"]["model_id"]}
        liquidity = self._liquidity(events["bids"], as_of)
        bid_prices = [x["amount"] for x in liquidity["executable_bids"]]
        exit_factor = number(scenario.get("exit_price_factor", 1))
        if exit_factor is None or not 0 <= exit_factor <= 2:
            raise ValueError("exit_price_factor must be between 0 and 2")
        if exit_factor != 1:
            assumptions.append({"name": "exit_price_factor", "value": exit_factor, "source": "user downside/upside scenario", "note": "Scenario-adjusted prices are not executable bids."})
        exit_low = min(bid_prices) * exit_factor if bid_prices else None
        exit_high = max(bid_prices) * exit_factor if bid_prices else None
        exit_target = exit_high
        exit_price = {"low": money(exit_low), "high": money(exit_high), "target": money(exit_target), "status": "scenario_price" if bid_prices and exit_factor != 1 else "executable_bid_evidence" if bid_prices else "no_executable_demand", **{key: liquidity[key] for key in ("executable_bids", "stated_interest")}}
        expenses = self._expenses(events["expenses"])
        additional = number(scenario.get("additional_expenses", 0))
        if additional is None or additional < 0:
            raise ValueError("additional_expenses must be nonnegative")
        if additional:
            assumptions.append({"name": "additional_expenses", "value": additional, "source": "user scenario"})
        expense_known = expenses["attributable"] is not None and not expenses["missing_amount_ids"]
        if scenario.get("expenses_complete") is True and expenses["attributable"] is None:
            expense_known = True
            expenses = {**expenses, "attributable": 0.0, "paid": 0.0, "unpaid": 0.0, "status": "user_scenario_zero_cost"}
            assumptions.append({"name": "expenses_complete", "value": True, "source": "user scenario", "note": "No expense entries were recorded; zero cost is an explicit scenario assumption."})
        attributable = (expenses["attributable"] or 0) + additional
        cash_required = first_number(episode, "cash_required", "company_cash_required")
        cash_available = first_number(scenario, "cash_available")
        rule_cash = first_number(rule_values, "cash_available", "cash_limit")
        if rule_cash is not None:
            cash_available = rule_cash if cash_available is None else min(cash_available, rule_cash)
        max_cash = first_number(rule_values, "max_cash_required")
        capacity = first_number(scenario, "capacity", "max_active_contracts")
        rule_capacity = first_number(rule_values, "capacity", "max_active_contracts")
        if rule_capacity is not None:
            capacity = rule_capacity if capacity is None else min(capacity, rule_capacity)
        active = [x for x in self._episodes() if stage_of(x) in CONTRACT_STAGES]
        active_units = sum(first_number(x, "capacity_required", "capacity") or 1 for x in active)
        current_active = stage in CONTRACT_STAGES
        capacity_blocked = capacity is not None and active_units + (0 if current_active else 1) > capacity
        cash_blocked = cash_required is not None and ((cash_available is not None and cash_required > cash_available) or (max_cash is not None and cash_required > max_cash))
        required = rule_values.get("required_documents", rule_values.get("required_milestones", []))
        if isinstance(required, str):
            required = [required]
        cleared = {str(x.get("name", x.get("milestone", x.get("document", "")))).lower() for x in events["milestones"] if x.get("verified") is True or x.get("status") in {"cleared", "complete", "completed", "satisfied", "waived"}}
        missing_required = [str(name) for name in required if str(name).lower() not in cleared]
        structure = episode.get("exit_strategy", episode.get("structure", "assignment"))
        allowed = rule_values.get("allowed_structures", [])
        structure_blocked = bool(rule_values.get("structure_constraints_present") and structure not in allowed)
        spread_blocked = exit_low is not None and exit_low < min_spread
        constraints = {"minimum_gross_spread": min_spread, "minimum_spread_status": "infeasible_at_recorded_exit" if spread_blocked else "pending_exit" if exit_low is None else "feasible_within_offer_ceiling", "partner_share_pct": round(share * 100, 4), "cash_required": money(cash_required), "cash_available": money(cash_available), "max_cash_required": money(max_cash), "cash_status": "blocked" if cash_blocked else "unknown_requirement" if cash_required is None else "within_configured_limit" if cash_available is not None or max_cash is not None else "limit_not_configured", "capacity": capacity, "active_contract_units": active_units, "capacity_status": "blocked" if capacity_blocked else "within_limit" if capacity is not None else "not_configured", "missing_required_documents": missing_required, "structure_blocked": structure_blocked, "expense_status": "recorded" if expense_known else "unknown_or_incomplete", "rules": rules}
        maximum = max(0, exit_low - min_spread) if exit_low is not None else None
        min_contribution = first_number(rule_values, "min_contribution")
        if maximum is not None and min_contribution is not None and expense_known:
            maximum = min(maximum, exit_low - (min_contribution + attributable) / (1 - share)) if share < 1 else 0
        if maximum is not None and structure in {"flip", "purchase", "wholetail"} and cash_available is not None:
            maximum = min(maximum, max(0, cash_available - attributable - (repairs or 0)))
        notes = []
        for source in [{"id": "property", "text": prop.get("seller_notes", prop.get("notes", ""))}, {"id": "episode", "text": episode.get("seller_notes", episode.get("notes", ""))}] + events["events"]:
            text = source.get("text", source.get("notes", source.get("note", source.get("transcript", ""))))
            facts = seller_note_facts(text)
            if facts:
                notes.append({"source_id": source.get("id"), "original_text": text, "facts": facts, "method": "local_span_rules", "review_required": True})
        asking = first_number(episode, "asking_price", "seller_asking_price")
        if asking is None:
            asking = first_number(prop, "asking_price")
        if asking is None:
            asking = next((x["value"] for note in notes for x in note["facts"] if x["kind"] == "asking_price" and isinstance(x["value"], (int, float))), None)
            if asking is not None:
                assumptions.append({"name": "seller_asking_price", "value": asking, "source": "unverified local NLP extraction from seller notes", "review_required": True, "note": "Confirm the asking price before treating the derived offer range as executable."})
        opening, target = (maximum * 0.90, maximum * 0.95) if maximum is not None else (None, None)
        if target is not None and asking is not None:
            target, opening = min(target, asking), min(opening, asking)
        if maximum is not None:
            assumptions.append({"name": "deterministic_negotiation_range", "value": {"opening_pct_of_ceiling": 90, "target_pct_of_ceiling": 95}, "source": "planning heuristic", "note": "This is not a learned optimum or a counterfactual acceptance claim."})
        timeline = self._timeline(models["closing"])
        global_timeline = None
        if timeline and models["closing"]["prediction"].get("stage_conditioned") is False:
            global_timeline, timeline = timeline, None
        p_close = timeline["90"]["closed"] if timeline else None
        candidates = []
        acceptance_models = {}
        loss = number(scenario.get("loss_exposure", episode.get("loss_exposure")))
        if loss is not None and loss < 0:
            raise ValueError("loss_exposure must be nonnegative")
        if "loss_exposure" in scenario:
            assumptions.append({"name": "loss_exposure", "value": loss, "source": "user scenario"})
        price_candidates = sorted({round(x, 2) for x in [opening, target, maximum, asking, *[first_number(x, "amount", "price", "offer_price") for x in events["offers"]]] if x is not None and x >= 0 and maximum is not None and x <= maximum})
        acceptance_model = None
        blocked = cash_blocked or capacity_blocked or structure_blocked or bool(missing_required) or spread_blocked or (min_contribution is not None and not expense_known)
        for price in price_candidates:
            features_at_price = {**features, "offered_price": price, "offer_price": price, "offer_ratio": price / exit_target if exit_target else None, "asking_price": asking}
            model = self._predict("acceptance", features_at_price)
            acceptance_models[price] = model
            acceptance_model = model
            p_accept = probability(model["prediction"].get("probability")) if model["usable"] else None
            retained = (exit_target - price) * (1 - share) if exit_target is not None else None
            objective = p_accept * p_close * retained - attributable - p_accept * (1 - p_close) * loss if p_accept is not None and p_close is not None and retained is not None and loss is not None and cash_required is not None and expense_known and not blocked else None
            candidates.append({"price": price, "seller_acceptance": p_accept, "closing_probability": p_close, "retained_fee_if_closed": money(retained), "probability_weighted_contribution": money(objective), "status": "model_estimate" if objective is not None else "insufficient_evidence_or_constraints", "acceptance_model_id": model["model_id"], "causal": False})
        scored = [x for x in candidates if x["probability_weighted_contribution"] is not None]
        if scored:
            selected = max(scored, key=lambda x: (x["probability_weighted_contribution"], -x["price"]))
            target = selected["price"]
        selected_acceptance = next((x["seller_acceptance"] for x in candidates if x["price"] == money(target)), None)
        offer = {"opening": money(opening), "target": money(target), "counter_range": {"low": money(target), "high": money(maximum)}, "maximum": money(maximum), "objective_status": "probability_weighted_observational_estimate" if scored else "deterministic_threshold_only" if maximum is not None else "pending_executable_bid", "recommendation_status": "blocked_by_reviewed_rule_or_resource_constraint" if blocked else "provisional" if maximum is not None else "pending_evidence", "objective": "P(acceptance) × P(funded closing | stage) × retained receipts − attributable expenses − P(acceptance) × P(no funded closing) × loss exposure", "candidates": candidates, "constraints": constraints, "limitations": ["Historical acceptance is observational; it does not establish acceptance of an unoffered price.", "The 90-day funded-closing probability bounds this forecast horizon; later outcomes remain outside it."]}
        contract_price = first_number(episode, "contract_price", "target_price", "purchase_price")
        if contract_price is None:
            contract_price = first_number(prop, "purchase_price")
        economics_price = contract_price if contract_price is not None else target
        spread = exit_target - economics_price if exit_target is not None and economics_price is not None else None
        retained = spread * (1 - share) if spread is not None else None
        settlement = detail.get("current_settlement")
        if not isinstance(settlement, dict):
            valid = [x for x in self._available(detail.get("settlements", []), as_of) if x.get("status") not in {"void", "voided", "superseded"}]
            settlement = max(valid, key=lambda x: (str(x.get("recorded_at", x.get("closed_at", ""))), str(x.get("id", "")))) if valid else {}
        settlement = flat(settlement)
        settled_spread = first_number(settlement, "gross_spread", "transaction_spread")
        settled_retained = first_number(settlement, "retained_fee", "company_receipts", "company_fee")
        collected = first_number(settlement, "collected_cash", "cash_received")
        if settled_spread is not None:
            spread = settled_spread
        if settled_retained is not None:
            retained = settled_retained
        settled_acquisition_costs = first_number(settlement, "acquisition_costs")
        settled_transaction_costs = first_number(settlement, "transaction_costs")
        if settled_acquisition_costs is not None and settled_transaction_costs is not None:
            settled_costs = settled_acquisition_costs + settled_transaction_costs
            expenses = {**expenses, "recorded_expense_event_total": expenses["attributable"], "attributable": money(settled_costs), "acquisition_costs": money(settled_acquisition_costs), "transaction_costs": money(settled_transaction_costs), "status": "settlement_summary", "source_settlement_id": settlement.get("id")}
            attributable, expense_known = settled_costs + additional, True
            constraints["expense_status"] = "settlement_summary"
        contribution = retained - attributable if retained is not None and expense_known else None
        accepted = 1.0 if stage in CONTRACT_STAGES or stage in {"closed", "funded", "settled"} else selected_acceptance
        expected = accepted * p_close * retained - attributable - accepted * (1 - p_close) * loss if accepted is not None and p_close is not None and retained is not None and loss is not None and expense_known else None
        if stage in {"cancelled", "canceled", "expired", "lost", "rejected"}:
            expected = -attributable if expense_known else None
        elif stage in {"closed", "funded", "settled"}:
            expected = None
        actual_partner = first_number(settlement, "partner_share", "partner_fee", "partner_receipts")
        economics = {"gross_spread": money(spread), "partner_share": money(actual_partner if actual_partner is not None else spread * share if spread is not None else None), "retained_fee": money(retained), "expenses": expenses, "additional_scenario_expenses": money(additional), "contribution": money(contribution), "collected_cash": money(collected), "cash_required": money(cash_required), "expected_contribution": money(expected), "conditional_cash": models["cash"]["prediction"] if models["cash"]["usable"] else None, "cash_timing_status": models["cash"]["status"], "status": "settled_economics" if settlement else "conditional_on_funded_exit" if retained is not None else "pending_price_or_exit", "contract_price": money(contract_price), "forecast_price": money(economics_price), "settlement_id": settlement.get("id"), "loss_exposure": money(loss), "downside": {"lower_executable_price": money(exit_low), "retained_fee_at_lower_price": money((exit_low - economics_price) * (1 - share)) if exit_low is not None and economics_price is not None else None, "failed_transaction_expense_exposure": money(attributable) if expense_known else None, "additional_loss_exposure": money(loss)}, "note": "Retained fees, contribution, and actual collected cash are separate; an absent cash receipt remains unknown."}
        deadline = timestamp(episode.get("deadline", episode.get("contract_deadline")))
        required_deadline = timestamp(rule_values.get("deadline"))
        rule_deadline_days = number(rule_values.get("deadline")) if required_deadline is None else None
        if rule_deadline_days is not None:
            reference = timestamp(episode.get("contract_date", episode.get("created_at")))
            required_deadline = reference + dt.timedelta(days=rule_deadline_days) if reference else None
        if required_deadline:
            deadline = min(deadline, required_deadline) if deadline else required_deadline
        constraints["effective_deadline"] = deadline.isoformat() if deadline else None
        deadline_probability = None
        if deadline and timeline:
            remaining = max(0, (deadline - as_of).total_seconds() / 86400)
            eligible = [day for day in (14, 30, 60, 90) if day <= remaining]
            if eligible:
                deadline_probability = {"probability_lower_bound": timeline[str(max(eligible))]["closed"], "reference_horizon_days": max(eligible), "days_remaining": round(remaining, 2), "method": "nearest_supported_horizon_at_or_before_deadline; no interpolation"}
        closing = {"probability": p_close, "horizon_days": 90, "status": models["closing"]["status"] if timeline or not models["closing"]["usable"] else "invalid_model_forecast", "timeline": timeline, "deadline_probability": deadline_probability, "failure_risk": {key: timeline["90"][key] for key in ("cancelled", "expired", "still_open")} if timeline else None, "observed_terminal_outcome": stage if stage in TERMINAL else None, "model_id": models["closing"]["model_id"], "limitations": models["closing"]["limitations"], "conditional_on": "current recorded transaction stage and model feature support"}
        if global_timeline:
            closing.update(status="global_benchmark_only", global_benchmark=global_timeline, conditional_on="Current-stage support is insufficient; the separate global benchmark is not used for offer optimization or cash forecasts.")
        if stage in TERMINAL:
            offer["recommendation_status"] = "observed_terminal_no_new_offer"
            closing.update(probability=None, timeline=None, deadline_probability=None, failure_risk=None, status="observed_terminal_outcome")
        title_cleared = any("title" in x or "ownership" in x for x in cleared)
        inspection_cleared = any("inspection" in x for x in cleared)
        unresolved = [x for x in events["milestones"] if x.get("required") and x.get("status") not in {"complete", "completed", "cleared", "satisfied", "waived"} and x.get("verified") is not True]
        if missing_required or structure_blocked or spread_blocked:
            action = {"action": "resolve_reviewed_rule_gate", "reason": "Required documents or permitted transaction structure are unresolved.", "priority": 100, "required_documents": missing_required}
        elif capacity_blocked or cash_blocked:
            action = {"action": "resolve_execution_capacity_or_cash", "reason": "Configured resources do not support an additional commitment.", "priority": 99}
        elif stage in TERMINAL:
            action = {"action": "reconcile_collected_cash" if stage in {"closed", "funded", "settled"} and collected is None else "review_terminal_outcome", "reason": "Link final settlement, cash receipt, and attributable expenses to the learning ledger.", "priority": 85 if collected is None else 20}
        elif not title_cleared:
            action = {"action": "obtain_ownership_and_title_evidence", "reason": "Recorded professional title or ownership clearance is missing. Resolve it before relying on closing readiness.", "priority": 95}
        elif deadline and (deadline - as_of).days < 14:
            action = {"action": "review_deadline_and_extension", "reason": "The recorded deadline is near; obtain a documented extension or execution plan.", "priority": 90}
        elif repairs is None or not inspection_cleared:
            action = {"action": "obtain_itemized_inspection", "reason": "Condition and repair estimates require an inspection-linked cost basis.", "priority": 80}
        elif not bid_prices:
            action = {"action": "obtain_executable_partner_bid", "reason": "Stated interest and assessed values do not establish an executable disposition price.", "priority": 75}
        elif unresolved:
            action = {"action": "complete_transaction_milestone", "reason": "A required recorded milestone remains unresolved.", "priority": 70, "milestones": [x.get("name", x.get("id")) for x in unresolved]}
        else:
            action = {"action": "confirm_price_terms_and_seller_response", "reason": "Review the supported offer range and record the actual response and agreed terms.", "priority": 60}
        action["evidence_ids"] = [x.get("id") for x in events["milestones"] if x.get("id")]
        sensitivity = (exit_high - exit_low) * (1 - share) if exit_low is not None and exit_high is not None else None
        information_cost = first_number(scenario, "information_cost", "inspection_cost")
        value_of_information = {"status": "bounded_scenario_sensitivity" if sensitivity is not None else "insufficient_scenarios", "maximum_retained_receipt_change": money(sensitivity), "information_cost": money(information_cost), "net_upper_bound": money(sensitivity - information_cost) if sensitivity is not None and information_cost is not None else None, "acquisition_decision_could_change": bool(asking is not None and exit_low is not None and exit_high is not None and exit_low - min_spread < asking <= exit_high - min_spread), "causal": False, "note": "A price-scenario bound, not an expected or causal benefit of inspection, extension, or follow-up."}
        freshness = []
        stale_after = first_number(scenario, "stale_after_days") or 90
        for row in evidence:
            observed = timestamp(row.get("observed_at"))
            age = max(0, (as_of - observed).days) if observed else None
            freshness.append({"evidence_id": row.get("evidence_id", row.get("id")), "source_id": row.get("source_id"), "observed_at": row.get("observed_at"), "available_at": row.get("available_at", row.get("recorded_at")), "age_days": age, "status": "unknown_timestamp" if age is None else "stale" if age > stale_after else "current"})
        assumptions.append({"name": "stale_after_days", "value": stale_after, "source": "user scenario" if "stale_after_days" in scenario else "planning default"})
        decision_features = {**features, "offered_price": money(target), "offer_price": money(target), "offer_ratio": target / exit_target if target is not None and exit_target else None, "asking_price": asking}
        decision_features = sanitize_features(decision_features, as_of.isoformat())
        acceptance_model = acceptance_models.get(money(target)) or acceptance_model or self._predict("acceptance", decision_features)
        versions = {kind: {"model_id": model["model_id"], "status": model["status"], "synthetic": model["synthetic"], "limitations": model["limitations"]} for kind, model in {**models, "acceptance": acceptance_model}.items()}
        return {"property_id": property_id, "episode_id": episode.get("id"), "as_of": as_of.isoformat(), "stage": stage, "valuation": valuation, "condition": condition, "exit_price": exit_price, "offer": offer, "seller_acceptance": {"probability": selected_acceptance, "status": acceptance_model["status"], "model_id": acceptance_model["model_id"], "by_offer": [{"price": x["price"], "probability": x["seller_acceptance"]} for x in candidates], "causal": False, "limitations": acceptance_model["limitations"]}, "closing": closing, "company_economics": economics, "next_action": action, "evidence": {"sources": evidence, "freshness": freshness, "conflicts": property_detail.get("conflicts", prop.get("conflicts", [])), "provenance": property_detail.get("field_provenance", prop.get("field_provenance", {})), "stale_after_days": stale_after}, "assumptions": assumptions, "model_versions": versions, "liquidity": liquidity, "seller_notes": notes, "constraints": constraints, "rules": rules, "value_of_information": value_of_information, "scenario": scenario, "decision_features": decision_features, "feature_snapshot": decision_features, "features_available_at": as_of.isoformat(), "snapshot_as_of": as_of.isoformat(), "inference_features": {**{kind: features for kind in models}, "acceptance": decision_features}, "synthetic": bool(prop.get("synthetic") or episode.get("synthetic"))}

    def _portfolio_reports(self, scenario):
        result = []
        for episode in self._episodes():
            detail = self.ledger.get_episode(episode["id"])
            prop = detail.get("property", episode.get("property_snapshot", episode.get("property", {})))
            if not isinstance(prop, dict):
                prop = {}
            prop = {"id": episode.get("property_id"), **prop}
            property_detail = prop if "property" in prop else {"property": prop, "evidence": detail.get("evidence", []), "comps": detail.get("comps", [])}
            result.append(self.report(property_detail, episode["id"], scenario))
        return result

    def portfolio(self, scenario=None):
        scenario = scenario or {}
        reports = self._portfolio_reports(scenario)
        collected = [x["company_economics"]["collected_cash"] for x in reports if x["company_economics"]["collected_cash"] is not None]
        forecast = {str(day): {"expected_receipts": 0.0, "supported_episodes": 0, "pending_episodes": 0} for day in (14, 30, 60, 90)}
        concentration = {key: Counter() for key in ("state", "county", "partner", "buyer", "exit_strategy")}
        for report in reports:
            detail = self.ledger.get_episode(report["episode_id"])
            episode = flat(detail["episode"])
            prop = detail.get("property", episode.get("property_snapshot", {}))
            for key, value in {"state": prop.get("state", episode.get("state", "unknown")), "county": prop.get("county_fips", "unknown"), "partner": episode.get("partner_id", episode.get("partner", "unknown")), "exit_strategy": episode.get("exit_strategy", episode.get("structure", "assignment"))}.items():
                concentration[key][str(value)] += 1
            for buyer in {x.get("buyer_id") for x in report["liquidity"]["executable_bids"] if x.get("buyer_id")}:
                concentration["buyer"][str(buyer)] += 1
            economics = report["company_economics"]
            outstanding = max(0, economics["retained_fee"] - (economics["collected_cash"] or 0)) if economics["retained_fee"] is not None else None
            cash = economics["conditional_cash"] or {}
            delay = first_number(cash, "median_days")
            if "cash_delay_days" in scenario:
                delay = first_number(scenario, "cash_delay_days")
            timeline = report["closing"]["timeline"]
            p_accept = 1 if report["stage"] in CONTRACT_STAGES or report["stage"] in {"closed", "funded", "settled"} else report["seller_acceptance"]["probability"]
            for day in (14, 30, 60, 90):
                slot = forecast[str(day)]
                if report["stage"] in {"cancelled", "canceled", "expired", "lost", "rejected"}:
                    slot["supported_episodes"] += 1
                    continue
                if outstanding == 0:
                    slot["supported_episodes"] += 1
                    continue
                if outstanding is None or delay is None or p_accept is None:
                    slot["pending_episodes"] += 1
                    continue
                supported_day = max([h for h in (14, 30, 60, 90) if h <= day - delay], default=None)
                if report["stage"] in {"closed", "funded", "settled"}:
                    close_probability = 1 if day >= delay else 0
                elif timeline and supported_day:
                    close_probability = timeline[str(supported_day)]["closed"]
                elif timeline:
                    close_probability = 0
                else:
                    slot["pending_episodes"] += 1
                    continue
                slot["expected_receipts"] += outstanding * p_accept * close_probability
                slot["supported_episodes"] += 1
        for value in forecast.values():
            value["expected_receipts"] = None if value["pending_episodes"] and not value["supported_episodes"] else money(value["expected_receipts"])
            value["status"] = "unsupported" if value["pending_episodes"] and not value["supported_episodes"] else "partial_pending_support" if value["pending_episodes"] else "supported_model_or_observed_inputs"
        active = sum(1 for x in reports if x["stage"] in CONTRACT_STAGES)
        capacity = first_number(scenario, "capacity", "max_active_contracts")
        configured = [x["constraints"]["capacity"] for x in reports if x["constraints"]["capacity"] is not None]
        if capacity is None and configured:
            capacity = min(configured)
        expected = [x["company_economics"]["expected_contribution"] for x in reports if x["company_economics"]["expected_contribution"] is not None]
        return {"totals": {"episodes": len(reports), "active_contracts": active, "actual_collected_cash": money(sum(collected)), "episodes_with_unrecorded_cash": len(reports) - len(collected), "supported_expected_contribution": money(sum(expected)), "episodes_pending_contribution_forecast": len(reports) - len(expected)}, "forecast": forecast, "concentration": {key: dict(value) for key, value in concentration.items()}, "capacity": {"configured": capacity, "active_contracts": active, "status": "not_configured" if capacity is None else "exceeded" if active > capacity else "within_limit"}, "items": reports, "scenario": scenario, "limitations": ["Forecasts use supported model horizons and median closing-to-cash delay; they are conditional scenario estimates, not assured cash.", "Pending transactions remain visible and are not assigned fabricated zero probabilities.", "Concentration counts are descriptive; allocation recommendations require measured marginal performance."]}

    def queue(self, scenario=None):
        rows = []
        for report in self._portfolio_reports(scenario or {}):
            if report["stage"] in TERMINAL and report["next_action"]["action"] == "review_terminal_outcome":
                continue
            economics = report["company_economics"]
            expected = economics["expected_contribution"]
            potential = economics["retained_fee"]
            score = expected if expected is not None else potential if potential is not None else 0
            rows.append({"property_id": report["property_id"], "episode_id": report["episode_id"], **report["next_action"], "score": money(score), "calculation_label": "supported_probability_weighted_contribution_at_risk" if expected is not None else "potential_retained_fee_not_probability_weighted" if potential is not None else "rule_priority_only_unknown_financial_impact", "value_of_information": report["value_of_information"], "causal_action_uplift": None})
        rows.sort(key=lambda x: (-x["score"], -x["priority"], str(x["episode_id"])))
        return {"items": rows, "limitations": ["Ranking shows supported contribution or explicitly labeled potential receipts. It does not estimate causal improvement from an intervention."]}
