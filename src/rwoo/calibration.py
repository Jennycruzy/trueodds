"""Calibration scoring utilities.

These functions are deliberately small and deterministic: given a list of
prediction records with `oracle_prob` and `outcome`, they compute the same
reliability buckets and Brier score every time. No model or LLM participates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Precommitted production transform shared by the weather engine and evidence
# report. One definition prevents silent model/report parameter drift.
WEATHER_V3_CALIBRATION_GAMMA = 0.65
WEATHER_V3_SOURCE_MODEL = "weather-ensemble-v2"


@dataclass(frozen=True)
class CalibrationRecord:
    domain: str
    venue: str
    market_id: str
    question: str
    decision_timestamp: str
    resolution_timestamp: str
    oracle_prob: float
    outcome: int
    bucket: str
    source_run: str
    source_available_at: str
    target_date: str


def probability_bucket(probability: float, width: float = 0.2) -> str:
    idx = min(int(probability / width), int(1 / width) - 1)
    low = idx * width
    high = low + width
    return f"{low:.1f}-{high:.1f}"


def brier_score(records: list[CalibrationRecord]) -> float:
    if not records:
        raise ValueError("cannot score an empty calibration record")
    return sum((r.oracle_prob - r.outcome) ** 2 for r in records) / len(records)


def reliability_curve(records: list[CalibrationRecord], width: float = 0.2) -> list[dict]:
    buckets: dict[str, list[CalibrationRecord]] = {}
    for record in records:
        buckets.setdefault(probability_bucket(record.oracle_prob, width), []).append(record)

    rows = []
    for bucket in sorted(buckets):
        values = buckets[bucket]
        rows.append(
            {
                "bucket": bucket,
                "count": len(values),
                "mean_predicted": sum(r.oracle_prob for r in values) / len(values),
                "actual_hit_rate": sum(r.outcome for r in values) / len(values),
            }
        )
    return rows


def max_calibration_gap(curve: list[dict]) -> float:
    if not curve:
        return 0.0
    return max(abs(row["mean_predicted"] - row["actual_hit_rate"]) for row in curve)


def calibration_breakdown(records: list[CalibrationRecord], width: float = 0.1) -> dict:
    """Report calibration separately by domain and confidence/probability band.

    Probability band is the measurable historical analogue of a confidence
    claim in the current record schema.  Counts remain explicit so a strong
    percentage from a tiny sample cannot masquerade as strong evidence.
    """
    if not records:
        raise ValueError("cannot score an empty calibration record")

    def report(values: list[CalibrationRecord]) -> dict:
        curve = reliability_curve(values, width=width)
        return {
            "count": len(values),
            "brier_score": brier_score(values),
            "max_calibration_gap": max_calibration_gap(curve),
            "reliability": curve,
        }

    domains: dict[str, list[CalibrationRecord]] = {}
    bands: dict[str, list[CalibrationRecord]] = {}
    domain_bands: dict[tuple[str, str], list[CalibrationRecord]] = {}
    for record in records:
        band = probability_bucket(record.oracle_prob, width)
        domains.setdefault(record.domain, []).append(record)
        bands.setdefault(band, []).append(record)
        domain_bands.setdefault((record.domain, band), []).append(record)
    return {
        "overall": report(records),
        "by_domain": {name: report(values) for name, values in sorted(domains.items())},
        "by_probability_band": {name: report(values) for name, values in sorted(bands.items())},
        "by_domain_and_probability_band": {
            f"{domain}:{band}": report(values)
            for (domain, band), values in sorted(domain_bands.items())
        },
        "warning": "band hit rates are evidence only with their displayed sample counts",
    }


def recalibrate_by_bucket(records: list[CalibrationRecord], width: float = 0.2) -> tuple[list[dict], float]:
    """Leave-one-out bucket recalibration.

    For each prediction, use other predictions in the same probability bucket
    to estimate that bucket's empirical hit rate. If there are no peers in the
    bucket, fall back to a neutral 50% prior. This is intentionally reported as
    a demonstration on a tiny seed set, not a production recalibrator.
    """
    if not records:
        raise ValueError("cannot recalibrate an empty calibration record")
    recalibrated_probs = []
    details = []
    for record in records:
        bucket = probability_bucket(record.oracle_prob, width)
        peers = [r for r in records if r is not record and probability_bucket(r.oracle_prob, width) == bucket]
        if peers:
            new_prob = sum(r.outcome for r in peers) / len(peers)
            method = f"leave-one-out empirical hit rate from {len(peers)} peer(s)"
        else:
            new_prob = 0.5
            method = "neutral fallback; no same-bucket peers"
        recalibrated_probs.append((new_prob, record.outcome))
        details.append(
            {
                "market_id": record.market_id,
                "bucket": bucket,
                "original_prob": record.oracle_prob,
                "recalibrated_prob": new_prob,
                "outcome": record.outcome,
                "method": method,
            }
        )
    brier = sum((prob - outcome) ** 2 for prob, outcome in recalibrated_probs) / len(recalibrated_probs)
    return details, brier


def power_transform(probability: float, gamma: float) -> float:
    if probability <= 0.0:
        return 0.0
    if probability >= 1.0:
        return 1.0
    yes_weight = probability ** gamma
    no_weight = (1 - probability) ** gamma
    return yes_weight / (yes_weight + no_weight)


def fit_power_recalibration(records: list[CalibrationRecord]) -> dict:
    """Fit one transparent calibration parameter by grid search.

    gamma > 1 sharpens probabilities away from 50%; gamma < 1 shrinks them
    toward 50%. This is a tiny in-sample seed-set correction for Gate 5 only;
    Phase 6+ must anchor the record, and larger Phase 5 iterations should
    split train/test before treating any transform as production.
    """
    if not records:
        raise ValueError("cannot recalibrate an empty calibration record")
    original_brier = brier_score(records)
    best_gamma = 1.0
    best_brier = original_brier
    for i in range(1, 201):
        gamma = i / 20
        transformed = [(power_transform(r.oracle_prob, gamma), r.outcome) for r in records]
        candidate_brier = sum((prob - outcome) ** 2 for prob, outcome in transformed) / len(transformed)
        if candidate_brier < best_brier:
            best_gamma = gamma
            best_brier = candidate_brier
    details = [
        {
            "market_id": r.market_id,
            "original_prob": r.oracle_prob,
            "recalibrated_prob": power_transform(r.oracle_prob, best_gamma),
            "outcome": r.outcome,
        }
        for r in records
    ]
    return {
        "gamma": best_gamma,
        "original_brier": original_brier,
        "recalibrated_brier": best_brier,
        "improved": best_brier < original_brier,
        "details": details,
    }


def grouped_walk_forward(records: list[CalibrationRecord], min_train_groups: int = 8,
                         min_test_groups: int = 20) -> dict:
    """Walk-forward power calibration with correlated thresholds kept together.

    A group is one source run for one target. Gamma is fitted only on earlier
    groups, then scored on the next group. Reported sample size is independent
    groups, while row count remains visible for auditability.
    """
    groups: dict[tuple[str, str], list[CalibrationRecord]] = {}
    for record in records:
        groups.setdefault((record.source_run, record.target_date), []).append(record)
    ordered = sorted(groups.values(), key=lambda g: datetime.fromisoformat(g[0].decision_timestamp.replace("Z", "+00:00")))
    folds = []
    for index in range(min_train_groups, len(ordered)):
        train = [record for group in ordered[:index] for record in group]
        test = ordered[index]
        fit = fit_power_recalibration(train)
        gamma = fit["gamma"]
        original = sum((r.oracle_prob - r.outcome) ** 2 for r in test) / len(test)
        recalibrated = sum((power_transform(r.oracle_prob, gamma) - r.outcome) ** 2 for r in test) / len(test)
        folds.append({"group": (test[0].source_run, test[0].target_date), "rows": len(test),
                      "gamma": gamma, "original_brier": original, "recalibrated_brier": recalibrated})
    if not folds:
        return {"independent_groups": len(ordered), "rows": len(records), "folds": [], "eligible": False,
                "reason": f"need more than {min_train_groups} independent groups"}
    original = sum(f["original_brier"] for f in folds) / len(folds)
    recalibrated = sum(f["recalibrated_brier"] for f in folds) / len(folds)
    eligible = len(folds) >= min_test_groups
    return {"independent_groups": len(ordered), "rows": len(records), "test_groups": len(folds),
            "original_brier": original, "recalibrated_brier": recalibrated,
            "improved": recalibrated < original, "folds": folds, "eligible": eligible,
            "reason": None if eligible else f"need at least {min_test_groups} walk-forward test groups"}
