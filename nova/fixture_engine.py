"""Deterministic, explicitly non-scientific fixture adapter for the NOVA demo.

This module deliberately has no data/network/tool access.  Its records are tiny
in-memory examples used to exercise orchestration and result-shape handling.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import random
from typing import Any, Mapping, Optional, Tuple

MODE = "fixture"
DATASET_SHA256 = "fixture-demo-v1"

_RECORDS = (
    {"jid": "FX-O1", "family": "oxide", "gap": 1.20, "ehull": 0.020},
    {"jid": "FX-O2", "family": "oxide", "gap": 1.55, "ehull": 0.070},
    {"jid": "FX-O3", "family": "oxide", "gap": 1.95, "ehull": 0.010},
    {"jid": "FX-O4", "family": "oxide", "gap": None, "ehull": 0.010},
    {"jid": "FX-S1", "family": "chalcogenide", "gap": 1.30, "ehull": 0.030},
    {"jid": "FX-S2", "family": "chalcogenide", "gap": 1.70, "ehull": 0.080},
    {"jid": "FX-S3", "family": "chalcogenide", "gap": 1.00, "ehull": 0.010},
    {"jid": "FX-S4", "family": "chalcogenide", "gap": None, "ehull": 0.010},
)


@dataclass(frozen=True)
class Result:
    result_id: str
    experiment_id: str
    mode: str
    template: str
    execution_status: str
    scientific_status: Optional[str] = None
    groups_summary: tuple[dict[str, Any], ...] = ()
    delta: Optional[float] = None
    resampling_interval: Optional[Tuple[float, float]] = None
    missingness_interval: Optional[Tuple[float, float]] = None
    points: tuple[dict[str, Any], ...] = ()
    seed: int = 1729
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["groups_summary"] = list(value["groups_summary"])
        value["points"] = list(value["points"])
        return value


def _get(spec: Any, name: str, default: Any = None) -> Any:
    if isinstance(spec, Mapping):
        return spec.get(name, default)
    return getattr(spec, name, default)


def _one(spec: Any, gap_window: Tuple[float, float], ehull_max: float) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for family in ("oxide", "chalcogenide"):
        rows = [r for r in _RECORDS if r["family"] == family]
        observed = [r for r in rows if r["gap"] is not None]
        passing = [r for r in observed if gap_window[0] <= r["gap"] <= gap_window[1] and r["ehull"] <= ehull_max]
        total, n_observed, n_pass = len(rows), len(observed), len(passing)
        groups[family] = {
            "n_total": total, "n_observed": n_observed, "n_pass": n_pass,
            "coverage": n_observed / total, "observed_rate": n_pass / n_observed,
            "missing_lower": n_pass / total, "missing_upper": (n_pass + total - n_observed) / total,
        }
    return groups


def _screen(spec: Any, gap_window: Tuple[float, float], ehull_max: float) -> Tuple[tuple[dict[str, Any], ...], float, Tuple[float, float], Tuple[float, float]]:
    groups = _one(spec, gap_window, ehull_max)
    o, c = groups["oxide"], groups["chalcogenide"]
    delta = c["observed_rate"] - o["observed_rate"]
    missing = (c["missing_lower"] - o["missing_upper"], c["missing_upper"] - o["missing_lower"])
    # A deterministic bootstrap-like interval: fixed seed and fixed records.
    rng = random.Random(int(_get(spec, "seed", 1729)))
    samples = []
    for _ in range(min(int(_get(spec, "bootstrap_repeats", 200)), 200)):
        vals = []
        for family in ("oxide", "chalcogenide"):
            rows = [r for r in _RECORDS if r["family"] == family and r["gap"] is not None]
            draw = [rows[rng.randrange(len(rows))] for _ in rows]
            vals.append(sum(gap_window[0] <= r["gap"] <= gap_window[1] and r["ehull"] <= ehull_max for r in draw) / len(draw))
        samples.append(vals[1] - vals[0])
    samples.sort()
    interval = (samples[max(0, int(len(samples) * .025) - 1)], samples[min(len(samples) - 1, int(len(samples) * .975))])
    return tuple(groups.values()), delta, missing, interval


def execute(spec: Any) -> Result:
    """Execute one fixture spec.  ``mode`` must be omitted or explicitly fixture."""
    mode = _get(spec, "mode", MODE)
    experiment_id = str(_get(spec, "experiment_id", "FIXTURE-001"))
    template = str(_get(spec, "template", "family_screen"))
    seed = int(_get(spec, "seed", 1729))
    if mode != MODE:
        raise ValueError("fixture_engine only accepts mode='fixture'; it cannot run live experiments")
    if template not in {"family_screen", "threshold_sensitivity", "gap_window_sensitivity"}:
        raise ValueError(f"unsupported fixture template: {template}")
    default_gap = tuple(_get(spec, "gap_window_ev", (1.1, 1.8)))
    default_ehull = float(_get(spec, "ehull_max_ev_atom", 0.05))
    points = []
    if template == "threshold_sensitivity":
        for threshold in (0.025, 0.05, 0.10):
            groups, delta, missing, interval = _screen(spec, default_gap, threshold)
            points.append({"ehull_max_ev_atom": threshold, "groups_summary": groups, "delta": delta, "interval": interval, "missingness_interval": missing})
    elif template == "gap_window_sensitivity":
        for window in ((0.9, 1.6), (1.1, 1.8), (1.3, 2.0)):
            groups, delta, missing, interval = _screen(spec, window, default_ehull)
            points.append({"gap_window_ev": window, "groups_summary": groups, "delta": delta, "interval": interval, "missingness_interval": missing})
    groups, delta, missing, interval = _screen(spec, default_gap, default_ehull)
    digest = hashlib.sha256(f"{experiment_id}:{template}:{seed}".encode()).hexdigest()[:12]
    return Result("FIX-" + digest, experiment_id, MODE, template, "completed", groups_summary=groups,
                  delta=delta, resampling_interval=interval, missingness_interval=missing, points=tuple(points), seed=seed)
