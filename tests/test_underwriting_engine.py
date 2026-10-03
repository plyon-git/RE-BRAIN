import copy
import unittest

from services.underwriting.engine import UnderwritingEngine, seller_note_facts


class Ledger:
    def __init__(self, details=None, rules=None):
        self.details = details or {}
        self.rule_rows = rules or []

    def episodes(self, property_id=None):
        return {"items": [copy.deepcopy(value["episode"]) for value in self.details.values() if property_id is None or value["episode"]["property_id"] == property_id]}

    def get_episode(self, identifier, as_of=None):
        return copy.deepcopy(self.details[identifier])

    def rules(self, filters=None):
        return {"items": copy.deepcopy(self.rule_rows)}


class Registry:
    def __init__(self, ready=False, synthetic=False, invalid_timeline=False):
        self.ready, self.synthetic, self.invalid_timeline = ready, synthetic, invalid_timeline
        self.calls = []

    def predict(self, kind, features):
        self.calls.append((kind, copy.deepcopy(features)))
        if not self.ready:
            return {"status": "untrained", "model_id": None, "synthetic": False, "prediction": None, "limitations": ["No promoted model"]}
        if kind == "valuation":
            prediction = {"as_is_value": 250000, "arv": None, "interval": {"lower": 230000, "upper": 270000}}
        elif kind == "repairs":
            prediction = {"estimated_cost": 20000, "interval": {"lower": 15000, "upper": 30000}}
        elif kind == "acceptance":
            price = features.get("offered_price") or 0
            prediction = {"probability": .15 if price <= 162000 else .65 if price <= 175000 else .9, "causal": False}
        elif kind == "cash":
            prediction = {"median_days": 10, "p10_days": 5, "p90_days": 20, "reference": "closing_to_cash"}
        else:
            rows = {"14": {"closed": .2, "cancelled": .05, "expired": .01, "still_open": .74}, "30": {"closed": .4, "cancelled": .08, "expired": .02, "still_open": .5}, "60": {"closed": .65, "cancelled": .1, "expired": .03, "still_open": .22}, "90": {"closed": .8, "cancelled": .12, "expired": .04, "still_open": .04}}
            if self.invalid_timeline:
                rows["90"]["closed"] = 1.1
            prediction = {"probabilities": rows}
        return {"status": "ready", "model_id": kind + "-v1", "synthetic": self.synthetic, "prediction": prediction, "limitations": ["Observational test fixture"]}


def episode(identifier="e1", property_id="08031-001", stage="lead"):
    prop = {"id": property_id, "state": "CO", "county_fips": "08031", "estimated_value": 240000, "assessed_value": 180000, "repairs": 25000, "purchase_price": 170000}
    return {"episode": {"id": identifier, "property_id": property_id, "stage": stage, "partner_id": "p1", "asking_price": 175000, "cash_required": 2000, "property_snapshot": prop}, "property": prop, "offers": [], "bids": [{"id": "b1", "amount": 200000, "executable": True, "observed_at": "2026-09-01T00:00:00+00:00"}], "milestones": [], "expenses": [{"id": "x1", "amount": 1000, "paid": True}], "settlements": [], "events": [], "decisions": [], "current_settlement": None}


