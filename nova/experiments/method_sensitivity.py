"""Frozen discovery-only paired OPT/MBJ method sensitivity audit."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from nova.data import pipeline
from nova.statistics import BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, bootstrap_difference


METHOD_PROTOCOL_PATH = pipeline.PROJECT_ROOT / "docs" / "METHOD_AUDIT_PROTOCOL.json"
METHOD_PROTOCOL_SHA256 = "ef09b94e6eebec20974ae4d05647f718471880e44cecb0bbaee55f2c2d050b03"
FAMILIES = ("oxide", "chalcogenide")
METHODS = ("opt", "mbj")
GAP_WINDOW_EV = (1.1, 1.8)
EHULL_MAX_EV_ATOM = 0.05
_CANDIDATE_LABELS = (
    "passes_both_methods",
    "opt_only",
    "mbj_only",
    "opt_pass_mbj_unknown",
    "mbj_pass_opt_unknown",
    "neither_passes",
    "no_current_pass_incomplete_evidence",
    "insufficient_evidence",
)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"{field} must be a boolean or the string 'True'/'False'")


def _read_method_protocol() -> tuple[dict[str, Any], str]:
    """Verify the registered extension bytes before loading prepared outcomes."""
    raw = METHOD_PROTOCOL_PATH.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != METHOD_PROTOCOL_SHA256:
        raise ValueError("Frozen method audit protocol hash mismatch")
    try:
        protocol = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Frozen method audit protocol is not valid UTF-8 JSON") from error
    if not isinstance(protocol, dict):
        raise ValueError("Frozen method audit protocol must be a JSON object")
    _validate_protocol(protocol)
    return protocol, actual_sha256


def _validate_protocol(protocol: dict[str, Any]) -> None:
    if not isinstance(protocol, dict):
        raise TypeError("protocol must be a dictionary")
    fixed = {
        "schema_version": 1,
        "protocol_id": "paired_method_audit_v1",
        "template": "method_sensitivity",
        "split": "discovery",
        "holdout_execution_allowed": False,
        "groups": list(FAMILIES),
        "methods": list(METHODS),
        "gap_window_ev": list(GAP_WINDOW_EV),
        "ehull_max_ev_atom": EHULL_MAX_EV_ATOM,
        "bootstrap_repeats": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "arms": ["opt_all", "opt_paired", "mbj_paired"],
        "candidate_labels": list(_CANDIDATE_LABELS),
    }
    for key, expected in fixed.items():
        if protocol.get(key) != expected:
            raise ValueError(f"Method audit protocol field {key} differs from its frozen value")
    quality = protocol.get("quality")
    if not isinstance(quality, dict):
        raise ValueError("Method audit protocol quality rules are missing")
    quality_fixed = {
        "opt_all_min_observed_per_family": 40,
        "paired_min_observed_per_family": 20,
        "opt_all_min_coverage": 0.8,
        "family_status": (
            "data_limited if sample/coverage gates fail; inconclusive if either endpoint is degenerate "
            "or the interval contains zero; supported_in_snapshot if lower bound > 0; "
            "reversed_in_snapshot if upper bound < 0"
        ),
        "paired_change_status": (
            "data_limited if either paired family has fewer than 20 rows; inconclusive if either family's "
            "paired differences are constant or the interval includes zero; otherwise direction_positive "
            "or direction_negative. These describe method sensitivity, not hypothesis replication."
        ),
    }
    for key, expected in quality_fixed.items():
        if quality.get(key) != expected:
            raise ValueError(f"Method audit protocol quality rule {key} differs from its frozen value")
    if protocol.get("representatives") != (
        "Use the already frozen representative/JID for each reduced composition; never choose a different "
        "structure by method or gap. Filter eligible nonexcluded discovery representatives before inspecting "
        "property values. Reject duplicate JIDs or family/formula keys."
    ):
        raise ValueError("Method audit representative rule differs from its frozen value")
    if protocol.get("pairing") != (
        "A pair is the same representative row/JID with finite OPT, finite MBJ and valid finite ehull. "
        "Never pair by formula across structures, coalesce OPT/MBJ, or impute a missing MBJ."
    ):
        raise ValueError("Method audit pairing rule differs from its frozen value")


def _verify_provenance_links(protocol: dict[str, Any], manifest: dict[str, Any]) -> None:
    linked_values = {
        "dataset_sha256": manifest.get("original_download_zip_sha256"),
        "parent_protocol_sha256": manifest.get("protocol_sha256"),
        "representative_compositions_csv_sha256": manifest.get("representative_compositions_csv_sha256"),
        "split_assignment_sha256": manifest.get("split_assignment_sha256"),
    }
    for key, actual in linked_values.items():
        if not isinstance(actual, str) or protocol.get(key) != actual:
            raise ValueError(f"Method audit protocol {key} does not match the frozen prepared inputs")


def _eligible_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select discovery, nonexcluded representatives using metadata only."""
    eligible: list[dict[str, Any]] = []
    seen_jids: set[str] = set()
    seen_family_formula: set[tuple[str, str]] = set()
    for row in rows:
        # Keep this order: excluded splits never have their remaining fields inspected.
        if row["split"] != "discovery":
            continue
        if _bool(row["excluded"], "excluded"):
            continue
        if not _bool(row["is_representative"], "is_representative"):
            continue
        family = row["family"]
        if family not in FAMILIES:
            continue

        jid = row["jid"]
        reduced_formula = row["reduced_formula"]
        if not isinstance(jid, str) or not jid.strip():
            raise ValueError("Eligible discovery representative is missing a JID")
        if not isinstance(reduced_formula, str) or not reduced_formula.strip():
            raise ValueError(f"Eligible discovery representative {jid} is missing a reduced formula")
        if jid in seen_jids:
            raise ValueError(f"Duplicate eligible JID: {jid}")
        family_formula = (family, reduced_formula)
        if family_formula in seen_family_formula:
            raise ValueError(f"Duplicate eligible family/reduced_formula: {family}/{reduced_formula}")
        seen_jids.add(jid)
        seen_family_formula.add(family_formula)
        eligible.append(row)
    return eligible


