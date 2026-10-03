"""Frozen discovery-only sensitivity analysis for the ehull threshold grid."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from nova.data.pipeline import PROJECT_ROOT, _read_prepared_compositions
from nova.experiments import family_screen
from nova.statistics import BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, bootstrap_difference, missingness_difference


THRESHOLD_GRID_EV_ATOM = (0.025, 0.05, 0.10)
PRIMARY_POINT_INDEX = 1
THRESHOLD_PROTOCOL_PATH = PROJECT_ROOT / "docs" / "THRESHOLD_PROTOCOL.json"
THRESHOLD_PROTOCOL_SHA256 = "9dd5cda359722312ebe4cc9087b566eb0849ccd7175ada7587eb5efa7c6624c3"
PARENT_RESULT_PATH = PROJECT_ROOT / "docs" / "results" / "first_family_screen.json"
PARENT_RESULT_SHA256 = "b8d3fd9336d76d3f9e4e6e1468b76396952308b89964c42e6be733ca75fe45ec"

_PROTOCOL_FIELDS = {
    "bandgap_method",
    "bootstrap_repeats",
    "created_at_utc",
    "dataset_sha256",
    "ehull_grid_ev_atom",
    "gap_window_ev",
    "groups",
    "holdout_execution_allowed",
    "limits",
    "parent_protocol_sha256",
    "parent_result_file",
    "parent_result_sha256",
    "primary_ehull_max_ev_atom",
    "protocol_id",
    "registration_context",
    "reporting",
    "representative_compositions_csv_sha256",
    "representative_rule",
    "schema_version",
    "scientific_status_rules",
    "seed",
    "selection_mode",
    "selection_reason",
    "split",
    "split_assignment_sha256",
    "template",
}


def read_metadata() -> dict[str, Any]:
    """Expose counts and coverage only, using the public metadata adapter."""
    return family_screen.read_metadata()


def _canonical_sha(value: Any) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _read_threshold_protocol() -> tuple[dict[str, Any], str]:
    """Read the committed extension registration and enforce its pinned bytes."""
    raw = THRESHOLD_PROTOCOL_PATH.read_bytes()
    protocol_sha256 = hashlib.sha256(raw).hexdigest()
    if protocol_sha256 != THRESHOLD_PROTOCOL_SHA256:
        raise ValueError("Frozen threshold extension protocol hash mismatch")
    try:
        protocol = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Frozen threshold extension protocol is not valid UTF-8 JSON") from error
    if not isinstance(protocol, dict):
        raise ValueError("Frozen threshold extension protocol must be a JSON object")
    return protocol, protocol_sha256


def _verify_parent_result(protocol: dict[str, Any]) -> None:
    """Verify the registered discovery result by bytes without interpreting it."""
    if protocol.get("parent_result_file") != "docs/results/first_family_screen.json":
        raise ValueError("Threshold protocol points at an unsupported parent result artifact")
    raw = PARENT_RESULT_PATH.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != protocol.get("parent_result_sha256") or actual_sha256 != PARENT_RESULT_SHA256:
        raise ValueError("Registered parent discovery result hash mismatch")


def _check_threshold_protocol(
    protocol: dict[str, Any],
    protocol_sha256: str,
    manifest: dict[str, Any],
) -> None:
    if not isinstance(protocol, dict):
        raise TypeError("threshold protocol must be a dictionary")
    if protocol_sha256 != THRESHOLD_PROTOCOL_SHA256:
        raise ValueError("Threshold extension protocol hash is not the frozen registration")
    missing = sorted(_PROTOCOL_FIELDS - set(protocol))
    unknown = sorted(set(protocol) - _PROTOCOL_FIELDS)
    if missing:
        raise ValueError(f"Threshold protocol is missing fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"Unknown threshold protocol fields: {', '.join(unknown)}")

    fixed = {
        "bandgap_method": "opt",
        "bootstrap_repeats": BOOTSTRAP_REPLICATES,
        "ehull_grid_ev_atom": list(THRESHOLD_GRID_EV_ATOM),
        "gap_window_ev": [1.1, 1.8],
        "groups": ["oxide", "chalcogenide"],
        "holdout_execution_allowed": False,
        "parent_result_file": "docs/results/first_family_screen.json",
        "parent_result_sha256": PARENT_RESULT_SHA256,
        "primary_ehull_max_ev_atom": 0.05,
        "protocol_id": "threshold_sensitivity_v1",
        "schema_version": 1,
        "seed": BOOTSTRAP_SEED,
        "split": "discovery",
        "template": "threshold_sensitivity",
    }
    for key, expected in fixed.items():
        if protocol[key] != expected:
            raise ValueError(f"Threshold protocol field {key} differs from its frozen value")

    linked_values = {
        "dataset_sha256": manifest.get("original_download_zip_sha256"),
        "parent_protocol_sha256": manifest.get("protocol_sha256"),
        "representative_compositions_csv_sha256": manifest.get("representative_compositions_csv_sha256"),
        "split_assignment_sha256": manifest.get("split_assignment_sha256"),
    }
    for key, expected in linked_values.items():
        if not isinstance(expected, str) or protocol[key] != expected:
            raise ValueError(f"Threshold protocol {key} does not match the frozen prepared inputs")
    _verify_parent_result(protocol)


def _check_spec(
    spec: dict[str, Any],
    parent_protocol: dict[str, Any],
    extension_protocol: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Validate the template before adapting all base fields through family_screen."""
    if not isinstance(spec, dict):
        raise TypeError("spec must be a dictionary")
    if spec.get("template") != "threshold_sensitivity":
        raise ValueError("template must be exactly 'threshold_sensitivity'")

    adapted = dict(spec)
    adapted["template"] = "family_screen"
    checked = family_screen._check_spec(adapted, parent_protocol, manifest)
    if extension_protocol.get("template") != "threshold_sensitivity":
        raise ValueError("Prepared extension protocol is not threshold_sensitivity")
    return {**checked, "template": "threshold_sensitivity"}


