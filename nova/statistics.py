"""Deterministic statistics for the NOVA-MAT minimal screen."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np


BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_SEED = 1_729


def _validated_binary(values: Sequence[int], label: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{label} must contain at least one endpoint")
    if not np.isin(array, (0, 1, False, True)).all():
        raise ValueError(f"{label} endpoints must be binary")
    return array.astype(np.int8, copy=False)


def bootstrap_difference(
    oxide: Sequence[int],
    chalcogenide: Sequence[int],
    *,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Return chalcogenide-minus-oxide rate and a group-stratified percentile CI.

    Resampling is with replacement within each family and at the composition
    level. These intervals describe resampling stability in this snapshot; they
    are not population intervals for all real materials.
    """
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates <= 0:
        raise ValueError("replicates must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    oxide_values = _validated_binary(oxide, "oxide")
    chalc_values = _validated_binary(chalcogenide, "chalcogenide")
    observed_delta = float(chalc_values.mean() - oxide_values.mean())
    oxide_seed, chalc_seed = np.random.SeedSequence(seed).spawn(2)
    oxide_rng = np.random.default_rng(oxide_seed)
    chalc_rng = np.random.default_rng(chalc_seed)
    deltas = np.empty(replicates, dtype=np.float64)
    batch_size = max(1, min(64, replicates))
    for start in range(0, replicates, batch_size):
        stop = min(start + batch_size, replicates)
        batch_count = stop - start
        oxide_draws = oxide_rng.integers(0, oxide_values.size, size=(batch_count, oxide_values.size))
        chalc_draws = chalc_rng.integers(0, chalc_values.size, size=(batch_count, chalc_values.size))
        deltas[start:stop] = (
            chalc_values[chalc_draws].mean(axis=1)
            - oxide_values[oxide_draws].mean(axis=1)
        )
    lower, upper = np.quantile(deltas, [0.025, 0.975], method="linear")
    return {
        "delta": observed_delta,
        "resampling_interval": [float(lower), float(upper)],
        "replicates": replicates,
        "seed": seed,
        "interval_method": "family-stratified percentile bootstrap at composition level",
        "bootstrap_degenerate": bool(np.ptp(deltas) == 0.0),
        "family_endpoint_degenerate": {
            "oxide": bool(np.unique(oxide_values).size < 2),
            "chalcogenide": bool(np.unique(chalc_values).size < 2),
        },
    }


def missingness_difference(
    *,
    oxide_total: int,
    oxide_pass: int,
    chalcogenide_total: int,
    chalcogenide_pass: int,
    oxide_observed: int,
    chalcogenide_observed: int,
) -> dict[str, float] | None:
    """Worst-case chalcogenide-minus-oxide bounds using all compositions."""
    counts = (oxide_total, oxide_pass, chalcogenide_total, chalcogenide_pass,
              oxide_observed, chalcogenide_observed)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in counts):
        raise ValueError("counts must be integers")
    if min(counts) < 0:
        raise ValueError("counts cannot be negative")
    if oxide_pass > oxide_observed or chalcogenide_pass > chalcogenide_observed:
        raise ValueError("pass counts cannot exceed observed counts")
    if oxide_observed > oxide_total or chalcogenide_observed > chalcogenide_total:
        raise ValueError("observed counts cannot exceed family totals")
    if oxide_total == 0 or chalcogenide_total == 0:
        return None

    oxide_lower = oxide_pass / oxide_total
    oxide_upper = (oxide_pass + oxide_total - oxide_observed) / oxide_total
    chalc_lower = chalcogenide_pass / chalcogenide_total
    chalc_upper = (chalcogenide_pass + chalcogenide_total - chalcogenide_observed) / chalcogenide_total
    return {
        "lower": chalc_lower - oxide_upper,
        "upper": chalc_upper - oxide_lower,
        "oxide_rate_lower": oxide_lower,
        "oxide_rate_upper": oxide_upper,
        "chalcogenide_rate_lower": chalc_lower,
        "chalcogenide_rate_upper": chalc_upper,
    }
