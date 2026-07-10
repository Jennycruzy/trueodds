"""Deterministic, data-backed explanation traces for oracle verdicts."""
from __future__ import annotations

import statistics
from typing import Any


def build_why_trace(engine_result: dict[str, Any]) -> dict[str, Any]:
    models = {
        str(name): float(value)
        for name, value in (engine_result.get("per_model_prob") or {}).items()
        if isinstance(value, (int, float))
    }
    confidence = engine_result.get("confidence")
    low = engine_result.get("prob_low")
    high = engine_result.get("prob_high")
    trace: dict[str, Any] = {
        "method": engine_result.get("method", ""),
        "sources": engine_result.get("per_source_values", {}),
        "model_probabilities": models,
        "confidence": confidence,
        "uncertainty_band": [low, high] if low is not None and high is not None else None,
    }
    if not models:
        trace["summary"] = (
            "No component probability ensemble was exposed; confidence is limited to the "
            "engine's documented source/model path."
        )
        return trace

    values = list(models.values())
    center = statistics.median(values)
    spread = max(values) - min(values)
    furthest_name, furthest_value = max(models.items(), key=lambda item: abs(item[1] - center))
    trace.update(
        {
            "model_count": len(values),
            "median_model_probability": center,
            "model_range": [min(values), max(values)],
            "model_spread": spread,
            "largest_outlier": {"model": furthest_name, "probability": furthest_value},
            "summary": (
                f"{len(values)} deterministic model/source estimates span "
                f"{min(values):.1%}–{max(values):.1%} (median {center:.1%}); "
                f"{furthest_name} is furthest from the median at {furthest_value:.1%}. "
                f"The reported confidence is {confidence:.2f}."
                if isinstance(confidence, (int, float))
                else f"{len(values)} estimates span {min(values):.1%}–{max(values):.1%}."
            ),
        }
    )
    return trace