class UnderwritingTests(unittest.TestCase):
    def report(self, record=None, registry=None, rules=None, scenario=None):
        record = record or episode()
        engine = UnderwritingEngine(Ledger({record["episode"]["id"]: record}, rules), registry or Registry())
        return engine.report({"property": record["property"]}, record["episode"]["id"], scenario), engine

    def test_untrained_report_abstains_and_preserves_recorded_estimates(self):
        report, _ = self.report()
        self.assertEqual(report["valuation"]["as_is_value"], 240000)
        self.assertIsNone(report["valuation"]["arv"])
        self.assertIsNone(report["seller_acceptance"]["probability"])
        self.assertIsNone(report["closing"]["timeline"])
        self.assertIsNone(report["company_economics"]["expected_contribution"])
        self.assertEqual(report["offer"]["objective_status"], "deterministic_threshold_only")
        self.assertEqual(report["offer"]["maximum"], 180000)
        self.assertEqual(report["next_action"]["action"], "obtain_ownership_and_title_evidence")
        self.assertTrue(any(x["name"] == "minimum_gross_spread" and "signed" in x["note"] for x in report["assumptions"]))

    def test_interest_and_expired_or_conditional_bids_never_set_exit(self):
        record = episode()
        record["bids"] = [{"amount": 500000, "status": "interest"}, {"amount": 400000, "executable": True, "expires_at": "2000-01-01"}, {"amount": 300000, "executable": True, "conditions": [{"status": "pending"}]}]
        report, _ = self.report(record)
        self.assertIsNone(report["exit_price"]["target"])
        self.assertIsNone(report["offer"]["maximum"])
        self.assertEqual(len(report["exit_price"]["stated_interest"]), 3)

    def test_probability_weighted_price_uses_receipts_expenses_and_loss(self):
        report, _ = self.report(registry=Registry(True), scenario={"loss_exposure": 500, "cash_available": 10000, "capacity": 5})
        self.assertEqual(report["offer"]["target"], 171000)
        candidate = next(x for x in report["offer"]["candidates"] if x["price"] == 171000)
        self.assertEqual(candidate["probability_weighted_contribution"], 6475)
        self.assertEqual(report["seller_acceptance"]["probability"], .65)
        self.assertEqual(report["decision_features"]["offered_price"], 171000)
        self.assertFalse(candidate["causal"])

    def test_synthetic_or_invalid_models_cannot_drive_probabilities(self):
        synthetic, _ = self.report(registry=Registry(True, synthetic=True))
        self.assertIsNone(synthetic["closing"]["probability"])
        self.assertIsNone(synthetic["seller_acceptance"]["probability"])
        invalid, _ = self.report(registry=Registry(True, invalid_timeline=True))
        self.assertIsNone(invalid["closing"]["timeline"])
        self.assertEqual(invalid["closing"]["status"], "invalid_model_forecast")

    def test_global_closing_benchmark_does_not_claim_stage_conditioning(self):
        class GlobalRegistry(Registry):
            def predict(self, kind, features):
                result = super().predict(kind, features)
                if kind == "closing":
                    result["prediction"]["stage_conditioned"] = False
                return result
        report, _ = self.report(registry=GlobalRegistry(True), scenario={"loss_exposure": 0})
        self.assertEqual(report["closing"]["status"], "global_benchmark_only")
        self.assertIsNone(report["closing"]["timeline"])
        self.assertIsNone(report["closing"]["probability"])
        self.assertEqual(report["closing"]["global_benchmark"]["90"]["closed"], .8)
        self.assertTrue(all(x["probability_weighted_contribution"] is None for x in report["offer"]["candidates"]))

    def test_reviewed_rules_are_scoped_and_drafts_do_not_bind(self):
        rules = [
            {"id": "draft", "status": "draft", "jurisdiction": "CO", "effective_from": "2020-01-01", "rules": {"min_profit": 100000}},
            {"id": "wrongstate", "status": "reviewed", "approved_by": "counsel", "jurisdiction": "TX", "effective_from": "2020-01-01", "rules": {"min_profit": 90000}},
            {"id": "future", "status": "reviewed", "approved_by": "counsel", "jurisdiction": "CO", "effective_from": "2099-01-01", "rules": {"min_profit": 80000}},
            {"id": "active", "status": "reviewed", "approved_by": "counsel", "jurisdiction": "CO", "partner_id": "p1", "effective_from": "2020-01-01", "rules": {"min_profit": 30000, "partner_split_pct": 1, "required_documents": ["ownership"]}},
        ]
        report, _ = self.report(rules=rules)
        self.assertEqual(report["offer"]["maximum"], 170000)
        self.assertEqual(report["constraints"]["partner_share_pct"], 1)
        self.assertEqual(report["next_action"]["action"], "resolve_reviewed_rule_gate")
        self.assertEqual(len(report["rules"]["draft"]), 1)
        self.assertEqual(len(report["rules"]["excluded"]), 2)

    def test_cash_and_capacity_block_commitments(self):
        report, _ = self.report(registry=Registry(True), scenario={"loss_exposure": 0, "cash_available": 1000, "capacity": 0})
        self.assertEqual(report["constraints"]["cash_status"], "blocked")
        self.assertEqual(report["constraints"]["capacity_status"], "blocked")
        self.assertTrue(all(x["probability_weighted_contribution"] is None for x in report["offer"]["candidates"]))

    def test_scenario_cannot_relax_reviewed_resources_or_document_rules(self):
        rules = [
            {"id": "global", "status": "reviewed", "approved_by": "counsel", "jurisdiction": "US", "effective_from": "2020-01-01", "rules": {"capacity": 0, "cash_available": 1000, "required_documents": ["ownership"], "min_profit": 30000, "allowed_structures": ["assignment"]}},
            {"id": "local", "status": "reviewed", "approved_by": "counsel", "jurisdiction": "CO", "effective_from": "2021-01-01", "rules": {"capacity": 100, "cash_available": 50000, "required_documents": ["disclosure"], "min_profit": 20000, "allowed_structures": ["flip"]}},
        ]
        report, _ = self.report(rules=rules, scenario={"capacity": 1000, "cash_available": 100000})
        self.assertEqual(report["constraints"]["capacity"], 0)
        self.assertEqual(report["constraints"]["cash_available"], 1000)
        self.assertEqual(report["constraints"]["minimum_gross_spread"], 30000)
        self.assertEqual(set(report["constraints"]["missing_required_documents"]), {"ownership", "disclosure"})
        self.assertTrue(report["constraints"]["structure_blocked"])

    def test_explicit_superseded_reviewed_versions_retire_old_constraints(self):
        rules = [
            {"id": "v1", "status": "reviewed", "approved_by": "counsel", "jurisdiction": "CO", "effective_from": "2020-01-01", "rules": {"min_profit": 50000}},
            {"id": "draft", "status": "draft", "jurisdiction": "CO", "effective_from": "2021-01-01", "supersedes_rule_id": "v1", "rules": {"min_profit": 1000}},
            {"id": "v2", "status": "reviewed", "approved_by": "counsel", "jurisdiction": "CO", "effective_from": "2022-01-01", "supersedes_rule_id": "v1", "rules": {"min_profit": 30000}},
        ]
        report, _ = self.report(rules=rules)
        self.assertEqual(report["constraints"]["minimum_gross_spread"], 30000)
        self.assertEqual([x["id"] for x in report["rules"]["applicable"]], ["v2"])
        self.assertTrue(any(x.get("superseded_by") == "v2" for x in report["rules"]["excluded"]))

    def test_missing_expenses_remain_unknown_until_explicit_scenario(self):
        record = episode()
        record["expenses"] = []
        report, _ = self.report(record, Registry(True), scenario={"loss_exposure": 0})
        self.assertIsNone(report["company_economics"]["expenses"]["attributable"])
        self.assertIsNone(report["company_economics"]["contribution"])
        self.assertIsNone(report["company_economics"]["expected_contribution"])
        scenario, _ = self.report(record, Registry(True), scenario={"loss_exposure": 0, "expenses_complete": True})
        self.assertIsNotNone(scenario["company_economics"]["contribution"])

    def test_settlement_corrections_and_unknown_cash_not_double_counted(self):
        record = episode(stage="closed")
        original = {"id": "s1", "gross_spread": 30000, "retained_fee": 15000, "collected_cash": 15000, "recorded_at": "2026-09-01"}
        correction = {"id": "s2", "gross_spread": 26000, "retained_fee": 13000, "collected_cash": None, "recorded_at": "2026-09-02"}
        record["settlements"], record["current_settlement"] = [original, correction], correction
        report, engine = self.report(record)
        self.assertEqual(report["company_economics"]["retained_fee"], 13000)
        self.assertEqual(report["company_economics"]["contribution"], 12000)
        self.assertIsNone(report["company_economics"]["collected_cash"])
        portfolio = engine.portfolio()
        self.assertEqual(portfolio["totals"]["actual_collected_cash"], 0)
        self.assertEqual(portfolio["totals"]["episodes_with_unrecorded_cash"], 1)
        self.assertEqual(portfolio["forecast"]["90"]["pending_episodes"], 1)
        self.assertIsNone(portfolio["forecast"]["90"]["expected_receipts"])

    def test_funded_settlement_cost_summary_is_authoritative_and_cash_separate(self):
        record = episode(stage="under_contract")
        record["expenses"] = []
        record["current_settlement"] = {"id": "funded", "closed_at": "2026-09-01", "gross_spread": 40000, "partner_share": 20000, "company_receipts": 20000, "acquisition_costs": 3000, "transaction_costs": 1000, "cash_received": None}
        report, _ = self.report(record, Registry(True))
        self.assertEqual(report["stage"], "funded")
        self.assertEqual(report["company_economics"]["contribution"], 16000)
        self.assertIsNone(report["company_economics"]["collected_cash"])
        self.assertEqual(report["company_economics"]["expenses"]["acquisition_costs"], 3000)
        self.assertIsNone(report["closing"]["probability"])
        self.assertIsNone(report["closing"]["timeline"])
        self.assertEqual(report["closing"]["observed_terminal_outcome"], "funded")

    def test_historical_values_use_only_available_history_and_authority(self):
        record = episode()
        detail = {"property": {**record["property"], "estimated_value": 999999, "repairs": 99999}, "evidence_history": [
            {"source_id": "assessor", "source_record_id": "1", "category": "assessor", "observed_at": "2026-01-01", "available_at": "2026-01-02", "attributes": {"estimated_value": 170000, "assessed_value": 150000}},
            {"source_id": "market", "source_record_id": "2", "category": "market", "observed_at": "2026-01-01", "available_at": "2026-01-03", "attributes": {"estimated_value": 200000, "repairs": 10000}},
            {"source_id": "market", "source_record_id": "2", "category": "market", "observed_at": "2026-01-01", "available_at": "2026-03-01", "attributes": {"estimated_value": 999999, "repairs": 99999}},
        ]}
        engine = UnderwritingEngine(Ledger({"e1": record}), Registry())
        report = engine.report(detail, "e1", {"as_of": "2026-02-01"})
        self.assertEqual(report["valuation"]["as_is_value"], 200000)
        self.assertEqual(report["condition"]["estimated_repairs"], 10000)
        self.assertEqual(report["decision_features"]["estimated_value"], 200000)
        absent = engine.report({"property": detail["property"]}, "e1", {"as_of": "2026-02-01"})
        self.assertIsNone(absent["valuation"]["as_is_value"])
        self.assertNotIn("estimated_value", absent["decision_features"])

    def test_future_events_do_not_make_executable_exit(self):
        record = episode()
        record["bids"][0]["available_at"] = "2099-01-01"
        report, _ = self.report(record)
        self.assertIsNone(report["exit_price"]["target"])

    def test_snapshot_features_exclude_outcomes_and_unknown_identities(self):
        record = episode()
        record["property"]["actual_profit"] = 100000
        record["property"]["cash_received"] = 50000
        report, _ = self.report(record)
        self.assertNotIn("actual_profit", report["feature_snapshot"])
        self.assertNotIn("cash_received", report["feature_snapshot"])
        self.assertNotIn("id", report["feature_snapshot"])
        self.assertEqual(report["feature_snapshot"], report["decision_features"])
        self.assertEqual(report["features_available_at"], report["as_of"])

    def test_local_nlp_retains_spans_and_flags_price_assumption(self):
        text = "Seller asking $175k. Tenant-occupied; leaking roof. Must have cash by 2026-12-01."
        facts = seller_note_facts(text)
        for fact in facts:
            self.assertEqual(text[fact["start"]:fact["end"]], fact["text"])
            self.assertTrue(fact["review_required"])
        self.assertEqual(next(x["value"] for x in facts if x["kind"] == "asking_price"), 175000)
        record = episode()
        record["episode"].pop("asking_price")
        record["episode"]["notes"] = text
        report, _ = self.report(record)
        assumption = next(x for x in report["assumptions"] if x["name"] == "seller_asking_price")
        self.assertTrue(assumption["review_required"])

    def test_portfolio_forecast_partial_support_not_assured_cash(self):
        a = episode(stage="under_contract")
        a["episode"]["contract_price"] = 170000
        b = episode("e2", "08031-002", "closed")
        b["current_settlement"] = {"retained_fee": 10000, "collected_cash": 10000}
        engine = UnderwritingEngine(Ledger({"e1": a, "e2": b}), Registry(True))
        portfolio = engine.portfolio({"loss_exposure": 500})
        self.assertEqual(portfolio["totals"]["actual_collected_cash"], 10000)
        self.assertEqual(portfolio["forecast"]["90"]["expected_receipts"], 9750)
        self.assertEqual(portfolio["concentration"]["state"]["CO"], 2)
        self.assertTrue(any("not assured" in x for x in portfolio["limitations"]))

    def test_failed_outcome_stays_observed_not_open_forecast(self):
        record = episode(stage="cancelled")
        _, engine = self.report(record, Registry(True))
        portfolio = engine.portfolio()
        self.assertEqual(portfolio["forecast"]["90"]["expected_receipts"], 0)
        self.assertEqual(portfolio["forecast"]["90"]["pending_episodes"], 0)

    def test_demand_deterioration_is_descriptive_and_requires_support(self):
        record = episode()
        record["bids"] = [{"id": str(index), "amount": amount, "executable": True, "observed_at": f"2026-09-0{index+1}"} for index, amount in enumerate([220000, 210000, 190000, 180000])]
        report, _ = self.report(record)
        demand = report["liquidity"]["demand_deterioration"]
        self.assertEqual(demand["status"], "deteriorating")
        self.assertFalse(demand["causal"])
        self.assertEqual(demand["earlier_count"], 2)
        self.assertFalse(report["value_of_information"]["causal"])

    def test_queue_exposes_potential_not_fake_action_uplift(self):
        _, engine = self.report()
        row = engine.queue()["items"][0]
        self.assertEqual(row["calculation_label"], "potential_retained_fee_not_probability_weighted")
        self.assertIsNone(row["causal_action_uplift"])


if __name__ == "__main__":
    unittest.main()