def _group_at_threshold(
    rows: list[dict[str, Any]],
    family: str,
    ehull_limit: float,
) -> tuple[dict[str, Any], list[int]]:
    family_rows = [
        row
        for row in rows
        if row["family"] == family and row["split"] == "discovery" and not family_screen._bool(row["excluded"])
    ]
    n_total = len(family_rows)
    endpoints: list[int] = []
    n_pass = 0
    for row in family_rows:
        gap = family_screen._number(row["opt_gap_ev"])
        ehull = family_screen._number(row["ehull_ev_atom"])
        if gap is None or ehull is None or not family_screen._bool(row["ehull_valid"]):
            continue
        passed = 1.1 <= gap <= 1.8 and ehull <= ehull_limit
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


def _analyze_point(rows: list[dict[str, Any]], ehull_limit: float) -> dict[str, Any]:
    oxide, oxide_endpoints = _group_at_threshold(rows, "oxide", ehull_limit)
    chalc, chalc_endpoints = _group_at_threshold(rows, "chalcogenide", ehull_limit)

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
            "endpoint_has_pass_and_fail": group["n_pass"] > 0 and group["n_pass"] < group["n_observed"],
        }
    size_and_coverage_pass = all(
        quality_flags[family]["minimum_evaluable_count_pass"] and quality_flags[family]["minimum_coverage_pass"]
        for family in ("oxide", "chalcogenide")
    )
    endpoint_non_degenerate = all(
        quality_flags[family]["endpoint_has_pass_and_fail"] for family in ("oxide", "chalcogenide")
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
    else:
        scientific_status = "inconclusive"

    return {
        "groups_summary": {"oxide": oxide, "chalcogenide": chalc},
        "delta": delta,
        "resampling_interval": interval,
        "missingness_interval": missing_interval,
        "quality_flags": quality_flags,
        "bootstrap": bootstrap,
        "scientific_status": scientific_status,
    }


def _delta_direction(delta: float | None) -> str:
    if delta is None:
        return "unavailable"
    if delta > 0.0:
        return "positive"
    if delta < 0.0:
        return "negative"
    return "zero"


def _direction_comparison(points: list[dict[str, Any]]) -> dict[str, Any]:
    directions = [_delta_direction(point["delta"]) for point in points]
    if "unavailable" in directions:
        classification = "unavailable"
    elif "positive" in directions and "negative" in directions:
        classification = "mixed_signs"
    elif all(direction == "positive" for direction in directions):
        classification = "all_positive"
    elif all(direction == "negative" for direction in directions):
        classification = "all_negative"
    elif all(direction == "zero" for direction in directions):
        classification = "all_zero"
    else:
        classification = "includes_zero"
    return {"point_directions": directions, "classification": classification}


def run_experiment(spec: dict[str, Any]) -> dict[str, Any]:
    """Run all preregistered ehull points on discovery representatives only."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    rows, manifest, parent_protocol = _read_prepared_compositions()
    extension_protocol, extension_protocol_sha256 = _read_threshold_protocol()
    _check_threshold_protocol(extension_protocol, extension_protocol_sha256, manifest)
    effective_spec = _check_spec(spec, parent_protocol, extension_protocol, manifest)

    # Filter by split before reading any property values. Every point reuses these same rows.
    discovery_rows = [row for row in rows if row["split"] == "discovery"]
    points = [
        {"threshold_ev_atom": threshold, **_analyze_point(discovery_rows, threshold)}
        for threshold in THRESHOLD_GRID_EV_ATOM
    ]
    primary = points[PRIMARY_POINT_INDEX]
    finished_at = datetime.now(timezone.utc).isoformat()
    elapsed = time.monotonic() - started

    spec_sha256 = _canonical_sha(
        {
            **effective_spec,
            "ehull_grid_ev_atom": list(THRESHOLD_GRID_EV_ATOM),
            "extension_protocol_sha256": extension_protocol_sha256,
        }
    )
    result = {
        "schema_version": 1,
        "template": "threshold_sensitivity",
        "execution_status": "success",
        "scientific_status": primary["scientific_status"],
        "error": None,
        "dataset_sha256": manifest["original_download_zip_sha256"],
        "protocol_sha256": manifest["protocol_sha256"],
        "extension_protocol_sha256": extension_protocol_sha256,
        "spec_sha256": spec_sha256,
        "split": "discovery",
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed,
        "primary_point_index": PRIMARY_POINT_INDEX,
        "primary_threshold_ev_atom": THRESHOLD_GRID_EV_ATOM[PRIMARY_POINT_INDEX],
        "main_point": primary,
        "points": points,
        "delta_direction_comparison": _direction_comparison(points),
        **{
            key: primary[key]
            for key in (
                "groups_summary",
                "delta",
                "resampling_interval",
                "missingness_interval",
                "quality_flags",
                "bootstrap",
            )
        },
        "artifact_ids": [
            "nova-manifest:" + manifest["original_download_zip_sha256"],
            "nova-protocol:" + manifest["protocol_sha256"],
            "nova-compositions-csv:" + manifest["representative_compositions_csv_sha256"],
            "nova-threshold-protocol:" + extension_protocol_sha256,
            "nova-parent-result:" + extension_protocol["parent_result_sha256"],
        ],
        "interpretation_scope": "discovery split; observed representative compositions in the frozen JARVIS snapshot; missingness bounds accompany complete-case rates",
        "contract_status": "provisional plain-dictionary adapter; pending shared B-owned contract integration",
    }
    return result
