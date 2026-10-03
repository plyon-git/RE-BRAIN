"""Model governance tests using generated test fixtures, never transaction evidence.

These rows deliberately pass ``synthetic=False`` in several tests to exercise
the production lifecycle. They are unit-test fixtures and make no claims about
101XVC's real performance, real labels, or trained production models.
"""

import copy
import json
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.underwriting.registry import ModelRegistry, aalen_johansen


def timestamp(index):
    return (datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).isoformat().replace("+00:00", "Z")


def valuation_rows(count=120, offset=0):
    rows = []
    for index in range(count):
        # Repeat the price range across time so validation tests model quality,
        # instead of accidentally making chronology a price-drift stress test.
        sqft = 850 + ((index * 37) % 1100)
        bedrooms = 2 + index % 3
        bathrooms = 1 + (index % 4) * .5
        assessed_value = 110000 + sqft * 65
        features = {
            "sqft": sqft,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "year_built": 1950 + index % 65,
            "lot_sqft": 4500 + index % 9 * 300,
            "assessed_value": assessed_value,
        }
        label = 42000 + sqft * 130 + bedrooms * 6000 + bathrooms * 8000 + ((index % 5) - 2) * 200
        rows.append({"row_id": f"valuation-{offset + index}", "property_id": f"parcel-{offset + index}", "decision_at": timestamp(offset + index), "label_available_at": timestamp(offset + index + 30), "features": features, "label": label})
    return rows


def acceptance_rows(count=200):
    rows = []
    for index in range(count):
        reference = 170000 + (index % 7) * 11000
        ratio = .65 + ((index * 37) % 80) / 100
        # Offer price changes acceptance while property value remains usable
        # at the decision time. Both labels occur in every chronological block.
        features = {"offered_price": reference * ratio, "assessed_value": reference, "sqft": 1200 + index % 5 * 100}
        rows.append({"row_id": f"acceptance-{index}", "property_id": f"offer-parcel-{index}", "decision_at": timestamp(index), "label_available_at": timestamp(index + 1), "features": features, "label": int(ratio >= 1.05)})
    return rows


def cash_rows(count=160):
    rows = []
    for index in range(count):
        partner = "fast-title" if index % 2 == 0 else "slow-title"
        delay = (3 if partner == "fast-title" else 18) + (index % 3) - 1
        # The cash model's decision clock begins at funded closing; its label
        # becomes observable only when cash actually arrives after that date.
        rows.append({"row_id": f"cash-{index}", "property_id": f"cash-parcel-{index}", "decision_at": timestamp(index), "label_available_at": timestamp(index + delay), "features": {"partner_id": partner, "state": "TX", "county_fips": "48439"}, "label": float(delay)})
    return rows


def closing_rows(count=200):
    rows = []
    for index in range(count):
        partner = "fast-title" if index % 2 == 0 else "slow-title"
        event = "closed" if index % 2 == 0 else "cancelled" if index % 4 == 1 else "expired"
        duration = 10 + index % 3 if event == "closed" else 35 + index % 7
        if index % 11 == 0:
            event, duration = "censored", 20
        rows.append({"row_id": f"closing-{index}", "property_id": f"closing-parcel-{index}", "decision_at": timestamp(index), "label_available_at": timestamp(index + duration), "features": {"partner_id": partner, "state": "TX", "county_fips": "48439"}, "label": {"duration": duration, "event": event}})
    return rows


class ModelRegistryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "nested"
        self.registry = ModelRegistry(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def train_valuation(self, rows=None, synthetic=False):
        result = self.registry.train("valuation", valuation_rows() if rows is None else rows, synthetic=synthetic)
        self.assertEqual(result["kind"], "valuation")
        self.assertEqual(result["status"], "candidate")
        self.assertIn("model_id", result)
        self.assertIn("dataset_fingerprint", result)
        return result

    def eligible_valuation(self, rows=None):
        result = self.train_valuation(rows)
        self.assertTrue(result["gate"]["eligible"], result["gate"])
        self.assertEqual(result["support"]["availability_unverified"], 0)
        self.assertTrue(result["gate"]["temporal_availability_verified"])
        split = result["validation"]["split"]
        self.assertLessEqual(split["train_max_label_available_at"], split["training_cutoff"])
        return result

    def test_untrained_registry_abstains_for_every_target(self):
        for kind in ("valuation", "repairs", "acceptance", "closing", "cash"):
            with self.subTest(kind=kind):
                prediction = self.registry.predict(kind, {"sqft": 1300, "offered_price": 170000})
                self.assertEqual(prediction["status"], "untrained")
                self.assertIsNone(prediction["prediction"])
                self.assertIsNone(prediction["model_id"])
                self.assertTrue(prediction["limitations"])
        self.assertEqual(self.registry.status()["active"], {})

    def test_training_creates_a_candidate_without_activating_it(self):
        result = self.eligible_valuation()
        self.assertFalse(result["synthetic"])
        self.assertEqual(self.registry.status()["active"], {})
        self.assertEqual(self.registry.predict("valuation", {"sqft": 1300})["status"], "untrained")
        self.assertIn(result["model_id"], [item["model_id"] for item in self.registry.status()["models"]])
        metrics = result["validation"]["metrics"]
        self.assertTrue(math.isfinite(metrics["mae"]))
        self.assertGreater(metrics["baseline_mae"], metrics["mae"])
        self.assertGreater(metrics["improvement"], 0)

    def test_chronological_holdout_has_no_property_overlap(self):
        rows = valuation_rows()
        repeat = copy.deepcopy(rows[0])
        repeat.update(row_id="late-repeat", decision_at=timestamp(121), label_available_at=timestamp(151))
        rows.append(repeat)
        result = self.train_valuation(rows)
        split = result["validation"]["split"]
        train_properties = set(split["train_property_ids"])
        validation_properties = set(split["validation_property_ids"])
        self.assertFalse(train_properties & validation_properties)
        self.assertFalse(set(split["train_row_ids"]) & set(split["validation_row_ids"]))
        self.assertLessEqual(split["train_max_timestamp"], split["validation_min_timestamp"])
        self.assertLessEqual(split["train_max_label_available_at"], split["training_cutoff"])
        self.assertEqual(split["training_cutoff"], split["validation_min_timestamp"])
        self.assertGreaterEqual(result["support"]["train"], 12)
        self.assertGreaterEqual(result["support"]["validation"], 5)
        self.assertEqual(result["support"]["total"], result["support"]["train"] + result["support"]["validation"] + result["support"]["excluded"])

    def test_constant_labels_cannot_beat_a_median_baseline(self):
        rows = valuation_rows()
        for row in rows:
            row["label"] = 250000.0
        result = self.train_valuation(rows)
        self.assertFalse(result["gate"]["eligible"])
        self.assertTrue(result["gate"]["reason"])
        with self.assertRaises(ValueError):
            self.registry.promote(result["model_id"])
        self.assertEqual(self.registry.status()["active"], {})

    def test_synthetic_data_cannot_be_promoted(self):
        explicitly_synthetic = self.train_valuation(synthetic=True)
        self.assertTrue(explicitly_synthetic["synthetic"])
        self.assertFalse(explicitly_synthetic["gate"]["eligible"])
        with self.assertRaises(ValueError):
            self.registry.promote(explicitly_synthetic["model_id"])
        rows = valuation_rows(offset=200)
        rows[0]["synthetic"] = True
        marked_in_row = self.train_valuation(rows, synthetic=False)
        self.assertTrue(marked_in_row["synthetic"])
        self.assertFalse(marked_in_row["gate"]["eligible"])
        with self.assertRaises(ValueError):
            self.registry.promote(marked_in_row["model_id"])

    def test_promoted_version_persists_and_rollback_restores_prediction(self):
        first = self.eligible_valuation()
        self.registry.promote(first["model_id"])
        features = valuation_rows()[25]["features"]
        first_prediction = self.registry.predict("valuation", features)
        self.assertEqual(first_prediction["model_id"], first["model_id"])
        self.assertIsNotNone(first_prediction["prediction"])
        rows = valuation_rows(offset=200)
        for row in rows:
            row["label"] += 30000
        second = self.eligible_valuation(rows)
        self.registry.promote(second["model_id"])
        self.assertEqual(self.registry.status()["active"]["valuation"], second["model_id"])
        restored = ModelRegistry(self.path)
        self.assertEqual(restored.predict("valuation", features)["model_id"], second["model_id"])
        restored.rollback("valuation", first["model_id"])
        self.assertEqual(restored.predict("valuation", features), first_prediction)
        self.assertEqual(ModelRegistry(self.path).status()["active"]["valuation"], first["model_id"])

    def test_future_trained_incumbent_cannot_validate_an_earlier_candidate(self):
        later = self.eligible_valuation(valuation_rows(offset=400))
        self.registry.promote(later["model_id"])
        earlier_rows = valuation_rows()
        for row in earlier_rows:
            row["label"] += 30000
        earlier = self.eligible_valuation(earlier_rows)
        later_split = later["validation"]["split"]
        earlier_split = earlier["validation"]["split"]
        self.assertGreater(later_split["train_max_label_available_at"], earlier_split["training_cutoff"])
        self.assertFalse(set(later_split["train_row_ids"]) & set(earlier_split["validation_row_ids"]))
        with self.assertRaisesRegex(ValueError, "unavailable at .*cutoff"):
            self.registry.promote(earlier["model_id"])
        self.assertEqual(self.registry.status()["active"]["valuation"], later["model_id"])
        self.assertEqual(ModelRegistry(self.path).status()["active"]["valuation"], later["model_id"])

    def test_fingerprint_and_prior_version_are_immutable(self):
        rows = valuation_rows()
        first = self.eligible_valuation(rows)
        prior = copy.deepcopy(first)
        repeated = self.train_valuation(copy.deepcopy(rows))
        self.assertEqual(repeated["dataset_fingerprint"], first["dataset_fingerprint"])
        changed = copy.deepcopy(rows)
        changed[0]["label"] += 1000
        third = self.train_valuation(changed)
        self.assertNotEqual(third["dataset_fingerprint"], first["dataset_fingerprint"])
        self.assertNotEqual(third["model_id"], first["model_id"])
        original = next(model for model in self.registry.status()["models"] if model["model_id"] == first["model_id"])
        self.assertEqual(original, prior)

    def test_outcome_fields_cannot_enter_features_or_change_inference(self):
        leaked = valuation_rows()
        denied = ("final_sale_price", "realized_sale_price", "repair_cost", "accepted", "closed_at", "close_to_cash", "duration", "event")
        for row in leaked:
            for field in denied:
                row["features"][field] = row["label"]
        candidate = self.eligible_valuation(leaked)
        self.assertFalse(set(candidate["features"]) & set(denied))
        self.registry.promote(candidate["model_id"])
        clean = valuation_rows()[35]["features"]
        expected = self.registry.predict("valuation", clean)
        poisoned = dict(clean, **{field: 999999999 for field in denied})
        self.assertEqual(self.registry.predict("valuation", poisoned), expected)

    def test_failed_atomic_activation_keeps_previous_active_model(self):
        first = self.eligible_valuation()
        self.registry.promote(first["model_id"])
        rows = valuation_rows(offset=200)
        for row in rows:
            row["label"] += 30000
        second = self.eligible_valuation(rows)
        before = copy.deepcopy(self.registry.status()["active"])
        with patch("services.underwriting.registry.os.replace", side_effect=OSError("simulated storage failure")):
            with self.assertRaises(OSError):
                self.registry.promote(second["model_id"])
        self.assertEqual(self.registry.status()["active"], before)
        self.assertEqual(ModelRegistry(self.path).status()["active"], before)
        self.registry.promote(second["model_id"])
        promoted = copy.deepcopy(self.registry.status()["active"])
        with patch("services.underwriting.registry.os.replace", side_effect=OSError("simulated storage failure")):
            with self.assertRaises(OSError):
                self.registry.rollback("valuation", first["model_id"])
        self.assertEqual(self.registry.status()["active"], promoted)
        self.assertEqual(ModelRegistry(self.path).status()["active"], promoted)

    def test_acceptance_uses_offer_and_reports_holdout_calibration(self):
        candidate = self.registry.train("acceptance", acceptance_rows(), synthetic=False)
        self.assertIn("offered_price", candidate["features"])
        metrics = candidate["validation"]["metrics"]
        self.assertLess(metrics["brier"], metrics["baseline_brier"])
        self.assertGreaterEqual(metrics["calibration_error"], 0)
        self.assertLessEqual(metrics["calibration_error"], 1)
        self.assertTrue(candidate["gate"]["eligible"], candidate["gate"])
        self.registry.promote(candidate["model_id"])
        low = self.registry.predict("acceptance", {"offered_price": 130000, "assessed_value": 200000, "sqft": 1400})
        high = self.registry.predict("acceptance", {"offered_price": 290000, "assessed_value": 200000, "sqft": 1400})
        self.assertGreater(self.probability(high["prediction"]), self.probability(low["prediction"]))
        unsupported = self.registry.predict("acceptance", {"offered_price": 1, "assessed_value": 200000, "sqft": 1400})
        self.assertEqual(unsupported["status"], "insufficient_support")
        self.assertIsNone(unsupported["prediction"])

    def test_uninformative_acceptance_cannot_pass_the_baseline_gate(self):
        rows = acceptance_rows()
        for index, row in enumerate(rows):
            row["features"] = {"offered_price": 200000, "assessed_value": 250000, "sqft": 1400}
            row["label"] = index % 2
        candidate = self.registry.train("acceptance", rows, synthetic=False)
        self.assertFalse(candidate["gate"]["eligible"])
        self.assertTrue(candidate["gate"]["reason"])
        with self.assertRaises(ValueError):
            self.registry.promote(candidate["model_id"])

    @staticmethod
    def probability(prediction):
        if isinstance(prediction, (int, float)):
            return prediction
        for field in ("probability", "probability_accepted", "acceptance_probability"):
            if field in prediction:
                return prediction[field]
        raise AssertionError("Acceptance prediction lacks a documented probability")

    def test_repairs_regression_and_partner_cash_delays_are_separate_targets(self):
        rows = valuation_rows()
        for index, row in enumerate(rows):
            sqft = row["features"]["sqft"]
            condition = 1 + (index * 7) % 5
            row["features"] = {"sqft": sqft, "condition_score": condition, "year_built": 1960 + index % 45}
            row["label"] = 3000 + sqft * 9 + condition * 6500 + ((index % 5) - 2) * 50
        repairs = self.registry.train("repairs", rows, synthetic=False)
        cash = self.registry.train("cash", cash_rows(), synthetic=False)
        for kind, candidate in (("repairs", repairs), ("cash", cash)):
            with self.subTest(kind=kind):
                self.assertTrue(candidate["gate"]["eligible"], candidate["gate"])
                self.assertLess(candidate["validation"]["metrics"]["mae"], candidate["validation"]["metrics"]["baseline_mae"])
                self.registry.promote(candidate["model_id"])
                self.assertEqual(self.registry.status()["active"][kind], candidate["model_id"])
        fast = self.registry.predict("cash", {"partner_id": "fast-title", "state": "TX", "county_fips": "48439"})
        slow = self.registry.predict("cash", {"partner_id": "slow-title", "state": "TX", "county_fips": "48439"})
        self.assertLess(self.central_value(fast["prediction"]), self.central_value(slow["prediction"]))

    @staticmethod
    def central_value(prediction):
        if isinstance(prediction, (int, float)):
            return prediction
        for field in ("value", "estimate", "median", "median_days", "days", "p50"):
            if field in prediction:
                return prediction[field]
        raise AssertionError("Prediction lacks a documented central estimate")

    def test_invalid_training_rows_are_excluded_and_cannot_support_promotion(self):
        with self.assertRaises(ValueError):
            self.registry.train("valuation", "not rows", synthetic=False)
        for data in ([None] * 30, [{"features": [], "label": 0}] * 30):
            with self.subTest(data=type(data).__name__):
                result = self.registry.train("valuation", data, synthetic=False)
                self.assertEqual(result["support"]["excluded"], len(data))
                self.assertEqual(result["support"]["train"], 0)
                self.assertEqual(result["support"]["validation"], 0)
                self.assertFalse(result["gate"]["eligible"])
                with self.assertRaises(ValueError):
                    self.registry.promote(result["model_id"])
        for field, invalid in (("label", float("nan")), ("decision_at", "next Tuesday"), ("property_id", "")):
            rows = valuation_rows()
            rows[0][field] = invalid
            with self.subTest(field=field):
                result = self.registry.train("valuation", rows, synthetic=False)
                self.assertEqual(result["support"]["usable"], len(rows) - 1)
                self.assertEqual(result["support"]["excluded"] - result["support"]["purged_label_availability"], 1)
                split = result["validation"]["split"]
                self.assertNotIn(rows[0]["row_id"], split["train_row_ids"] + split["validation_row_ids"])
        with self.assertRaises(ValueError):
            self.registry.train("valuation", valuation_rows(), synthetic="false")

    def test_features_available_after_decision_are_excluded_from_training(self):
        rows = valuation_rows()
        for index, row in enumerate(rows):
            row["features"]["future_appraised_value"] = {"value": row["label"], "available_at": timestamp(index + 1)}
            row["features"]["prior_tax_value"] = {"value": row["features"]["assessed_value"], "available_at": row["decision_at"]}
        result = self.eligible_valuation(rows)
        self.assertNotIn("future_appraised_value", result["features"])
        self.assertIn("prior_tax_value", result["features"])

    def test_missing_label_availability_blocks_promotion_despite_good_fit(self):
        for missing_all in (False, True):
            rows = valuation_rows()
            affected = rows if missing_all else [rows[-1]]
            for row in affected:
                del row["label_available_at"]
            with self.subTest(missing_all=missing_all):
                candidate = self.train_valuation(rows)
                self.assertGreater(candidate["support"]["availability_unverified"], 0)
                self.assertFalse(candidate["validation"]["label_availability"]["verified"])
                self.assertFalse(candidate["gate"]["temporal_availability_verified"])
                self.assertLess(candidate["validation"]["metrics"]["mae"], candidate["validation"]["metrics"]["baseline_mae"])
                self.assertFalse(candidate["gate"]["eligible"])
                self.assertIn("availability", candidate["gate"]["reason"].lower())
                with self.assertRaises(ValueError):
                    self.registry.promote(candidate["model_id"])
        self.assertEqual(self.registry.status()["active"], {})

    def test_future_training_labels_are_purged_and_cannot_influence_fit(self):
        rows = valuation_rows()
        rows[0]["label"] = 999999999.0
        rows[0]["label_available_at"] = timestamp(250)
        candidate = self.eligible_valuation(rows)
        split = candidate["validation"]["split"]
        self.assertIn(rows[0]["row_id"], split["purged_row_ids"])
        self.assertNotIn(rows[0]["row_id"], split["train_row_ids"])
        self.assertNotIn(rows[0]["row_id"], split["validation_row_ids"])
        self.assertEqual(candidate["support"]["purged_label_availability"], len(split["purged_row_ids"]))
        self.assertEqual(candidate["support"]["total"], candidate["support"]["train"] + candidate["support"]["validation"] + candidate["support"]["excluded"])
        # Removing the unavailable row altogether must yield the same fit and
        # holdout metrics as retaining its extreme future label in the input.
        without_future = self.eligible_valuation(rows[1:])
        self.assertEqual(split["train_row_ids"], without_future["validation"]["split"]["train_row_ids"])
        self.assertEqual(split["validation_row_ids"], without_future["validation"]["split"]["validation_row_ids"])
        self.assertEqual(candidate["validation"]["metrics"], without_future["validation"]["metrics"])

    def test_label_purge_can_leave_insufficient_temporal_support(self):
        rows = valuation_rows(count=24)
        candidate = self.train_valuation(rows)
        self.assertEqual(candidate["support"]["train"], 0)
        self.assertEqual(candidate["support"]["purged_label_availability"], 18)
        self.assertEqual(candidate["support"]["validation"], 6)
        self.assertFalse(candidate["gate"]["eligible"])
        with self.assertRaises(ValueError):
            self.registry.promote(candidate["model_id"])
        self.assertEqual(self.registry.predict("valuation", rows[0]["features"])["status"], "untrained")

    def test_outcome_occurrence_alone_does_not_verify_label_availability(self):
        rows = valuation_rows()
        for row in rows:
            row["outcome_at"] = row.pop("label_available_at")
        candidate = self.train_valuation(rows)
        self.assertGreater(candidate["support"]["availability_unverified"], 0)
        self.assertFalse(candidate["gate"]["eligible"])
        self.assertFalse(candidate["validation"]["label_availability"]["verified"])
        with self.assertRaises(ValueError):
            self.registry.promote(candidate["model_id"])

    def test_closing_label_cannot_be_available_before_its_elapsed_duration(self):
        rows = closing_rows()
        # An intentionally inconsistent claimed timestamp must not move a
        # future censoring observation into the earlier training risk set.
        rows[0]["label"] = {"duration": 1000, "event": "censored"}
        rows[0]["label_available_at"] = rows[0]["decision_at"]
        candidate = self.registry.train("closing", rows, synthetic=False)
        split = candidate["validation"]["split"]
        self.assertIn(rows[0]["row_id"], split["purged_row_ids"])
        self.assertNotIn(rows[0]["row_id"], split["train_row_ids"])
        self.assertLessEqual(split["train_max_label_available_at"], split["training_cutoff"])
        artifact = json.loads((self.path / "versions" / (candidate["model_id"] + ".json")).read_text())
        persisted_row = next(row for row in artifact["dataset"]["rows"] if row["row_id"] == rows[0]["row_id"])
        self.assertFalse(persisted_row["label_availability_verified"])
        self.assertGreater(persisted_row["label_available_at"], split["training_cutoff"])

    def test_closing_model_preserves_competing_outcomes_and_censor_diagnostics(self):
        candidate = self.registry.train("closing", closing_rows(), synthetic=False)
        self.assertEqual(candidate["validation"]["estimator"]["name"], "aalen-johansen")
        self.assertGreater(candidate["validation"]["estimator"]["censored"], 0)
        curves = candidate["validation"]["cumulative_incidence"]
        self.assertEqual(set(curves), {"14", "30", "60", "90"})
        for probabilities in curves.values():
            self.assertEqual(set(probabilities), {"closed", "cancelled", "expired", "still_open"})
            self.assertTrue(all(0 <= value <= 1 for value in probabilities.values()))
            self.assertAlmostEqual(sum(probabilities.values()), 1)
        metrics = candidate["validation"]["metrics"]
        self.assertGreaterEqual(metrics["brier"], 0)
        self.assertGreaterEqual(metrics["calibration_error"], 0)
        self.assertEqual(self.registry.status()["active"], {})

    def test_invalid_identifiers_and_cross_kind_rollback_are_rejected(self):
        first = self.eligible_valuation()
        for action in (
            lambda: self.registry.promote("missing-model"),
            lambda: self.registry.rollback("valuation", "missing-model"),
            lambda: self.registry.rollback("repairs", first["model_id"]),
        ):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.registry.status()["active"], {})


