"""Minimal real-data family screen. Only discovery results are callable."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nova.data.pipeline import PROJECT_ROOT, _read_json, _read_prepared_compositions
from nova.statistics import BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, bootstrap_difference, missingness_difference


def read_metadata() -> dict[str, Any]:
    """Expose family/split counts and coverage; never expose holdout outcomes."""
    from nova.data.pipeline import read_metadata as _read_metadata

    return _read_metadata()


def _number(value: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _check_spec(spec: dict[str, Any], protocol: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise TypeError("spec must be a dictionary")
    required = {
        "schema_version",
        "template",
        "split",
        "groups",
        "bandgap_method",
        "gap_window_ev",
        "ehull_max_ev_atom",
        "bootstrap_repeats",
        "seed",
        "dataset_sha256",
    }
    optional_metadata = {"experiment_id", "run_id", "hypothesis_id"}
    missing = sorted(required - set(spec))
    unknown = sorted(set(spec) - required - optional_metadata)
    if missing:
        raise ValueError(f"Experiment spec is missing required fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"Unknown family_screen spec fields: {', '.join(unknown)}")
    for key in ("schema_version", "bootstrap_repeats", "seed"):
        if isinstance(spec[key], bool) or not isinstance(spec[key], int):
            raise ValueError(f"{key} must be an integer")
    gap_window = spec["gap_window_ev"]
    if (
        not isinstance(gap_window, list)
        or len(gap_window) != 2
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in gap_window)
    ):
        raise ValueError("gap_window_ev must be a pair of finite numbers")
    ehull_limit = spec["ehull_max_ev_atom"]
    if isinstance(ehull_limit, bool) or not isinstance(ehull_limit, (int, float)) or not math.isfinite(ehull_limit):
        raise ValueError("ehull_max_ev_atom must be a finite number")
    if not isinstance(spec["groups"], list) or spec["groups"] != ["oxide", "chalcogenide"]:
        raise ValueError("groups must be exactly ['oxide', 'chalcogenide']")
    if not isinstance(spec["dataset_sha256"], str):
        raise ValueError("dataset_sha256 must be a string")
    expected = {
        "schema_version": 1,
        "template": "family_screen",
        "split": "discovery",
        "groups": ["oxide", "chalcogenide"],
        "bandgap_method": "opt",
        "gap_window_ev": [1.1, 1.8],
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "dataset_sha256": manifest["original_download_zip_sha256"],
    }
    for key, value in expected.items():
        if spec[key] != value:
            raise ValueError(f"{key} is frozen by the protocol at {value!r}")
    if protocol.get("protocol_id") != "family_screen_v1":
        raise ValueError("Prepared protocol is not the supported family_screen_v1")
    endpoint = protocol["primary_endpoint"]
    if endpoint["opt_gap_ev_inclusive"] != expected["gap_window_ev"]:
        raise ValueError("Frozen band-gap window differs from the implemented template")
    if endpoint["ehull_ev_atom_max_inclusive"] != expected["ehull_max_ev_atom"]:
        raise ValueError("Frozen ehull threshold differs from the implemented template")
    return {key: spec[key] for key in sorted(required)}


def _group(rows: list[dict[str, Any]], family: str) -> tuple[dict[str, Any], list[int]]:
    family_rows = [
        row for row in rows
        if row["family"] == family and row["split"] == "discovery" and not _bool(row["excluded"])
    ]
    n_total = len(family_rows)
    endpoints: list[int] = []
    n_pass = 0
    for row in family_rows:
        gap = _number(row["opt_gap_ev"])
        ehull = _number(row["ehull_ev_atom"])
        if gap is None or ehull is None or not _bool(row["ehull_valid"]):
            continue
        passed = 1.1 <= gap <= 1.8 and ehull <= 0.05
        endpoints.append(int(passed))
        n_pass += int(passed)
    n_observed = len(endpoints)
    return {
        "n_total": n_total,
        "n_observed": n_observed,
        "n_pass": n_pass,
        "coverage": n_observed / n_total if n_total else None,
        "observed_rate": n_pass / n_observed if n_observed else None,
        "missing_lower": n_pass / n_total if n_total else None,
        "missing_upper": (n_pass + n_total - n_observed) / n_total if n_total else None,
    }, endpoints


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_sha(value: Any) -> str:
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def run_experiment(spec: dict[str, Any]) -> dict[str, Any]:
    """Run the frozen family_screen on discovery compositions only.

    Provisional adapter for B's contract integration: takes a plain dictionary
    and returns a plain dictionary. It does not create or modify a registry.
    """
    started = time.monotonic()
    started_at = _utc_now()
    rows, manifest, protocol = _read_prepared_compositions()
    effective_spec = _check_spec(spec, protocol, manifest)
    discovery_rows = [row for row in rows if row["split"] == "discovery"]
    oxide, oxide_endpoints = _group(discovery_rows, "oxide")
    chalc, chalc_endpoints = _group(discovery_rows, "chalcogenide")

    if oxide_endpoints and chalc_endpoints:
        bootstrap = bootstrap_difference(
            oxide_endpoints,
            chalc_endpoints,
            replicates=BOOTSTRAP_REPLICATES,
            seed=BOOTSTRAP_SEED,
        )
        delta = bootstrap["delta"]
        interval = bootstrap["resampling_interval"]
    else:
        bootstrap = None
        delta = None
        interval = None

    quality_flags: dict[str, Any] = {}
    for family, group in (("oxide", oxide), ("chalcogenide", chalc)):
        quality_flags[family] = {
            "minimum_evaluable_count_pass": group["n_observed"] >= 40,
            "minimum_coverage_pass": group["coverage"] is not None and group["coverage"] >= 0.80,
            "endpoint_has_pass_and_fail": (
                group["n_pass"] > 0 and group["n_pass"] < group["n_observed"]
            ),
        }
    size_and_coverage_pass = all(
        quality_flags[family]["minimum_evaluable_count_pass"]
        and quality_flags[family]["minimum_coverage_pass"]
        for family in ("oxide", "chalcogenide")
    )
    endpoint_non_degenerate = all(
        quality_flags[family]["endpoint_has_pass_and_fail"]
        for family in ("oxide", "chalcogenide")
    )
    missing_interval = missingness_difference(
        oxide_total=oxide["n_total"],
        oxide_pass=oxide["n_pass"],
        chalcogenide_total=chalc["n_total"],
        chalcogenide_pass=chalc["n_pass"],
        oxide_observed=oxide["n_observed"],
        chalcogenide_observed=chalc["n_observed"],
    )
    quality_flags["minimum_sample_and_coverage_pass"] = size_and_coverage_pass
    quality_flags["endpoint_non_degenerate"] = endpoint_non_degenerate
    quality_flags["missingness_bounds_cross_zero"] = (
        missing_interval is not None and missing_interval["lower"] <= 0.0 <= missing_interval["upper"]
    )

    if not size_and_coverage_pass:
        scientific_status = "data_limited"
    elif not endpoint_non_degenerate or interval is None or interval[0] <= 0.0 <= interval[1]:
        scientific_status = "inconclusive"
    elif interval[0] > 0.0:
        scientific_status = "supported_in_snapshot"
    elif interval[1] < 0.0:
        scientific_status = "reversed_in_snapshot"
    else:  # Defensive; all interval cases are handled above.
        scientific_status = "inconclusive"

    finished_at = _utc_now()
    elapsed = time.monotonic() - started
    spec_sha = _canonical_sha(effective_spec)
    result = {
        "schema_version": 1,
        "template": "family_screen",
        "execution_status": "success",
        "scientific_status": scientific_status,
        "error": None,
        "dataset_sha256": manifest["original_download_zip_sha256"],
        "protocol_sha256": manifest["protocol_sha256"],
        "spec_sha256": spec_sha,
        "split": "discovery",
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed,
        "groups_summary": {"oxide": oxide, "chalcogenide": chalc},
        "delta": delta,
        "resampling_interval": interval,
        "missingness_interval": missing_interval,
        "quality_flags": quality_flags,
        "bootstrap": bootstrap,
        "artifact_ids": [
            "nova-manifest:" + manifest["original_download_zip_sha256"],
            "nova-protocol:" + manifest["protocol_sha256"],
            "nova-compositions-csv:" + manifest["representative_compositions_csv_sha256"],
        ],
        "interpretation_scope": "observed representative compositions in JARVIS snapshot; missingness bounds accompany complete-case rates",
        "contract_status": "provisional plain-dictionary adapter; pending shared B-owned contract integration",
    }
    return result
