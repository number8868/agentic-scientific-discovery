"""Frozen, one-shot holdout comparison for the registered NOVA final protocol.

All request, discovery-evidence, and prepared-manifest checks run before the
prepared composition loader is called. Numeric outcomes are computed only from
the holdout split and are compared with already stored discovery results.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from nova.contracts import ExperimentSpec, Result, Split, Template
from nova.data import pipeline
from nova.experiments import family_screen, threshold_sensitivity
from nova.statistics import BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED, bootstrap_difference, missingness_difference


PROJECT_ROOT = pipeline.PROJECT_ROOT
DATASET_SHA256 = "f9e0a3309f0000d5de1ec9e49c93963109ea45e63f451103f8f6595d2eabf7f5"
PROTOCOL_SHA256 = "9497988f1f8443f66326fa66a976d7196e5671ad320a1cce8a638780a8fc64ac"
SPLIT_ASSIGNMENT_SHA256 = "96c9c210f77698d47bfdb68f9b3ad65673766a879785a6c7d983d7ee3777a58c"
COMPOSITIONS_SHA256 = "d7184816ea97e4daa860b1a93a387b56a82280d3758eb2f658fbfa7ab021fb50"
CLEANING_SCRIPT_SHA256 = "944c23f9c7f8b8cb4d68c0e23c4e197181b33e39ffa352fcc3a9b22339f6be0a"
DEPENDENCY_SPEC = {
    "files": {
        "requirements-science-lock.txt": "7894930b0e716d73935d2b8f524b971a781bc8141e71461bf6802753f8b7af0f",
        "requirements-science.txt": "7d999e0c77206a7b82a97cbe6dc96c46cc16cf3e2bb2e94eb8d66fb93d8ba242",
    }
}
HOLDOUT_MIN_EVALUABLE = 20
MIN_COVERAGE = 0.80
DISCOVERY_STATUSES = frozenset({"supported_in_snapshot", "reversed_in_snapshot", "inconclusive", "data_limited"})
HOLDOUT_LABELS = frozenset({
    "replicated_in_snapshot",
    "direction_consistent_inconclusive",
    "inconclusive",
    "contradicted",
    "data_limited",
    "not_tested",
})

_PROTOCOL_FIELDS = frozenset({
    "schema_version", "hypothesis_id", "dataset_sha256", "main_result_id",
    "followup_result_id", "main_spec", "followup_spec", "review_refs",
    "explanation", "holdout_split", "holdout_template",
})
_FROZEN_SPLIT_RULE = {
    "unit": "reduced_formula within family",
    "seed": 1_729,
    "discovery_fraction": 0.70,
    "method": "sorted eligible composition keys permuted by NumPy default_rng(seed) independently per family; floor(0.70*n) discovery; remaining keys holdout",
    "holdout_execution_allowed": False,
}
_CONTRACT_FIELDS = frozenset(field.name for field in fields(ExperimentSpec))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _implementation_sha256() -> str:
    return _sha256_file(Path(__file__).resolve())


def _sha256_file(path: Path) -> str:
    return pipeline.sha256_file(path)


def _under_root(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("prepared manifest contains an unsafe relative path")
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise ValueError("prepared manifest path escapes its data directory") from None
    return resolved


def _verify_fixed_manifests() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    """Verify every pinned input using metadata and byte hashes only."""
    data_root = PROJECT_ROOT / "data"
    manifest = pipeline._read_json(data_root / "manifest.json")
    expected_manifest_values = {
        "dataset": "dft_3d",
        "protocol_file": "protocol.json",
        "representative_compositions_csv": "audit/compositions.csv",
        "original_download_zip_sha256": DATASET_SHA256,
        "protocol_sha256": PROTOCOL_SHA256,
        "split_assignment_sha256": SPLIT_ASSIGNMENT_SHA256,
        "representative_compositions_csv_sha256": COMPOSITIONS_SHA256,
        "cleaning_script_sha256": CLEANING_SCRIPT_SHA256,
        "dependency_spec": DEPENDENCY_SPEC,
        "split_seed": 1_729,
        "split_rule": _FROZEN_SPLIT_RULE,
    }
    for key, expected in expected_manifest_values.items():
        if manifest.get(key) != expected:
            raise ValueError(f"prepared manifest field {key} differs from the fixed snapshot")
    if manifest.get("holdout_visibility") != "read_metadata exposes only family/split counts and missingness coverage; the discovery adapter rejects holdout":
        raise ValueError("prepared manifest does not preserve the holdout visibility boundary")
    split_rule = manifest.get("split_rule")
    if not isinstance(split_rule, Mapping) or split_rule.get("holdout_execution_allowed") is not False:
        raise ValueError("prepared split manifest does not close holdout execution by default")

    protocol_path = _under_root(data_root, manifest.get("protocol_file", ""))
    if _sha256_file(protocol_path) != PROTOCOL_SHA256:
        raise ValueError("frozen family protocol bytes do not match the registered hash")
    parent_protocol = pipeline._read_json(protocol_path)
    if (
        parent_protocol.get("protocol_id") != "family_screen_v1"
        or parent_protocol.get("dataset_sha256") != DATASET_SHA256
        or parent_protocol.get("split") != _FROZEN_SPLIT_RULE
    ):
        raise ValueError("frozen family protocol does not match the registered snapshot")

    # Verify the source snapshots and prepared table by bytes before the CSV is
    # parsed into rows. Hashing does not inspect any property values.
    for key, digest_key in (
        ("original_download_zip", "original_download_zip_sha256"),
        ("original_inner_json", "original_inner_json_sha256"),
        ("representative_compositions_csv", "representative_compositions_csv_sha256"),
    ):
        path = _under_root(data_root, manifest.get(key, ""))
        if _sha256_file(path) != manifest.get(digest_key):
            raise ValueError(f"frozen {key} bytes do not match the prepared manifest")
    if _sha256_file(PROJECT_ROOT / "nova" / "data" / "pipeline.py") != CLEANING_SCRIPT_SHA256:
        raise ValueError("frozen cleaning code differs from the prepared manifest")
    if pipeline._dependency_fingerprint() != DEPENDENCY_SPEC:
        raise ValueError("science dependency specification differs from the prepared manifest")

    extension, extension_sha256 = threshold_sensitivity._read_threshold_protocol()
    threshold_sensitivity._check_threshold_protocol(extension, extension_sha256, manifest)
    if tuple(extension.get("ehull_grid_ev_atom", ())) != threshold_sensitivity.THRESHOLD_GRID_EV_ATOM:
        raise ValueError("threshold extension grid differs from its frozen computation")
    return manifest, parent_protocol, extension, extension_sha256


def _contract_from_payload(payload: Mapping[str, Any]) -> tuple[ExperimentSpec, str]:
    if not isinstance(payload, Mapping):
        raise TypeError("registered holdout payload must be a mapping")
    if payload.get("mode") != "live":
        raise ValueError("holdout executor accepts live mode only")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("holdout host run_id is required")
    unknown = set(payload) - _CONTRACT_FIELDS - {"mode", "run_id"}
    if unknown:
        raise ValueError(f"unknown holdout executor fields: {sorted(unknown)}")
    contract_fields = {key: value for key, value in payload.items() if key in _CONTRACT_FIELDS}
    contract = ExperimentSpec.from_dict(contract_fields)
    if contract.split is not Split.HOLDOUT or contract.template is not Template.HOLDOUT_VALIDATION:
        raise ValueError("registered holdout spec must use holdout_validation on the holdout split")
    return contract, run_id


def _protocol_and_spec(
    payload: Mapping[str, Any], frozen_protocol: Mapping[str, Any]
) -> tuple[ExperimentSpec, ExperimentSpec, ExperimentSpec, str, str]:
    holdout, run_id = _contract_from_payload(payload)
    if not isinstance(frozen_protocol, Mapping) or set(frozen_protocol) != _PROTOCOL_FIELDS:
        raise ValueError("frozen protocol has an unsupported shape")
    if (
        isinstance(frozen_protocol.get("schema_version"), bool)
        or frozen_protocol.get("schema_version") != 1
        or frozen_protocol.get("holdout_split") != "holdout"
        or frozen_protocol.get("holdout_template") != "holdout_validation"
    ):
        raise ValueError("frozen protocol has an unsupported version or holdout target")
    explanation = frozen_protocol.get("explanation")
    if (
        not isinstance(explanation, str)
        or len(explanation) > 500
        or any(ord(char) < 32 and char not in "\t" for char in explanation)
    ):
        raise ValueError("frozen protocol explanation is invalid")
    protocol_sha256 = hashlib.sha256(
        json.dumps(frozen_protocol, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    frozen_id = "NOVA-FINAL-" + protocol_sha256[:16]
    if holdout.frozen_protocol_id != frozen_id:
        raise ValueError("holdout spec does not reference the supplied frozen protocol")
    if holdout.experiment_id != "NOVA-HOLDOUT-" + hashlib.sha256((run_id + ":" + frozen_id).encode()).hexdigest()[:16]:
        raise ValueError("holdout experiment ID is not derived from this run and frozen protocol")

    try:
        main = ExperimentSpec.from_dict(frozen_protocol["main_spec"])
        followup = ExperimentSpec.from_dict(frozen_protocol["followup_spec"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("frozen protocol contains an invalid discovery spec") from error
    main_result_id = frozen_protocol.get("main_result_id")
    followup_result_id = frozen_protocol.get("followup_result_id")
    if not isinstance(main_result_id, str) or not main_result_id or not isinstance(followup_result_id, str) or not followup_result_id:
        raise ValueError("frozen protocol is missing discovery result references")
    if frozen_protocol.get("review_refs") != [main_result_id, followup_result_id]:
        raise ValueError("frozen review references do not match the discovery results")
    if (
        main.split is not Split.DISCOVERY or main.template is not Template.FAMILY_SCREEN
        or followup.split is not Split.DISCOVERY or followup.template is not Template.THRESHOLD_SENSITIVITY
        or followup.parent_result_id != main_result_id or followup.review_id != main_result_id
        or main.hypothesis_id != followup.hypothesis_id
        or main.dataset_sha256 != followup.dataset_sha256
        or main.groups != followup.groups or main.bandgap_method != followup.bandgap_method
        or main.gap_window_ev != followup.gap_window_ev
        or main.ehull_max_ev_atom != followup.ehull_max_ev_atom
        or main.bootstrap_repeats != followup.bootstrap_repeats or main.seed != followup.seed
        or main.timeout_seconds != followup.timeout_seconds
    ):
        raise ValueError("frozen main and follow-up specs do not define the same discovery protocol")
    if (
        main.dataset_sha256 != DATASET_SHA256
        or main.ehull_max_ev_atom != 0.05
        or main.bootstrap_repeats != BOOTSTRAP_REPLICATES
        or main.seed != BOOTSTRAP_SEED
        or main.timeout_seconds != 120
        or main.groups != ("oxide", "chalcogenide")
        or main.bandgap_method != "opt"
        or main.gap_window_ev != (1.1, 1.8)
    ):
        raise ValueError("frozen discovery parameters differ from the final holdout design")
    expected_holdout = ExperimentSpec(
        1,
        holdout.experiment_id,
        main.hypothesis_id,
        main.dataset_sha256,
        Split.HOLDOUT,
        Template.HOLDOUT_VALIDATION,
        main.groups,
        main.bandgap_method,
        main.gap_window_ev,
        main.ehull_max_ev_atom,
        main.bootstrap_repeats,
        main.seed,
        main.timeout_seconds,
        followup_result_id,
        followup_result_id,
        frozen_id,
    )
    if holdout != expected_holdout:
        raise ValueError("holdout spec differs from the parameters derived from the frozen discovery specs")
    if frozen_protocol.get("dataset_sha256") != main.dataset_sha256:
        raise ValueError("frozen protocol dataset differs from its discovery specs")
    return main, followup, holdout, protocol_sha256, frozen_id


def _result_value(value: Any, name: str) -> Result:
    try:
        result = value if isinstance(value, Result) else Result.from_dict(value)
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError(f"discovery evidence {name} is not a canonical Result") from error
    if result.execution_status != "completed" or result.error is not None:
        raise ValueError(f"discovery evidence {name} is not a successful result")
    if result.scientific_status not in DISCOVERY_STATUSES:
        raise ValueError(f"discovery evidence {name} has an unsupported scientific status")
    return result


def _quality_from_result(result: Result) -> dict[str, Any]:
    entries = [item for item in result.quality_flags if item.startswith("science-quality-json-v1:")]
    if len(entries) != 1:
        raise ValueError("discovery Result must contain one structured quality flag entry")
    try:
        value = json.loads(entries[0].partition(":")[2])
    except json.JSONDecodeError as error:
        raise ValueError("discovery Result quality flags are malformed") from error
    if not isinstance(value, dict):
        raise ValueError("discovery Result quality flags must be an object")
    return value


def _quality_pass(flags: Mapping[str, Any]) -> bool:
    families = flags.get("families")
    if not isinstance(families, Mapping):
        # Low-level threshold points store the two family objects at top level.
        families = flags
    if flags.get("minimum_sample_and_coverage_pass") is not True or flags.get("endpoint_non_degenerate") is not True:
        return False
    for family in ("oxide", "chalcogenide"):
        detail = families.get(family)
        if not isinstance(detail, Mapping) or any(
            detail.get(field) is not True
            for field in ("minimum_evaluable_count_pass", "minimum_coverage_pass", "endpoint_has_pass_and_fail")
        ):
            return False
    return True


def _result_groups(result: Result) -> dict[str, dict[str, Any]]:
    return {
        summary.group: {
            "n_total": summary.n_total,
            "n_observed": summary.n_observed,
            "n_pass": summary.n_pass,
            "coverage": summary.coverage,
            "observed_rate": summary.observed_rate,
            "missing_lower": summary.missing_lower,
            "missing_upper": summary.missing_upper,
        }
        for summary in result.groups_summary
    }


def _direction(delta: Any) -> str:
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not math.isfinite(float(delta)):
        return "unavailable"
    if delta > 0:
        return "positive"
    if delta < 0:
        return "negative"
    return "zero"


def _valid_interval(value: Any) -> bool:
    return (
        isinstance(value, (tuple, list))
        and len(value) == 2
        and all(not isinstance(bound, bool) and isinstance(bound, (int, float)) and math.isfinite(float(bound)) for bound in value)
        and -1 <= value[0] <= value[1] <= 1
    )


def _validate_discovery_point(point: Mapping[str, Any], threshold: float) -> None:
    if point.get("threshold_ev_atom") != threshold:
        raise ValueError("threshold discovery grid points differ from the preregistered order")
    if point.get("scientific_status") not in DISCOVERY_STATUSES:
        raise ValueError("threshold discovery point has an unsupported scientific status")
    if _direction(point.get("delta")) == "unavailable" or not _valid_interval(point.get("resampling_interval")):
        if point.get("scientific_status") != "data_limited":
            raise ValueError("threshold discovery point has invalid numerical outcomes")
    if not isinstance(point.get("groups_summary"), Mapping) or set(point["groups_summary"]) != {"oxide", "chalcogenide"}:
        raise ValueError("threshold discovery point has malformed group summaries")
    if not isinstance(point.get("quality_flags"), Mapping):
        raise ValueError("threshold discovery point has malformed structured quality flags")
    quality = point["quality_flags"]
    status = point["scientific_status"]
    size_pass = quality.get("minimum_sample_and_coverage_pass") is True
    endpoint_pass = quality.get("endpoint_non_degenerate") is True
    interval = point.get("resampling_interval")
    if status in {"supported_in_snapshot", "reversed_in_snapshot"}:
        if not _quality_pass(quality) or not _valid_interval(interval):
            raise ValueError("threshold discovery direction lacks valid quality and interval evidence")
        if status == "supported_in_snapshot" and (not interval[0] > 0.0 or point["delta"] <= 0.0):
            raise ValueError("threshold discovery support label does not match its interval")
        if status == "reversed_in_snapshot" and (not interval[1] < 0.0 or point["delta"] >= 0.0):
            raise ValueError("threshold discovery reversal label does not match its interval")
    elif status == "inconclusive":
        if not size_pass or (endpoint_pass and (not _valid_interval(interval) or not interval[0] <= 0.0 <= interval[1])):
            raise ValueError("threshold discovery inconclusive label does not match its quality or interval")
    elif status == "data_limited" and size_pass:
        raise ValueError("threshold discovery data-limited label passes its sample and coverage gate")


def _classify(discovery_status: str, discovery_delta: Any, discovery_quality: Mapping[str, Any], holdout_point: Mapping[str, Any]) -> str:
    if not _quality_pass(discovery_quality) or not _quality_pass(holdout_point["quality_flags"]):
        return "data_limited"
    holdout_status = holdout_point["holdout_scientific_status"]
    if discovery_status == "data_limited" or holdout_status == "data_limited":
        return "data_limited"
    if discovery_status in {"supported_in_snapshot", "reversed_in_snapshot"} and holdout_status in {"supported_in_snapshot", "reversed_in_snapshot"}:
        return "replicated_in_snapshot" if discovery_status == holdout_status else "contradicted"
    discovery_direction = _direction(discovery_delta)
    holdout_direction = _direction(holdout_point["delta"])
    if (
        (discovery_status == "inconclusive" or holdout_status == "inconclusive")
        and discovery_direction == holdout_direction
        and discovery_direction in {"positive", "negative"}
    ):
        return "direction_consistent_inconclusive"
    return "inconclusive"


def _validate_discovery_evidence(
    evidence: Mapping[str, Any] | None,
    protocol: Mapping[str, Any],
    main_spec: ExperimentSpec,
    followup_spec: ExperimentSpec,
    manifest: Mapping[str, Any],
    extension_sha256: str,
) -> tuple[Result, Result, dict[str, Any], dict[str, Any]]:
    if not isinstance(evidence, Mapping):
        raise ValueError("authenticated discovery result evidence is required for holdout comparison")
    main_result = _result_value(evidence.get("main_result"), "main_result")
    followup_result = _result_value(evidence.get("followup_result"), "followup_result")
    threshold_result = evidence.get("followup_science_result")
    if not isinstance(threshold_result, Mapping):
        raise ValueError("authenticated threshold follow-up science payload is required")
    if (
        main_result.result_id != protocol["main_result_id"]
        or main_result.experiment_id != main_spec.experiment_id
        or main_result.spec_sha256 != main_spec.sha256
        or main_result.dataset_sha256 != main_spec.dataset_sha256
        or followup_result.result_id != protocol["followup_result_id"]
        or followup_result.experiment_id != followup_spec.experiment_id
        or followup_result.spec_sha256 != followup_spec.sha256
        or followup_result.dataset_sha256 != followup_spec.dataset_sha256
    ):
        raise ValueError("discovery Results do not match the frozen protocol IDs, specs, or dataset")
    if not any(item.startswith("nova-result-payload:") for item in followup_result.artifact_ids):
        raise ValueError("threshold discovery Result has no registered science payload reference")
    followup_minimal = {
        key: followup_spec.to_dict()[key]
        for key in executor_science_fields()
    }
    expected_followup_sha = threshold_sensitivity._canonical_sha({
        **followup_minimal,
        "ehull_grid_ev_atom": list(threshold_sensitivity.THRESHOLD_GRID_EV_ATOM),
        "extension_protocol_sha256": extension_sha256,
    })
    if (
        threshold_result.get("template") != "threshold_sensitivity"
        or threshold_result.get("execution_status") != "success"
        or threshold_result.get("dataset_sha256") != manifest.get("original_download_zip_sha256")
        or threshold_result.get("protocol_sha256") != manifest.get("protocol_sha256")
        or threshold_result.get("extension_protocol_sha256") != extension_sha256
        or threshold_result.get("split") != "discovery"
        or threshold_result.get("spec_sha256") != expected_followup_sha
    ):
        raise ValueError("threshold science payload does not match its registered frozen computation")
    points = threshold_result.get("points")
    if not isinstance(points, list) or len(points) != len(threshold_sensitivity.THRESHOLD_GRID_EV_ATOM):
        raise ValueError("threshold discovery payload has an incomplete preregistered grid")
    for point, threshold in zip(points, threshold_sensitivity.THRESHOLD_GRID_EV_ATOM):
        if not isinstance(point, Mapping):
            raise ValueError("threshold discovery point must be an object")
        _validate_discovery_point(point, threshold)
        if point["scientific_status"] in {"supported_in_snapshot", "reversed_in_snapshot"} and not _quality_pass(point["quality_flags"]):
            raise ValueError("threshold discovery point claims direction without all frozen quality gates")
    if (
        threshold_result.get("primary_point_index") != threshold_sensitivity.PRIMARY_POINT_INDEX
        or threshold_result.get("primary_threshold_ev_atom") != 0.05
        or threshold_result.get("scientific_status") != points[threshold_sensitivity.PRIMARY_POINT_INDEX].get("scientific_status")
    ):
        raise ValueError("threshold discovery payload changed its frozen primary point")
    primary = points[threshold_sensitivity.PRIMARY_POINT_INDEX]
    if threshold_result.get("main_point") != primary:
        raise ValueError("threshold discovery primary point differs from its preregistered grid point")
    primary_interval = primary.get("resampling_interval")
    primary_result_interval = tuple(primary_interval) if isinstance(primary_interval, (list, tuple)) else None
    if (
        followup_result.scientific_status != primary.get("scientific_status")
        or followup_result.delta != primary.get("delta")
        or followup_result.resampling_interval != primary_result_interval
        or _quality_from_result(followup_result) != primary.get("quality_flags")
        or _result_groups(followup_result) != primary.get("groups_summary")
    ):
        raise ValueError("canonical threshold Result differs from its verified science payload")
    main_quality = _quality_from_result(main_result)
    if (
        main_result.scientific_status != primary.get("scientific_status")
        or main_result.delta != primary.get("delta")
        or main_result.resampling_interval != primary_result_interval
        or main_quality != primary.get("quality_flags")
        or _result_groups(main_result) != primary.get("groups_summary")
    ):
        raise ValueError("main Result differs from the frozen 0.05 threshold discovery point")
    if main_result.scientific_status == "supported_in_snapshot" and not _quality_pass(main_quality):
        raise ValueError("main discovery Result claims support without all required quality gates")
    if main_result.scientific_status == "reversed_in_snapshot" and not _quality_pass(main_quality):
        raise ValueError("main discovery Result claims reversal without all required quality gates")
    return main_result, followup_result, dict(threshold_result), main_quality


def executor_science_fields() -> tuple[str, ...]:
    """The canonical science fields shared with the discovery Result adapter."""
    return (
        "schema_version", "template", "split", "groups", "bandgap_method",
        "gap_window_ev", "ehull_max_ev_atom", "bootstrap_repeats", "seed",
        "dataset_sha256",
    )


def _group(rows: list[dict[str, Any]], family: str, threshold: float) -> tuple[dict[str, Any], list[int]]:
    family_rows = [
        row for row in rows
        if row["family"] == family and row["split"] == "holdout" and not family_screen._bool(row["excluded"])
    ]
    total = len(family_rows)
    endpoints: list[int] = []
    n_pass = 0
    for row in family_rows:
        gap = family_screen._number(row["opt_gap_ev"])
        ehull = family_screen._number(row["ehull_ev_atom"])
        if gap is None or ehull is None or not family_screen._bool(row["ehull_valid"]):
            continue
        passed = 1.1 <= gap <= 1.8 and ehull <= threshold
        endpoints.append(int(passed))
        n_pass += int(passed)
    observed = len(endpoints)
    return {
        "n_total": total,
        "n_observed": observed,
        "n_pass": n_pass,
        "coverage": observed / total if total else None,
        "observed_rate": n_pass / observed if observed else None,
        "missing_lower": n_pass / total if total else None,
        "missing_upper": (n_pass + total - observed) / total if total else None,
    }, endpoints


def _analyze_point(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    oxide, oxide_values = _group(rows, "oxide", threshold)
    chalc, chalc_values = _group(rows, "chalcogenide", threshold)
    bootstrap = None
    delta = None
    interval = None
    if oxide_values and chalc_values:
        bootstrap = bootstrap_difference(oxide_values, chalc_values, replicates=BOOTSTRAP_REPLICATES, seed=BOOTSTRAP_SEED)
        delta = bootstrap["delta"]
        interval = bootstrap["resampling_interval"]
    quality: dict[str, Any] = {}
    for family, group in (("oxide", oxide), ("chalcogenide", chalc)):
        quality[family] = {
            "minimum_evaluable_count_pass": group["n_observed"] >= HOLDOUT_MIN_EVALUABLE,
            "minimum_coverage_pass": group["coverage"] is not None and group["coverage"] >= MIN_COVERAGE,
            "endpoint_has_pass_and_fail": group["n_pass"] > 0 and group["n_pass"] < group["n_observed"],
        }
    sample_and_coverage_pass = all(
        quality[family][key]
        for family in ("oxide", "chalcogenide")
        for key in ("minimum_evaluable_count_pass", "minimum_coverage_pass")
    )
    endpoint_non_degenerate = all(
        quality[family]["endpoint_has_pass_and_fail"] for family in ("oxide", "chalcogenide")
    )
    missing = missingness_difference(
        oxide_total=oxide["n_total"], oxide_pass=oxide["n_pass"],
        chalcogenide_total=chalc["n_total"], chalcogenide_pass=chalc["n_pass"],
        oxide_observed=oxide["n_observed"], chalcogenide_observed=chalc["n_observed"],
    )
    quality["minimum_sample_and_coverage_pass"] = all(
        quality[family]["minimum_evaluable_count_pass"] and quality[family]["minimum_coverage_pass"]
        for family in ("oxide", "chalcogenide")
    )
    quality["endpoint_non_degenerate"] = all(
        quality[family]["endpoint_has_pass_and_fail"] for family in ("oxide", "chalcogenide")
    )
    all_quality_pass = sample_and_coverage_pass and endpoint_non_degenerate
    quality["all_holdout_quality_gates_pass"] = all_quality_pass
    quality["missingness_bounds_cross_zero"] = (
        missing is not None and missing["lower"] <= 0.0 <= missing["upper"]
    )
    if not sample_and_coverage_pass:
        status = "data_limited"
    elif not endpoint_non_degenerate or interval is None or interval[0] <= 0.0 <= interval[1]:
        status = "inconclusive"
    elif interval[0] > 0:
        status = "supported_in_snapshot"
    elif interval[1] < 0:
        status = "reversed_in_snapshot"
    else:
        status = "inconclusive"
    return {
        "groups_summary": {"oxide": oxide, "chalcogenide": chalc},
        "delta": delta,
        "resampling_interval": interval,
        "missingness_interval": missing,
        "quality_flags": quality,
        "bootstrap": bootstrap,
        "holdout_scientific_status": status,
    }


def computation_spec(
    contract: ExperimentSpec,
    frozen_protocol_sha256: str,
    threshold_protocol_sha256: str,
) -> dict[str, Any]:
    fields = executor_science_fields()
    registered = contract.to_dict()
    return {
        **{key: registered[key] for key in fields},
        "holdout_implementation_sha256": _implementation_sha256(),
        "frozen_protocol_sha256": frozen_protocol_sha256,
        "threshold_extension_protocol_sha256": threshold_protocol_sha256,
        "ehull_grid_ev_atom": list(threshold_sensitivity.THRESHOLD_GRID_EV_ATOM),
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "interval": "95% percentile; family-stratified composition-level resampling",
        },
        "quality_gates": {
            "minimum_evaluable_per_family": HOLDOUT_MIN_EVALUABLE,
            "minimum_primary_coverage": MIN_COVERAGE,
            "endpoint_non_degenerate": True,
        },
        "comparison_labels": sorted(HOLDOUT_LABELS),
    }


def run_experiment(
    payload: Mapping[str, Any],
    frozen_protocol: Mapping[str, Any],
    discovery_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the registered holdout once, comparing against frozen discovery results."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    main_spec, followup_spec, contract, frozen_sha256, frozen_id = _protocol_and_spec(payload, frozen_protocol)
    manifest, parent_protocol, extension, extension_sha256 = _verify_fixed_manifests()
    if (
        contract.dataset_sha256 != manifest.get("original_download_zip_sha256")
        or contract.dataset_sha256 != DATASET_SHA256
        or parent_protocol.get("dataset_sha256") != contract.dataset_sha256
        or extension.get("dataset_sha256") != contract.dataset_sha256
    ):
        raise ValueError("holdout request does not match the fixed prepared snapshot")
    main_result, followup_result, followup_payload, main_quality = _validate_discovery_evidence(
        discovery_evidence, frozen_protocol, main_spec, followup_spec, manifest, extension_sha256
    )

    # The frozen protocol, registered spec, discovery evidence, and every
    # prepared input hash have passed before this loader can parse the table.
    rows, loaded_manifest, loaded_protocol = pipeline._read_prepared_compositions()
    if (
        loaded_manifest.get("original_download_zip_sha256") != manifest.get("original_download_zip_sha256")
        or loaded_manifest.get("protocol_sha256") != manifest.get("protocol_sha256")
        or loaded_manifest.get("split_assignment_sha256") != manifest.get("split_assignment_sha256")
        or loaded_protocol.get("protocol_id") != parent_protocol.get("protocol_id")
    ):
        raise ValueError("prepared inputs changed between preflight and holdout loading")
    holdout_rows = [row for row in rows if row["split"] == "holdout"]
    grid = [
        {"threshold_ev_atom": threshold, **_analyze_point(holdout_rows, threshold)}
        for threshold in threshold_sensitivity.THRESHOLD_GRID_EV_ATOM
    ]
    primary_index = threshold_sensitivity.PRIMARY_POINT_INDEX
    primary = grid[primary_index]

    main_point = {
        "threshold_ev_atom": 0.05,
        **primary,
        "discovery_scientific_status": main_result.scientific_status,
        "discovery_delta": main_result.delta,
        "discovery_resampling_interval": main_result.resampling_interval,
        "replication_status": _classify(
            main_result.scientific_status,
            main_result.delta,
            main_quality,
            primary,
        ),
    }
    for index, point in enumerate(grid):
        discovery_point = followup_payload["points"][index]
        discovery_quality = discovery_point.get("quality_flags")
        if not isinstance(discovery_quality, Mapping):
            raise ValueError("threshold discovery point has malformed structured quality flags")
        point["discovery_scientific_status"] = discovery_point.get("scientific_status")
        point["discovery_delta"] = discovery_point.get("delta")
        point["discovery_resampling_interval"] = discovery_point.get("resampling_interval")
        point["replication_status"] = _classify(
            point["discovery_scientific_status"],
            point["discovery_delta"],
            discovery_quality,
            point,
        )
    if main_point["replication_status"] not in HOLDOUT_LABELS or any(
        point["replication_status"] not in HOLDOUT_LABELS for point in grid
    ):
        raise ValueError("holdout comparison generated an invalid scientific label")

    computation = computation_spec(contract, frozen_sha256, extension_sha256)
    computation_sha256 = _canonical_sha(computation)
    finished_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "template": "holdout_validation",
        "execution_status": "success",
        "scientific_status": main_point["replication_status"],
        "error": None,
        "dataset_sha256": DATASET_SHA256,
        "protocol_sha256": PROTOCOL_SHA256,
        "split_assignment_sha256": SPLIT_ASSIGNMENT_SHA256,
        "representative_compositions_csv_sha256": COMPOSITIONS_SHA256,
        "frozen_protocol_id": frozen_id,
        "frozen_protocol_sha256": frozen_sha256,
        "extension_protocol_sha256": extension_sha256,
        "spec_sha256": computation_sha256,
        "computation_spec": computation,
        "split": "holdout",
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": time.monotonic() - started,
        "primary_point_index": primary_index,
        "primary_threshold_ev_atom": 0.05,
        "main_primary_comparison": main_point,
        "points": grid,
        "groups_summary": primary["groups_summary"],
        "delta": primary["delta"],
        "resampling_interval": primary["resampling_interval"],
        "missingness_interval": primary["missingness_interval"],
        "quality_flags": {
            "main_primary_comparison": {
                "replication_status": main_point["replication_status"],
                "discovery_quality_pass": _quality_pass(main_quality),
                "holdout_quality_pass": _quality_pass(primary["quality_flags"]),
            },
            "threshold_grid": [
                {
                    "threshold_ev_atom": point["threshold_ev_atom"],
                    "replication_status": point["replication_status"],
                    "holdout_quality_flags": point["quality_flags"],
                }
                for point in grid
            ],
            "missingness_bounds_cross_zero_at_primary": primary["quality_flags"]["missingness_bounds_cross_zero"],
        },
        "provenance": {
            "holdout_implementation_sha256": _implementation_sha256(),
            "main_result_id": main_result.result_id,
            "main_experiment_id": main_spec.experiment_id,
            "main_registered_spec_sha256": main_spec.sha256,
            "followup_result_id": followup_result.result_id,
            "followup_experiment_id": followup_spec.experiment_id,
            "followup_registered_spec_sha256": followup_spec.sha256,
            "threshold_extension_protocol_sha256": extension_sha256,
            "dataset_sha256": DATASET_SHA256,
            "family_protocol_sha256": PROTOCOL_SHA256,
            "split_assignment_sha256": SPLIT_ASSIGNMENT_SHA256,
            "representative_compositions_csv_sha256": COMPOSITIONS_SHA256,
        },
        "artifact_ids": [
            "nova-manifest:" + DATASET_SHA256,
            "nova-protocol:" + PROTOCOL_SHA256,
            "nova-compositions-csv:" + COMPOSITIONS_SHA256,
            "nova-threshold-protocol:" + extension_sha256,
            "nova-frozen-protocol:" + frozen_sha256,
            "nova-discovery-result:" + main_result.result_id,
            "nova-discovery-result:" + followup_result.result_id,
        ],
        "interpretation_scope": "Frozen JARVIS snapshot holdout representatives only; bootstrap intervals describe resampling stability in this snapshot; missingness bounds limit interpretation to observed representatives and do not support claims about all real materials.",
    }


__all__ = ["computation_spec", "run_experiment"]