class CompetingRisksTests(unittest.TestCase):
    def test_right_censoring_changes_risk_set_without_becoming_failure(self):
        labels = [
            {"duration": 10, "event": "closed"},
            {"duration": 20, "event": "censored"},
            {"duration": 30, "event": "cancelled"},
            {"duration": 40, "event": "expired"},
        ]
        curves = aalen_johansen(labels)
        self.assertAlmostEqual(curves["14"]["closed"], .25)
        self.assertAlmostEqual(curves["14"]["still_open"], .75)
        self.assertAlmostEqual(curves["30"]["closed"], .25)
        self.assertAlmostEqual(curves["30"]["cancelled"], .375)
        self.assertAlmostEqual(curves["30"]["still_open"], .375)
        self.assertAlmostEqual(curves["60"]["expired"], .375)
        self.assertAlmostEqual(curves["60"]["still_open"], 0)
        previous = {event: 0 for event in ("closed", "cancelled", "expired")}
        for horizon in ("14", "30", "60", "90"):
            probabilities = curves[horizon]
            self.assertLessEqual(sum(probabilities[event] for event in previous), 1 + 1e-12)
            self.assertAlmostEqual(sum(probabilities.values()), 1)
            for event in previous:
                self.assertGreaterEqual(probabilities[event], previous[event])
                previous[event] = probabilities[event]

    def test_tied_events_use_one_shared_risk_set(self):
        curves = aalen_johansen([
            {"duration": 10, "event": "closed"},
            {"duration": 10, "event": "cancelled"},
            {"duration": 10, "event": "censored"},
            {"duration": 20, "event": "expired"},
        ])
        self.assertAlmostEqual(curves["14"]["closed"], .25)
        self.assertAlmostEqual(curves["14"]["cancelled"], .25)
        self.assertAlmostEqual(curves["14"]["still_open"], .5)
        self.assertAlmostEqual(curves["30"]["expired"], .5)

    def test_all_censored_sample_abstains_from_inventing_outcomes(self):
        curves = aalen_johansen([{"duration": day, "event": "censored"} for day in (10, 20, 45, 70)])
        for probabilities in curves.values():
            self.assertEqual(probabilities["closed"], 0)
            self.assertEqual(probabilities["cancelled"], 0)
            self.assertEqual(probabilities["expired"], 0)
            self.assertEqual(probabilities["still_open"], 1)


if __name__ == "__main__":
    unittest.main()