def _screen_status(gap: float | None, ehull: float | None, ehull_valid: bool) -> str:
    if gap is None or ehull is None or not ehull_valid:
        return "unknown"
    if GAP_WINDOW_EV[0] <= gap <= GAP_WINDOW_EV[1] and ehull <= EHULL_MAX_EV_ATOM:
        return "pass"
    return "fail"


def _candidate_label(opt_status: str, mbj_status: str) -> str:
    pair = (opt_status, mbj_status)
    labels = {
        ("pass", "pass"): "passes_both_methods",
        ("pass", "fail"): "opt_only",
        ("fail", "pass"): "mbj_only",
        ("pass", "unknown"): "opt_pass_mbj_unknown",
        ("unknown", "pass"): "mbj_pass_opt_unknown",
        ("fail", "fail"): "neither_passes",
        ("unknown", "unknown"): "insufficient_evidence",
    }
    return labels.get(pair, "no_current_pass_incomplete_evidence")


def _method_reason(method: str, gap: float | None, ehull: float | None, ehull_valid: bool) -> str:
    if gap is None:
        gap_reason = "gap unavailable or non-finite"
    elif gap < GAP_WINDOW_EV[0]:
        gap_reason = f"gap below {GAP_WINDOW_EV[0]:g} eV window"
    elif gap > GAP_WINDOW_EV[1]:
        gap_reason = f"gap above {GAP_WINDOW_EV[1]:g} eV window"
    else:
        gap_reason = "gap within inclusive frozen window"
    if not ehull_valid:
        hull_reason = "valid finite ehull unavailable"
    elif ehull is not None and ehull > EHULL_MAX_EV_ATOM:
        hull_reason = f"ehull above {EHULL_MAX_EV_ATOM:g} eV/atom limit"
    else:
        hull_reason = f"ehull within {EHULL_MAX_EV_ATOM:g} eV/atom limit"
    return f"{method.upper()}: {gap_reason}; {hull_reason}"


