"""Local, versioned statistical models for 101XVC's observed transaction outcomes.

Only decision-time features may enter a fit. Candidates are never activated by
training; chronological holdout evidence, calibration, and support gates govern
promotion. This module needs only the Python standard library.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "101xvc-local-models-v2-temporal"
KINDS = {"valuation", "repairs", "acceptance", "closing", "cash"}
ALIASES = {"time_to_cash": "cash", "time_to_close": "closing", "closing_timing": "closing"}
HORIZONS = (14, 30, 60, 90)
MIN_SUPPORT = 20
_LOCK = threading.RLock()
_LEAK = re.compile(r"(^|_)(actual|settled|settlement|outcome|label|target|accepted|rejected|cancelled|expired|terminal|paid|received|duration|event|sold|final)(_|$)|sale_price|repair_cost|cash_delay|close_to_cash|days_to_|time_to_|closed_at|closing_date|close_date|cash_received|realized_profit|realized_contribution", re.I)
_IDENTIFIERS = {"property_id", "parcel_id", "episode_id", "decision_id", "address", "owner", "owner_name", "record_id"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _quantile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _safe_features(features: Any, decision_at: str) -> dict[str, Any]:
    if not isinstance(features, dict):
        return {}
    result = {}
    for key, value in sorted(features.items()):
        if not isinstance(key, str) or len(key) > 100 or _LEAK.search(key) or key.lower() in _IDENTIFIERS:
            continue
        if isinstance(value, dict) and "value" in value:
            available = _time(value.get("available_at") or value.get("observed_at"))
            if available is None or available > decision_at:
                continue
            value = value["value"]
        if isinstance(value, (int, float, bool)):
            value = _number(value)
            if value is None:
                continue
        elif isinstance(value, str):
            if len(value) > 120:
                continue
            value = value.strip()
            if not value:
                continue
        else:
            continue
        result[key] = value
    return result


def sanitize_features(features: Any, decision_at: str | None = None) -> dict[str, Any]:
    """Keep supported facts available at the stated prediction time.

    The ledger must still supply an immutable decision snapshot; sanitization
    cannot recover undocumented timing or identify every possible outcome proxy.
    """
    cutoff = _time(decision_at) if decision_at is not None else _now()
    if cutoff is None:
        raise ValueError("decision_at must be an ISO timestamp")
    return _safe_features(features, cutoff)


def _event(label: dict) -> str | None:
    event = str(label.get("event", "")).lower()
    return {"closed": "closed", "funded": "closed", "cancelled": "cancelled", "canceled": "cancelled", "failed": "cancelled", "expired": "expired", "censored": "censored", "open": "censored"}.get(event)


def aalen_johansen(labels: Iterable[dict], horizons=HORIZONS) -> dict[str, dict[str, float]]:
    """Empirical competing-risk CIF; right-censored rows remain in their risk set.

    Events at a time are counted before censoring at that same time. No
    independence between competing causes is assumed. Informative censoring
    remains a substantive limitation of this estimator.
    """
    observations = []
    for label in labels:
        duration = _number(label.get("duration"))
        event = _event(label)
        if duration is not None and duration >= 0 and event is not None:
            observations.append((duration, event))
    risk = len(observations)
    survival = 1.0
    incidence = {"closed": 0.0, "cancelled": 0.0, "expired": 0.0}
    by_time = defaultdict(Counter)
    for duration, event in observations:
        by_time[duration][event] += 1
    snapshots = []
    for time in sorted(by_time):
        counts = by_time[time]
        terminal = sum(counts[cause] for cause in incidence)
        if risk:
            for cause in incidence:
                incidence[cause] += survival * counts[cause] / risk
            survival *= max(0.0, 1.0 - terminal / risk)
        snapshots.append((time, dict(incidence), survival))
        risk -= terminal + counts["censored"]
    result = {}
    for horizon in horizons:
        causes, remaining = {"closed": 0.0, "cancelled": 0.0, "expired": 0.0}, 1.0
        for time, values, survival in snapshots:
            if time > horizon:
                break
            causes, remaining = values, survival
        result[str(horizon)] = {**causes, "still_open": remaining}
    return result


def _encoding(rows: list[dict]) -> list[dict]:
    candidates = sorted({key for row in rows for key in row["features"]})
    encoding = []
    for key in candidates:
        present = [row["features"][key] for row in rows if key in row["features"]]
        if len(present) < max(3, len(rows) * 0.6):
            continue
        numbers = [_number(value) for value in present]
        if all(value is not None for value in numbers):
            if len(encoding) >= 24:
                continue
            mean = statistics.mean(numbers)
            scale = statistics.pstdev(numbers) or 1.0
            encoding.append({"key": key, "type": "numeric", "mean": mean, "scale": scale, "min": min(numbers), "max": max(numbers)})
        else:
            categories = sorted({str(value) for value in present})
            if 1 < len(categories) <= 12 and len(encoding) < 24:
                encoding.append({"key": key, "type": "categorical", "categories": categories})
    return encoding


def _vector(features: dict, encoding: list[dict]) -> list[float]:
    result = [1.0]
    for field in encoding:
        value = features.get(field["key"])
        if field["type"] == "numeric":
            number = _number(value)
            result.append(((number if number is not None else field["mean"]) - field["mean"]) / field["scale"])
        else:
            # One category is a reference level to avoid duplicate intercepts.
            result.extend(float(str(value) == category) for category in field["categories"][1:])
    return result


def _solve(matrix: list[list[float]], targets: list[float]) -> list[float]:
    augmented = [row[:] + [target] for row, target in zip(matrix, targets)]
    size = len(targets)
    for index in range(size):
        pivot = max(range(index, size), key=lambda row: abs(augmented[row][index]))
        augmented[index], augmented[pivot] = augmented[pivot], augmented[index]
        divisor = augmented[index][index]
        if abs(divisor) < 1e-12:
            divisor = 1e-12
        augmented[index] = [value / divisor for value in augmented[index]]
        for row in range(size):
            if row == index:
                continue
            factor = augmented[row][index]
            augmented[row] = [value - factor * other for value, other in zip(augmented[row], augmented[index])]
    return [row[-1] for row in augmented]


def _ridge(rows: list[dict], encoding: list[dict], target="label") -> list[float]:
    vectors = [_vector(row["features"], encoding) for row in rows]
    size = len(vectors[0])
    matrix = [[sum(vector[i] * vector[j] for vector in vectors) + (0.01 if i == j and i else 0.0) for j in range(size)] for i in range(size)]
    values = [sum(vector[i] * row[target] for vector, row in zip(vectors, rows)) for i in range(size)]
    return _solve(matrix, values)


def _dot(weights: list[float], vector: list[float]) -> float:
    return sum(weight * value for weight, value in zip(weights, vector))


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-min(value, 700)))
    exponential = math.exp(max(value, -700))
    return exponential / (1.0 + exponential)


def _logistic(rows: list[dict], encoding: list[dict]) -> list[float]:
    vectors = [_vector(row["features"], encoding) for row in rows]
    rate = statistics.mean(row["label"] for row in rows)
    weights = [math.log(max(rate, 1e-6) / max(1 - rate, 1e-6))] + [0.0] * (len(vectors[0]) - 1)
    for _ in range(1200):
        residuals = [_sigmoid(_dot(weights, vector)) - row["label"] for vector, row in zip(vectors, rows)]
        gradient = [sum(error * vector[index] for error, vector in zip(residuals, vectors)) / len(rows) + (0.01 * weight if index else 0.0) for index, weight in enumerate(weights)]
        weights = [weight - 0.08 * delta for weight, delta in zip(weights, gradient)]
    return weights


def _calibration(pairs: list[tuple[float, float]]) -> float:
    bins = defaultdict(list)
    for prediction, target in pairs:
        bins[min(4, int(prediction * 5))].append((prediction, target))
    return sum(len(group) / len(pairs) * abs(statistics.mean(pair[0] for pair in group) - statistics.mean(pair[1] for pair in group)) for group in bins.values()) if pairs else 1.0


def _cash_stats(values: list[float]) -> dict:
    return {"median_days": statistics.median(values), "p10_days": _quantile(values, .1), "p90_days": _quantile(values, .9), "support": len(values), "ecdf": [{"days": value, "probability": sum(other <= value for other in values) / len(values)} for value in sorted(set(values))]}


def _temporally_verified(metadata: dict) -> bool:
    validation = metadata.get("validation", {})
    split = validation.get("split", {})
    cutoff, available = split.get("training_cutoff"), split.get("train_max_label_available_at")
    return bool(validation.get("label_availability", {}).get("verified") and cutoff and available and available <= cutoff)


def _choose_group(features: dict, groups: dict, key: str | None) -> dict | None:
    return groups.get(str(features.get(key))) if key else None


def _prediction(model: dict, features: dict) -> dict:
    kind = model["kind"]
    if kind in {"valuation", "repairs"}:
        value = max(0.0, _dot(model["weights"], _vector(features, model["encoding"])))
        radius = model["radius"]
        interval = {"lower": max(0.0, value - radius), "upper": value + radius, "confidence": .8}
        if kind == "repairs":
            return {"estimated_cost": value, "interval": interval, "support": model["support"]}
        arv = max(0.0, _dot(model["arv_weights"], _vector(features, model["encoding"]))) if model.get("arv_weights") else None
        return {"as_is_value": value, "arv": arv, "interval": interval, "support": model["support"]}
    if kind == "acceptance":
        probability = _sigmoid(_dot(model["weights"], _vector(features, model["encoding"])))
        radius = model["probability_radius"]
        return {"probability": probability, "interval": {"lower": max(0.0, probability - radius), "upper": min(1.0, probability + radius), "confidence": .8}, "support": model["support"], "offered_price": features.get(model["offer_field"]), "causal": False}
    if kind == "closing":
        group = _choose_group(features, model["groups"], model.get("group_key"))
        probabilities = (group or model)["probabilities"]
        support = (group or model)["support"]
        intervals = {}
        for horizon, causes in probabilities.items():
            intervals[horizon] = {}
            for cause, probability in causes.items():
                radius = max(.05, 1.282 * math.sqrt(max(probability * (1 - probability), .01) / max(support, 1)))
                intervals[horizon][cause] = {"lower": max(0.0, probability - radius), "upper": min(1.0, probability + radius)}
        return {"probabilities": probabilities, "intervals": intervals, "interval_method": "Approximate binomial support bands, not formal competing-risk confidence bounds", "support": support, "stage_conditioned": bool(group), **{f"close_by_{horizon}_days": probabilities[str(horizon)]["closed"] for horizon in HORIZONS}}
    group = _choose_group(features, model["groups"], model.get("group_key"))
    stats = (group or model)["statistics"]
    return {**stats, "reference": "closing_to_cash", "conditioned": bool(group)}


def _metric(kind: str, model: dict, rows: list[dict], baseline: Any) -> dict:
    if kind in {"valuation", "repairs", "cash"}:
        pairs = []
        coverage = []
        key = {"valuation": "as_is_value", "repairs": "estimated_cost", "cash": "median_days"}[kind]
        for row in rows:
            predicted = _prediction(model, row["features"])
            pairs.append((predicted[key], row["label"]))
            if "interval" in predicted:
                coverage.append(predicted["interval"]["lower"] <= row["label"] <= predicted["interval"]["upper"])
        mae = statistics.mean(abs(prediction - target) for prediction, target in pairs)
        base = statistics.mean(abs(baseline - row["label"]) for row in rows)
        return {"mae": mae, "baseline_mae": base, "improvement": base - mae, "interval_coverage": statistics.mean(coverage) if coverage else None, "scored": len(pairs)}
    pairs, baseline_errors = [], []
    for row in rows:
        prediction = _prediction(model, row["features"])
        if kind == "acceptance":
            pairs.append((prediction["probability"], row["label"]))
            baseline_errors.append((baseline - row["label"]) ** 2)
        else:
            label = row["label"]
            for horizon in HORIZONS:
                if label["event"] == "censored" and label["duration"] < horizon:
                    continue
                target = float(label["event"] == "closed" and label["duration"] <= horizon)
                pairs.append((prediction["probabilities"][str(horizon)]["closed"], target))
                baseline_errors.append((baseline - target) ** 2)
    brier = statistics.mean((prediction - target) ** 2 for prediction, target in pairs) if pairs else None
    base = statistics.mean(baseline_errors) if baseline_errors else None
    return {"brier": brier, "baseline_brier": base, "improvement": base - brier if base is not None else None, "calibration_error": _calibration(pairs), "scored": len(pairs)}


class ModelRegistry:
    """Immutable model versions with atomic activation and an append-only audit."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.versions = self.path / "versions"
        self.versions.mkdir(parents=True, exist_ok=True)
        self.active_path = self.path / "active.json"
        self.audit_path = self.path / "audit.ndjson"

    def _active(self) -> dict:
        if not self.active_path.exists():
            return {}
        return json.loads(self.active_path.read_text())

    def _artifact(self, model_id: str) -> dict:
        if not re.fullmatch(r"(valuation|repairs|acceptance|closing|cash)-[a-f0-9]{24}", str(model_id)):
            raise ValueError("Invalid model ID")
        target = self.versions / (model_id + ".json")
        if not target.exists():
            raise ValueError("Unknown model version")
        artifact = json.loads(target.read_text())
        expected = hashlib.sha256(_json(artifact["dataset"]).encode()).hexdigest()
        if expected != artifact["metadata"]["dataset_fingerprint"]:
            raise ValueError("Model artifact dataset integrity check failed")
        if artifact["metadata"]["model_id"] != model_id or model_id != artifact["metadata"]["kind"] + "-" + expected[:24]:
            raise ValueError("Model version identity check failed")
        if artifact.get("artifact_sha256"):
            payload = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
            if hashlib.sha256(_json(payload).encode()).hexdigest() != artifact["artifact_sha256"]:
                raise ValueError("Model artifact integrity check failed")
        return artifact

    def _atomic(self, target: Path, value: dict) -> None:
        temporary = target.with_name(target.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            with temporary.open("w") as output:
                output.write(_json(value) + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _audit(self, action: str, **details) -> None:
        with self.audit_path.open("a") as output:
            output.write(_json({"at": _now(), "action": action, **details}) + "\n")
            output.flush()
            os.fsync(output.fileno())

    def _clean(self, kind: str, rows: list[dict]) -> tuple[list[dict], int, bool]:
        clean = []
        any_synthetic = False
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            any_synthetic = any_synthetic or bool(row.get("synthetic"))
            decision = _time(row.get("decision_at") or row.get("observed_at"))
            if decision is None:
                continue
            availability = []
            explicit_availability = []
            invalid_availability = False
            explicit_label_availability = False
            for field in ("label_available_at", "available_at", "outcome_at"):
                if row.get(field) is not None:
                    timestamp = _time(row[field])
                    if timestamp is None:
                        invalid_availability = True
                    else:
                        availability.append(timestamp)
                        if field in ("label_available_at", "available_at"):
                            explicit_label_availability = True
                            explicit_availability.append(timestamp)
            if invalid_availability:
                continue
            label_available_at = max(availability) if availability else None
            if label_available_at is not None and label_available_at < decision:
                # A target preceding its prediction is not a prospective label.
                continue
            identity = row.get("property_id") or row.get("episode_id")
            if identity is None or not str(identity).strip() or not isinstance(row.get("features"), dict):
                continue
            available = _time(row.get("features_available_at"))
            if row.get("features_available_at") is not None and available is None:
                continue
            if available and available > decision:
                continue
            label = row.get("label")
            arv = None
            if kind == "closing":
                if not isinstance(label, dict):
                    label = {"duration": row.get("duration"), "event": row.get("event")}
                duration, event = _number(label.get("duration")), _event(label)
                if duration is None or duration < 0 or duration > 36500 or event is None:
                    continue
                label = {"duration": duration, "event": event}
                try:
                    inferred_occurrence = (datetime.fromisoformat(decision) + timedelta(days=duration)).isoformat()
                except OverflowError:
                    continue
                # A duration itself establishes a lower bound on when this
                # terminal event/censoring snapshot could have been observed.
                occurrence = max(inferred_occurrence, _time(row.get("outcome_at")) or inferred_occurrence)
                label_available_at = max(label_available_at or occurrence, occurrence)
                if not explicit_availability or max(explicit_availability) < occurrence:
                    explicit_label_availability = False
            else:
                if isinstance(label, dict):
                    if kind == "valuation":
                        arv = _number(label.get("arv"))
                        label = label.get("as_is_value", label.get("sale_value", label.get("value")))
                    elif kind == "repairs":
                        label = label.get("actual_repairs", label.get("cost"))
                    elif kind == "cash":
                        label = label.get("cash_delay", label.get("close_to_cash"))
                    else:
                        label = label.get("accepted")
                label = _number(label)
                if label is None or label < 0 or (kind == "acceptance" and label not in (0.0, 1.0)):
                    continue
            property_id = str(identity)
            row_id = str(row.get("row_id") or row.get("decision_id") or row.get("episode_id") or f"{property_id}:{decision}:{index}")
            occurrence = _time(row.get("outcome_at"))
            if occurrence and explicit_availability and max(explicit_availability) < occurrence:
                explicit_label_availability = False
            item = {"row_id": row_id, "property_id": property_id, "decision_at": decision, "label_available_at": label_available_at, "label_availability_verified": explicit_label_availability, "label_availability_source": "explicit" if explicit_label_availability else "outcome_or_duration_inferred" if label_available_at else "missing", "outcome_at": occurrence, "features_available_at": available, "features_availability_verified": available is not None, "features": _safe_features(row.get("features"), decision), "label": label}
            if arv is not None and arv >= 0:
                item["arv"] = arv
            clean.append(item)
        clean.sort(key=lambda row: (row["decision_at"], row["property_id"], row["row_id"]))
        unique = {}
        for row in clean:
            unique[row["row_id"]] = row
        ordered = sorted(unique.values(), key=lambda row: (row["decision_at"], row["property_id"], row["row_id"]))
        return ordered, len(rows) - len(unique), any_synthetic

    def train(self, kind: str, rows: list[dict], synthetic: bool = False) -> dict:
        kind = ALIASES.get(kind, kind)
        if kind not in KINDS:
            raise ValueError("Unknown model kind")
        if not isinstance(rows, list) or len(rows) > 100000:
            raise ValueError("Training expects a list of at most 100000 observed rows")
        if not isinstance(synthetic, bool):
            raise ValueError("synthetic must be a JSON boolean")
        clean, excluded, row_synthetic = self._clean(kind, rows)
        synthetic = bool(synthetic or row_synthetic)
        dataset = {"kind": kind, "rows": clean, "synthetic": synthetic, "version": VERSION}
        fingerprint = hashlib.sha256(_json(dataset).encode()).hexdigest()
        model_id = kind + "-" + fingerprint[:24]
        target = self.versions / (model_id + ".json")
        with _LOCK:
            if target.exists():
                return self._artifact(model_id)["metadata"]
            holdout_count = max(5, math.ceil(len(clean) * .25))
            boundary = clean[-holdout_count]["decision_at"] if len(clean) > holdout_count else ""
            validation = [row for row in clean if boundary and row["decision_at"] >= boundary]
            held_properties = {row["property_id"] for row in validation}
            early_rows = [row for row in clean if boundary and row["decision_at"] < boundary and row["property_id"] not in held_properties]
            purged = [row for row in early_rows if row["label_available_at"] is not None and row["label_available_at"] > boundary]
            training = [row for row in early_rows if row["label_available_at"] is None or row["label_available_at"] <= boundary]
            unverified = sum(not row["label_availability_verified"] for row in training + validation)
            limits = ["Observational historical fit; predictions do not establish causal effects of changing an offer or intervention.", "Only supplied decision snapshots are used; source reliability and decision-time availability must be verified by the ledger."]
            if unverified:
                limits.append("Outcome availability is unverified for some fitted/evaluated rows; this candidate is exploratory and cannot be promoted as a temporal validation.")
            if purged:
                limits.append("Earlier-decision rows with outcome/censoring labels unavailable at the holdout cutoff were purged from training.")
            if synthetic:
                limits.append("Synthetic reference data cannot establish operating performance or be promoted.")
            split = {"train_property_ids": sorted({row["property_id"] for row in training}), "validation_property_ids": sorted(held_properties), "train_row_ids": [row["row_id"] for row in training], "validation_row_ids": [row["row_id"] for row in validation], "train_max_timestamp": max((row["decision_at"] for row in training), default=None), "validation_min_timestamp": min((row["decision_at"] for row in validation), default=None), "training_cutoff": boundary or None, "train_max_label_available_at": max((row["label_available_at"] for row in training if row["label_available_at"] is not None), default=None), "purged_row_ids": [row["row_id"] for row in purged]}
            metadata = {"model_id": model_id, "kind": kind, "status": "candidate", "created_at": _now(), "version": VERSION, "synthetic": synthetic, "dataset_fingerprint": fingerprint, "support": {"total": len(rows), "usable": len(clean), "train": len(training), "validation": len(validation), "excluded": excluded + len(clean) - len(training) - len(validation), "purged_label_availability": len(purged), "availability_unverified": unverified}, "features": [], "training_window": {"start": min((row["decision_at"] for row in training), default=None), "end": split["train_max_timestamp"], "labels_available_by": boundary or None}, "validation": {"split": split, "metrics": {}, "label_availability": {"verified": unverified == 0, "unverified_rows": unverified, "purged_rows": len(purged), "policy": "Training labels and censoring snapshots must have been available no later than the first held-out decision."}}, "gate": {"eligible": False, "reason": "Insufficient chronological support"}, "limitations": limits}
            model = None
            reason = None
            if len(clean) < MIN_SUPPORT or len(training) < 12 or len(validation) < 5:
                reason = "Requires at least 20 observed labels, 12 earlier training rows, and 5 later property-disjoint validation rows"
            else:
                model, reason = self._fit(kind, training, validation, metadata)
            if model is not None:
                metadata["features"] = [field["key"] for field in model.get("encoding", [])]
                if kind == "closing" and model.get("group_key"):
                    metadata["features"] = [model["group_key"]]
                if kind == "cash" and model.get("group_key"):
                    metadata["features"] = [model["group_key"]]
                metrics = metadata["validation"]["metrics"]
                measure = "mae" if kind in {"valuation", "repairs", "cash"} else "brier"
                baseline = metrics.get("baseline_" + measure)
                improvement = metrics.get("improvement")
                good = improvement is not None and baseline is not None and improvement > max(1e-8, baseline * .01)
                calibrated = (metrics.get("calibration_error", 0) <= .25 and (metrics.get("interval_coverage") is None or metrics["interval_coverage"] >= .6))
                eligible = good and calibrated and not synthetic and not unverified and reason is None
                metadata["gate"] = {"eligible": eligible, "reason": reason or ("Synthetic data cannot be promoted" if synthetic else "Outcome availability is unverified; prospective holdout validity is unestablished" if unverified else "Measured holdout improvement and calibration passed" if eligible else "Candidate did not improve the baseline by 1% with adequate calibration"), "minimum_relative_improvement": .01, "calibration_threshold": .25, "baseline": measure, "temporal_availability_verified": unverified == 0}
            else:
                metadata["gate"]["reason"] = reason
            artifact = {"metadata": metadata, "model": model, "dataset": dataset, "validation_rows": validation}
            artifact["artifact_sha256"] = hashlib.sha256(_json(artifact).encode()).hexdigest()
            self._atomic(target, artifact)
            self._audit("train", model_id=model_id, kind=kind, eligible=metadata["gate"]["eligible"], dataset_fingerprint=fingerprint)
            return metadata

    def _fit(self, kind: str, training: list[dict], validation: list[dict], metadata: dict) -> tuple[dict | None, str | None]:
        model = {"kind": kind, "support": len(training), "known_counties": sorted({str(row["features"]["county_fips"]) for row in training if "county_fips" in row["features"]})}
        if kind in {"valuation", "repairs"}:
            calibration_count = max(3, len(training) // 5)
            fit, calibration = training[:-calibration_count], training[-calibration_count:]
            encoding = _encoding(fit)
            if not encoding:
                return None, "No supported non-leaking decision features for regression"
            weights = _ridge(fit, encoding)
            residuals = [abs(_dot(weights, _vector(row["features"], encoding)) - row["label"]) for row in calibration]
            model.update({"encoding": encoding, "weights": weights, "radius": max(_quantile(residuals, .8), statistics.mean(row["label"] for row in fit) * .02), "calibration_support": len(calibration)})
            baseline = statistics.median(row["label"] for row in training)
            metadata["validation"]["metrics"] = _metric(kind, model, validation, baseline)
            metadata["validation"]["interval_method"] = "80th percentile of earlier calibration absolute residuals with a 2% label-scale uncertainty floor"
            if kind == "valuation":
                arv_fit = [dict(row, label=row["arv"]) for row in fit if "arv" in row]
                arv_validation = [dict(row, label=row["arv"]) for row in validation if "arv" in row]
                if len(arv_fit) >= 12 and len(arv_validation) >= 5:
                    arv_weights = _ridge(arv_fit, encoding)
                    arv_mae = statistics.mean(abs(_dot(arv_weights, _vector(row["features"], encoding)) - row["label"]) for row in arv_validation)
                    arv_baseline = statistics.median(row["label"] for row in arv_fit)
                    baseline_mae = statistics.mean(abs(arv_baseline - row["label"]) for row in arv_validation)
                    metadata["validation"]["arv_metrics"] = {"mae": arv_mae, "baseline_mae": baseline_mae}
                    if arv_mae < baseline_mae * .99:
                        model["arv_weights"] = arv_weights
                if not model.get("arv_weights"):
                    metadata["limitations"].append("ARV is unavailable: separately verified after-repair labels have not passed their own holdout comparison.")
        elif kind == "acceptance":
            classes = Counter(row["label"] for row in training)
            validation_classes = Counter(row["label"] for row in validation)
            offer_field = next((key for key in ("offered_price", "offer_price", "offered_amount") if sum(_number(row["features"].get(key)) is not None for row in training) >= len(training) * .9), None)
            if not offer_field or min(classes.get(0.0, 0), classes.get(1.0, 0)) < 3 or min(validation_classes.get(0.0, 0), validation_classes.get(1.0, 0)) < 2:
                return None, "Acceptance requires recorded offered price and at least 3 observations of each training class and 2 of each later validation class"
            encoding = _encoding(training)
            weights = _logistic(training, encoding)
            probability_radius = max(.05, 1.282 * math.sqrt(.25 / len(training)))
            prices = [_number(row["features"].get(offer_field)) for row in training]
            prices = [price for price in prices if price is not None]
            model.update({"encoding": encoding, "weights": weights, "offer_field": offer_field, "price_range": [min(prices), max(prices)], "probability_radius": probability_radius})
            metadata["validation"]["metrics"] = _metric(kind, model, validation, statistics.mean(row["label"] for row in training))
            metadata["limitations"].append("Acceptance estimates describe observed price/context associations; unobserved counteroffers are not identified counterfactuals. Prices outside observed support are refused.")
        elif kind == "closing":
            events = Counter(row["label"]["event"] for row in training)
            if events["closed"] < 5 or events["cancelled"] + events["expired"] < 3:
                return None, "Closing requires at least 5 funded closings and 3 competing terminal outcomes in the earlier training set"
            probabilities = aalen_johansen(row["label"] for row in training)
            groups = defaultdict(list)
            for row in training:
                if "stage" in row["features"]:
                    groups[str(row["features"]["stage"])].append(row["label"])
            model.update({"probabilities": probabilities, "group_key": "stage" if groups else None, "groups": {key: {"probabilities": aalen_johansen(labels), "support": len(labels)} for key, labels in groups.items() if len(labels) >= 20}})
            baseline = events["closed"] / len(training)
            metadata["validation"]["metrics"] = _metric(kind, model, validation, baseline)
            metadata["validation"]["cumulative_incidence"] = probabilities
            metadata["validation"]["estimator"] = {"name": "aalen-johansen", "censored": events["censored"], "events": dict(events)}
            metadata["limitations"].append("Empirical competing risks rely on independent censoring and comparable stage cohorts. New or small stage cohorts use a global, explicitly unconditioned estimate.")
        else:
            statistics_global = _cash_stats([row["label"] for row in training])
            group_key, groups = None, {}
            for candidate in ("partner_id", "state", "county_fips"):
                cohorts = defaultdict(list)
                for row in training:
                    if candidate in row["features"]:
                        cohorts[str(row["features"][candidate])].append(row["label"])
                supported = {key: {"statistics": _cash_stats(values)} for key, values in cohorts.items() if len(values) >= 10}
                if len(supported) >= 2:
                    group_key, groups = candidate, supported
                    break
            model.update({"statistics": statistics_global, "group_key": group_key, "groups": groups})
            metadata["validation"]["metrics"] = _metric(kind, model, validation, statistics_global["median_days"])
            metadata["limitations"].append("Cash timing is an empirical distribution of observed closing-to-cash receipt delays; incomplete cash episodes are excluded and can cause selection bias.")
        return model, None

    def status(self) -> dict:
        with _LOCK:
            active = self._active()
            promoted = set()
            if self.audit_path.exists():
                for line in self.audit_path.read_text().splitlines():
                    try:
                        event = json.loads(line)
                        if event.get("action") in {"promote", "rollback"}:
                            promoted.add(event.get("model_id"))
                    except ValueError:
                        continue
            models = []
            for target in sorted(self.versions.glob("*.json")):
                metadata = self._artifact(target.stem)["metadata"]
                metadata["status"] = "active" if active.get(metadata["kind"]) == metadata["model_id"] else "inactive" if metadata["model_id"] in promoted else "candidate"
                models.append(metadata)
            return {"models": models, "active": active}

    def promote(self, model_id: str) -> dict:
        with _LOCK:
            artifact = self._artifact(model_id)
            metadata, model = artifact["metadata"], artifact["model"]
            if not _temporally_verified(metadata):
                raise ValueError("Promotion rejected: verified prospective outcome availability is required")
            if not metadata["gate"]["eligible"] or metadata["synthetic"] or model is None:
                raise ValueError("Promotion rejected: " + metadata["gate"]["reason"])
            active = self._active()
            kind = metadata["kind"]
            previous = active.get(kind)
            if previous == model_id:
                return {**metadata, "status": "active"}
            if previous:
                incumbent = self._artifact(previous)
                candidate_cutoff = metadata["validation"]["split"]["training_cutoff"]
                incumbent_split = incumbent["metadata"]["validation"]["split"]
                if (incumbent_split.get("train_max_label_available_at") or incumbent_split.get("train_max_timestamp") or "") > candidate_cutoff:
                    raise ValueError("Promotion rejected: active model learned information unavailable at the candidate holdout cutoff")
                overlap = set(incumbent["metadata"]["validation"]["split"]["train_row_ids"]) & set(metadata["validation"]["split"]["validation_row_ids"])
                if overlap:
                    raise ValueError("Promotion rejected: incumbent has already trained on candidate validation observations")
                rows = artifact["validation_rows"]
                scalar_key = {"valuation": "as_is_value", "repairs": "estimated_cost", "cash": "median_days"}.get(kind)
                if scalar_key:
                    incumbent_error = statistics.mean(abs(_prediction(incumbent["model"], row["features"])[scalar_key] - row["label"]) for row in rows)
                    candidate_error = metadata["validation"]["metrics"]["mae"]
                else:
                    pairs = []
                    for row in rows:
                        prediction = _prediction(incumbent["model"], row["features"])
                        if kind == "acceptance":
                            pairs.append((prediction["probability"], row["label"]))
                        else:
                            for horizon in HORIZONS:
                                label = row["label"]
                                if label["event"] == "censored" and label["duration"] < horizon:
                                    continue
                                pairs.append((prediction["probabilities"][str(horizon)]["closed"], float(label["event"] == "closed" and label["duration"] <= horizon)))
                    incumbent_error = statistics.mean((prediction - target) ** 2 for prediction, target in pairs)
                    candidate_error = metadata["validation"]["metrics"]["brier"]
                if candidate_error >= incumbent_error * .99 - 1e-8:
                    raise ValueError("Promotion rejected: candidate did not improve the active model's later-observation error by 1%")
            self._atomic(self.active_path, {**active, kind: model_id})
            self._audit("promote", kind=kind, model_id=model_id, previous=previous)
            return {**metadata, "status": "active"}

    def rollback(self, kind: str, model_id: str) -> dict:
        kind = ALIASES.get(kind, kind)
        with _LOCK:
            artifact = self._artifact(model_id)
            metadata = artifact["metadata"]
            if metadata["kind"] != kind or metadata["synthetic"] or not metadata["gate"]["eligible"] or not _temporally_verified(metadata):
                raise ValueError("Rollback target must be a validated version of the same kind")
            previously_active = False
            if self.audit_path.exists():
                previously_active = any(event.get("action") in {"promote", "rollback"} and event.get("model_id") == model_id for event in (json.loads(line) for line in self.audit_path.read_text().splitlines() if line.strip()))
            if not previously_active:
                raise ValueError("Rollback target has never been approved for activation")
            active = self._active()
            self._atomic(self.active_path, {**active, kind: model_id})
            self._audit("rollback", kind=kind, model_id=model_id, previous=active.get(kind))
            return {**metadata, "status": "active"}

    def predict(self, kind: str, features: dict) -> dict:
        kind = ALIASES.get(kind, kind)
        if kind not in KINDS:
            raise ValueError("Unknown model kind")
        with _LOCK:
            model_id = self._active().get(kind)
            if not model_id:
                return {"status": "untrained", "model_id": None, "synthetic": False, "limitations": ["No promoted model trained and validated on historical internal outcomes; no probability or model estimate is available."], "prediction": None}
            artifact = self._artifact(model_id)
            model, metadata = artifact["model"], artifact["metadata"]
            limits = list(metadata["limitations"])
            if not _temporally_verified(metadata):
                return {"status": "insufficient_support", "model_id": model_id, "synthetic": metadata["synthetic"], "limitations": limits + ["This stored version lacks verified prospective outcome availability; retraining is required before operational predictions."], "prediction": None}
            safe = _safe_features(features, _now())
            if kind == "acceptance":
                price = _number(safe.get(model["offer_field"]))
                if price is None or not model["price_range"][0] <= price <= model["price_range"][1]:
                    return {"status": "insufficient_support", "model_id": model_id, "synthetic": metadata["synthetic"], "limitations": limits + ["Offered price is missing or outside observed training support; extrapolated acceptance is refused."], "prediction": None}
            prediction = _prediction(model, safe)
            out_of_support = False
            for field in model.get("encoding", []):
                value = safe.get(field["key"])
                if field["type"] == "numeric":
                    number = _number(value)
                    out_of_support |= number is None or number < field["min"] or number > field["max"]
                else:
                    out_of_support |= str(value) not in field["categories"]
            if kind in {"valuation", "repairs"}:
                if not model["known_counties"]:
                    limits.append("County-specific performance is unestablished; this model has no verified geographic cohort in its supplied features.")
                    out_of_support = True
                elif str(safe.get("county_fips")) not in model["known_counties"]:
                    limits.append("This county is unseen or unspecified; local validation is unavailable.")
                    out_of_support = True
            if out_of_support:
                limits.append("Some context is missing or outside observed feature support; uncertainty is widened and local accuracy is unestablished.")
                if kind in {"valuation", "repairs"}:
                    key = "as_is_value" if kind == "valuation" else "estimated_cost"
                    value = prediction[key]
                    radius = model["radius"] * 1.5
                    prediction["interval"] = {"lower": max(0.0, value - radius), "upper": value + radius, "confidence": .8}
            if kind == "closing" and model.get("group_key") and not prediction["stage_conditioned"]:
                limits.append("Requested stage has fewer than 20 observations or is unseen; the forecast is global rather than stage-conditioned.")
            if kind == "cash" and model.get("group_key") and not prediction["conditioned"]:
                limits.append("Requested partner/market lacks 10 observed cash receipts; the forecast uses the global empirical distribution.")
            return {"status": "ready", "model_id": model_id, "synthetic": metadata["synthetic"], "limitations": limits, "prediction": prediction}