def _reason(ehull_valid: bool, ehull: float | None, opt_gap: float | None, mbj_gap: float | None) -> str:
    return "; ".join((
        _method_reason("OPT", opt_gap, ehull, ehull_valid),
        _method_reason("MBJ", mbj_gap, ehull, ehull_valid),
    ))


def _next_validation(label: str) -> str:
    if label == "passes_both_methods":
        return "Validate structure/stability and the intended physical target independently."
    if label in {"opt_only", "mbj_only"}:
        return "Run a targeted method/convergence and structural-input check on the same JID."
    if label in {"opt_pass_mbj_unknown", "mbj_pass_opt_unknown"}:
        return "Obtain the missing calculation for the same representative before a cross-method claim."
    return "No current shortlist priority; unknown evidence remains unknown."


def _outcomes(eligible: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    calculated: list[dict[str, Any]] = []
    for row in eligible:
        opt_gap = _number(row.get("opt_gap_ev"))
        mbj_gap = _number(row.get("mbj_gap_ev"))
        ehull = _number(row.get("ehull_ev_atom"))
        source_ehull_valid = _bool(row["ehull_valid"], "ehull_valid")
        ehull_valid = source_ehull_valid and ehull is not None
        opt_status = _screen_status(opt_gap, ehull, ehull_valid)
        mbj_status = _screen_status(mbj_gap, ehull, ehull_valid)
        paired = opt_gap is not None and mbj_gap is not None and ehull_valid
        label = _candidate_label(opt_status, mbj_status)
        shortlisted = opt_status == "pass" or mbj_status == "pass"
        calculated.append({
            "source": row,
            "opt_gap_ev": opt_gap,
            "mbj_gap_ev": mbj_gap,
            "ehull_ev_atom": ehull,
            "ehull_valid": ehull_valid,
            "paired": paired,
            "opt_status": opt_status,
            "mbj_status": mbj_status,
            "candidate_label": label,
            "shortlisted": shortlisted,
        })

    audit_rows: list[dict[str, Any]] = []
    for outcome in sorted(
        calculated,
        key=lambda item: (item["source"]["family"], item["source"]["jid"]),
    ):
        row = outcome["source"]
        label = outcome["candidate_label"]
        audit_rows.append({
            "jid": row["jid"],
            "reduced_formula": row["reduced_formula"],
            "family": row["family"],
            "opt_gap_ev": outcome["opt_gap_ev"],
            "mbj_gap_ev": outcome["mbj_gap_ev"],
            "ehull_ev_atom": outcome["ehull_ev_atom"],
            "ehull_valid": outcome["ehull_valid"],
            "paired": outcome["paired"],
            "opt_status": outcome["opt_status"],
            "mbj_status": outcome["mbj_status"],
            "candidate_label": label,
            "shortlisted": outcome["shortlisted"],
            "reason": _reason(
                outcome["ehull_valid"], outcome["ehull_ev_atom"],
                outcome["opt_gap_ev"], outcome["mbj_gap_ev"],
            ),
            "next_validation": _next_validation(label),
        })
    return calculated, audit_rows


def _arm_group(
    outcomes: list[dict[str, Any]], family: str, arm: str,
) -> tuple[dict[str, Any], list[int]]:
    all_family_rows = [outcome for outcome in outcomes if outcome["source"]["family"] == family]
    selected = [
        outcome for outcome in all_family_rows
        if (arm == "opt_all" or outcome["paired"])
        and outcome["opt_status" if arm != "mbj_paired" else "mbj_status"] in {"pass", "fail"}
    ]
    endpoints = [
        int(outcome["opt_status" if arm != "mbj_paired" else "mbj_status"] == "pass")
        for outcome in selected
    ]
    n_total = len(all_family_rows)
    n_observed = len(endpoints)
    n_pass = sum(endpoints)
    return {
        "n_total": n_total,
        "n_observed": n_observed,
        "n_pass": n_pass,
        "coverage": n_observed / n_total if n_total else None,
        "observed_rate": n_pass / n_observed if n_observed else None,
    }, endpoints


def _interval_contains_zero(interval: list[float] | None) -> bool | None:
    return None if interval is None else interval[0] <= 0.0 <= interval[1]


def _arm_analysis(outcomes: list[dict[str, Any]], protocol: dict[str, Any], arm: str) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    endpoints: dict[str, list[int]] = {}
    for family in FAMILIES:
        summary, values = _arm_group(outcomes, family, arm)
        groups[family] = summary
        endpoints[family] = values

    bootstrap = None
    delta = None
    interval = None
    if endpoints["oxide"] and endpoints["chalcogenide"]:
        bootstrap = bootstrap_difference(
            endpoints["oxide"],
            endpoints["chalcogenide"],
            replicates=protocol["bootstrap_repeats"],
            seed=protocol["seed"],
        )
        delta = bootstrap["delta"]
        interval = bootstrap["resampling_interval"]

    min_count = (
        protocol["quality"]["opt_all_min_observed_per_family"]
        if arm == "opt_all"
        else protocol["quality"]["paired_min_observed_per_family"]
    )
    coverage_floor = protocol["quality"]["opt_all_min_coverage"] if arm == "opt_all" else None
    quality_flags: dict[str, Any] = {}
    for family in FAMILIES:
        group = groups[family]
        coverage_pass = (
            group["coverage"] is not None and group["coverage"] >= coverage_floor
            if coverage_floor is not None else None
        )
        quality_flags[family] = {
            "minimum_evaluable_count_pass": group["n_observed"] >= min_count,
            "minimum_coverage_pass": coverage_pass,
            "endpoint_has_pass_and_fail": 0 < group["n_pass"] < group["n_observed"],
        }
    sample_and_coverage_pass = all(
        quality_flags[family]["minimum_evaluable_count_pass"]
        and (quality_flags[family]["minimum_coverage_pass"] is not False)
        for family in FAMILIES
    )
    endpoint_non_degenerate = all(
        quality_flags[family]["endpoint_has_pass_and_fail"] for family in FAMILIES
    )
    contains_zero = _interval_contains_zero(interval)
    quality_flags.update({
        "minimum_sample_and_coverage_pass": sample_and_coverage_pass,
        "endpoint_non_degenerate": endpoint_non_degenerate,
        "interval_contains_zero": contains_zero,
        "paired_scope_conditional_only": arm != "opt_all",
    })

    if not sample_and_coverage_pass:
        scientific_status = "data_limited"
    elif not endpoint_non_degenerate or contains_zero is not False:
        scientific_status = "inconclusive"
    elif interval[0] > 0.0:
        scientific_status = "supported_in_snapshot"
    elif interval[1] < 0.0:
        scientific_status = "reversed_in_snapshot"
    else:
        scientific_status = "inconclusive"
    return {
        "groups_summary": groups,
        "delta": delta,
        "resampling_interval": interval,
        "scientific_status": scientific_status,
        "quality_flags": quality_flags,
    }


def _bootstrap_mean(values: np.ndarray, replicates: int, rng: np.random.Generator) -> list[float] | None:
    if values.size == 0:
        return None
    samples = np.empty(replicates, dtype=np.float64)
    batch_size = max(1, min(64, replicates))
    for start in range(0, replicates, batch_size):
        stop = min(start + batch_size, replicates)
        draws = rng.integers(0, values.size, size=(stop - start, values.size))
        samples[start:stop] = values[draws].mean(axis=1)
    lower, upper = np.quantile(samples, [0.025, 0.975], method="linear")
    return [float(lower), float(upper)]


def _bootstrap_paired_delta(
    oxide: np.ndarray, chalcogenide: np.ndarray, replicates: int, seed: int,
) -> list[float] | None:
    if oxide.size == 0 or chalcogenide.size == 0:
        return None
    oxide_seed, chalc_seed = np.random.SeedSequence(seed).spawn(2)
    oxide_rng = np.random.default_rng(oxide_seed)
    chalc_rng = np.random.default_rng(chalc_seed)
    samples = np.empty(replicates, dtype=np.float64)
    batch_size = max(1, min(64, replicates))
    for start in range(0, replicates, batch_size):
        stop = min(start + batch_size, replicates)
        size = stop - start
        # Each sampled index selects one same-JID method pair, retaining its sign.
        oxide_draws = oxide_rng.integers(0, oxide.size, size=(size, oxide.size))
        chalc_draws = chalc_rng.integers(0, chalcogenide.size, size=(size, chalcogenide.size))
        samples[start:stop] = (
            chalcogenide[chalc_draws].mean(axis=1) - oxide[oxide_draws].mean(axis=1)
        )
    lower, upper = np.quantile(samples, [0.025, 0.975], method="linear")
    return [float(lower), float(upper)]


def _paired_change_analysis(outcomes: list[dict[str, Any]], protocol: dict[str, Any]) -> dict[str, Any]:
    paired_by_family = {
        family: [
            outcome for outcome in outcomes
            if outcome["source"]["family"] == family and outcome["paired"]
        ]
        for family in FAMILIES
    }
    changes = {
        family: np.asarray([
            int(outcome["mbj_status"] == "pass") - int(outcome["opt_status"] == "pass")
            for outcome in paired_by_family[family]
        ], dtype=np.int8)
        for family in FAMILIES
    }
    bootstrap_repeats = protocol["bootstrap_repeats"]
    seed = protocol["seed"]
    child_seeds = np.random.SeedSequence(seed).spawn(2)

    groups: dict[str, dict[str, Any]] = {}
    for family, child_seed in zip(FAMILIES, child_seeds[:2]):
        family_rows = paired_by_family[family]
        values = changes[family]
        groups[family] = {
            "n_paired": len(family_rows),
            "n_opt_pass": sum(outcome["opt_status"] == "pass" for outcome in family_rows),
            "n_mbj_pass": sum(outcome["mbj_status"] == "pass" for outcome in family_rows),
            "n_gained": int(np.count_nonzero(values == 1)),
            "n_lost": int(np.count_nonzero(values == -1)),
            "mean_change": float(values.mean()) if values.size else None,
            "resampling_interval": _bootstrap_mean(
                values, bootstrap_repeats, np.random.default_rng(child_seed),
            ),
        }

    oxide_values = changes["oxide"]
    chalc_values = changes["chalcogenide"]
    delta = None
    interval = None
    if oxide_values.size and chalc_values.size:
        delta = float(chalc_values.mean() - oxide_values.mean())
        interval = _bootstrap_paired_delta(
            oxide_values, chalc_values, bootstrap_repeats, seed,
        )

    min_paired = protocol["quality"]["paired_min_observed_per_family"]
    enough_rows = all(groups[family]["n_paired"] >= min_paired for family in FAMILIES)
    constant_by_family = {
        family: bool(changes[family].size and np.unique(changes[family]).size == 1)
        for family in FAMILIES
    }
    nonconstant = all(changes[family].size >= 2 and not constant_by_family[family] for family in FAMILIES)
    contains_zero = _interval_contains_zero(interval)
    quality_flags = {
        family: {
            "minimum_paired_rows_pass": groups[family]["n_paired"] >= min_paired,
            "paired_differences_constant": constant_by_family[family],
        }
        for family in FAMILIES
    }
    quality_flags.update({
        "minimum_paired_rows_pass": enough_rows,
        "paired_differences_nonconstant": nonconstant,
        "interval_contains_zero": contains_zero,
        "coverage_limits_generalization_to_all_eligible": True,
    })
    if not enough_rows:
        scientific_status = "data_limited"
    elif not nonconstant or contains_zero is not False:
        scientific_status = "inconclusive"
    elif interval[0] > 0.0:
        scientific_status = "direction_positive"
    elif interval[1] < 0.0:
        scientific_status = "direction_negative"
    else:
        scientific_status = "inconclusive"
    return {
        "groups_summary": groups,
        "delta": delta,
        "resampling_interval": interval,
        "scientific_status": scientific_status,
        "quality_flags": quality_flags,
    }


def analyze_rows(
    rows: list[dict[str, Any]], protocol: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Analyze eligible synthetic or prepared rows under the frozen protocol."""
    _validate_protocol(protocol)
    eligible = _eligible_rows(rows)
    outcomes, audit_rows = _outcomes(eligible)
    arms = {
        arm: _arm_analysis(outcomes, protocol, arm)
        for arm in ("opt_all", "opt_paired", "mbj_paired")
    }
    subset_shift = {}
    for family in FAMILIES:
        opt_all_rate = arms["opt_all"]["groups_summary"][family]["observed_rate"]
        opt_paired_rate = arms["opt_paired"]["groups_summary"][family]["observed_rate"]
        subset_shift[family] = (
            opt_paired_rate - opt_all_rate
            if opt_paired_rate is not None and opt_all_rate is not None
            else None
        )

    paired_method_change = _paired_change_analysis(outcomes, protocol)
    transitions = {
        family: {
            "pass_to_pass": 0,
            "pass_to_fail": 0,
            "fail_to_pass": 0,
            "fail_to_fail": 0,
        }
        for family in FAMILIES
    }
    for outcome in outcomes:
        if not outcome["paired"]:
            continue
        transition = f"{outcome['opt_status']}_to_{outcome['mbj_status']}"
        transitions[outcome["source"]["family"]][transition] += 1

    candidate_counts = {label: 0 for label in _CANDIDATE_LABELS}
    candidate_counts_by_family = {
        family: {label: 0 for label in _CANDIDATE_LABELS}
        for family in FAMILIES
    }
    for outcome in outcomes:
        label = outcome["candidate_label"]
        family = outcome["source"]["family"]
        candidate_counts[label] += 1
        candidate_counts_by_family[family][label] += 1

    analysis = {
        "arms": arms,
        "subset_shift": subset_shift,
        "paired_method_change": paired_method_change,
        "transitions": transitions,
        "candidate_counts": candidate_counts,
        "candidate_counts_by_family": candidate_counts_by_family,
        "n_eligible": len(eligible),
        "n_shortlisted": sum(bool(outcome["shortlisted"]) for outcome in outcomes),
    }
    return analysis, audit_rows


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_experiment() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run the pinned discovery audit with no caller-supplied experiment choices."""
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()

    protocol_started = time.perf_counter()
    extension_protocol, extension_protocol_sha256 = _read_method_protocol()
    protocol_validation_seconds = time.perf_counter() - protocol_started

    validation_started = time.perf_counter()
    rows, manifest, _parent_protocol = pipeline._read_prepared_compositions()
    _verify_provenance_links(extension_protocol, manifest)
    prepared_validation_seconds = time.perf_counter() - validation_started

    computation_started = time.perf_counter()
    analysis, audit_rows = analyze_rows(rows, extension_protocol)
    computation_seconds = time.perf_counter() - computation_started

    finished_at = datetime.now(timezone.utc).isoformat()
    elapsed_seconds = time.perf_counter() - started
    module_path = Path(__file__).resolve()
    statistics_path = Path(pipeline.__file__).resolve().parent.parent / "statistics.py"
    pipeline_path = Path(pipeline.__file__).resolve()
    result = {
        "schema_version": 1,
        "template": "method_sensitivity",
        "execution_status": "success",
        "split": "discovery",
        "dataset_sha256": manifest["original_download_zip_sha256"],
        "parent_protocol_sha256": manifest["protocol_sha256"],
        "protocol_sha256": extension_protocol_sha256,
        "representative_compositions_csv_sha256": manifest["representative_compositions_csv_sha256"],
        "split_assignment_sha256": manifest["split_assignment_sha256"],
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "timing_seconds": {
            "protocol_validation": protocol_validation_seconds,
            "prepared_data_validation": prepared_validation_seconds,
            "computation": computation_seconds,
            "total": elapsed_seconds,
        },
        "source_sha256": _sha256_file(module_path),
        "source_hashes": {
            "nova/experiments/method_sensitivity.py": _sha256_file(module_path),
            "nova/statistics.py": _sha256_file(statistics_path),
            "nova/data/pipeline.py": _sha256_file(pipeline_path),
        },
        "interpretation_scope": "Observed JARVIS representatives in the frozen discovery split; MBJ is a computational method, not ground truth.",
        "selection_mode": "human_selected",
        "no_new_model_calls": True,
        **analysis,
    }
    return result, audit_rows
