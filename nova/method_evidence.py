"""Build portable, content-addressable evidence for a registered method audit.

The method audit has three distinct arms and a separate paired-method contrast.
This module preserves those scientific outputs without collapsing them into a
single shared ``Result``. It reads only the frozen extension protocol and uses
the report validators; it never loads prepared property data or runs science.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any, Mapping

from nova.contracts import ExperimentSpec, Result, Split, Template
from nova.experiments import method_sensitivity
from nova.method_audit_report import (
    ARM_ORDER,
    CANDIDATE_LABELS,
    FAMILY_ORDER,
    _validate_result,
    _validate_row_aggregates,
    _validate_rows,
)


_REQUEST_FIELDS = frozenset({
    "schema_version",
    "audit_id",
    "run_id",
    "parent_result_id",
    "parent_experiment_id",
    "parent_spec_sha256",
    "dataset_sha256",
    "protocol_sha256",
})
_SOURCE_HASH_FIELDS = frozenset({
    "nova/experiments/method_sensitivity.py",
    "nova/statistics.py",
    "nova/data/pipeline.py",
})
_CANDIDATE_FIELDS = (
    "family",
    "jid",
    "reduced_formula",
    "opt_gap_ev",
    "mbj_gap_ev",
    "ehull_ev_atom",
    "opt_status",
    "mbj_status",
    "candidate_label",
    "reason",
    "next_validation",
)
_INTERPRETATION_SCOPE = (
    "Observed JARVIS representatives in the frozen discovery split; MBJ is a computational method, not ground truth."
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA256 hex digest")
    return value


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _request_body(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise TypeError("method audit request must be a mapping")
    unknown = set(request) - _REQUEST_FIELDS - {"status"}
    missing = _REQUEST_FIELDS - set(request)
    if missing or unknown:
        raise ValueError(
            f"method audit request fields are invalid (missing={sorted(missing)}, extra={sorted(unknown)})"
        )
    if request.get("status") not in {None, "registered", "running", "completed"}:
        raise ValueError("method audit request has an invalid status")
    body = {key: request[key] for key in sorted(_REQUEST_FIELDS)}
    if isinstance(body["schema_version"], bool) or body["schema_version"] != 1:
        raise ValueError("method audit request schema_version must be 1")
    for key in _REQUEST_FIELDS - {"schema_version"}:
        value = body[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"method audit request {key} must be nonempty text")
    for key in ("parent_spec_sha256", "dataset_sha256", "protocol_sha256"):
        _digest(body[key], f"method audit request {key}")
    expected_id = "NOVA-METHOD-" + _sha256(
        f"{body['run_id']}:{body['parent_result_id']}:{body['parent_spec_sha256']}:{body['protocol_sha256']}".encode()
    )[:24]
    if body["audit_id"] != expected_id:
        raise ValueError("method audit request audit_id does not match its registered links")
    return body


def _coerce_parent_spec(value: Any) -> ExperimentSpec:
    if isinstance(value, ExperimentSpec):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("parent_spec must be an ExperimentSpec or mapping")
    return ExperimentSpec.from_dict(value)


def _coerce_parent_result(value: Any) -> Result:
    if isinstance(value, Result):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("parent_result must be a Result or mapping")
    return Result.from_dict(value)


def _validate_parent(
    request: Mapping[str, Any],
    protocol: Mapping[str, Any],
    parent_result: Result,
    parent_spec: ExperimentSpec,
) -> None:
    if (
        parent_spec.template is not Template.FAMILY_SCREEN
        or parent_spec.split is not Split.DISCOVERY
        or parent_spec.bandgap_method != "opt"
        or tuple(parent_spec.groups) != tuple(protocol["groups"])
        or tuple(parent_spec.gap_window_ev) != tuple(protocol["gap_window_ev"])
        or parent_spec.ehull_max_ev_atom != protocol["ehull_max_ev_atom"]
        or parent_spec.bootstrap_repeats != protocol["bootstrap_repeats"]
        or parent_spec.seed != protocol["seed"]
    ):
        raise ValueError("parent spec does not match the frozen OPT discovery protocol")
    if (
        parent_spec.experiment_id != request["parent_experiment_id"]
        or parent_spec.sha256 != request["parent_spec_sha256"]
        or parent_spec.dataset_sha256 != request["dataset_sha256"]
    ):
        raise ValueError("method audit request does not match its parent spec")
    if (
        parent_result.result_id != request["parent_result_id"]
        or parent_result.experiment_id != parent_spec.experiment_id
        or parent_result.spec_sha256 != parent_spec.sha256
        or parent_result.dataset_sha256 != parent_spec.dataset_sha256
        or parent_result.execution_status != "completed"
        or parent_result.error is not None
        or parent_result.scientific_status is None
    ):
        raise ValueError("method audit request does not match a completed parent Result")


def _validate_runtime_fields(result: Mapping[str, Any]) -> None:
    for key in ("started_at", "finished_at"):
        value = result.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"method audit result is missing {key}")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"method audit result {key} must be an ISO timestamp") from None
        if parsed.tzinfo is None:
            raise ValueError(f"method audit result {key} must include a timezone")
    if not _is_finite_number(result.get("elapsed_seconds")) or result["elapsed_seconds"] < 0:
        raise ValueError("method audit result elapsed_seconds must be finite and nonnegative")
    timing = result.get("timing_seconds")
    expected_fields = {
        "protocol_validation",
        "prepared_data_validation",
        "computation",
        "total",
    }
    if not isinstance(timing, Mapping) or set(timing) != expected_fields:
        raise ValueError("method audit result timing_seconds has an invalid schema")
    if any(not _is_finite_number(timing[key]) or timing[key] < 0 for key in expected_fields):
        raise ValueError("method audit result phase timings must be finite and nonnegative")
    if not math.isclose(timing["total"], result["elapsed_seconds"], rel_tol=1e-8, abs_tol=1e-9):
        raise ValueError("method audit total timing does not match elapsed_seconds")
    phase_sum = sum(timing[key] for key in expected_fields - {"total"})
    if phase_sum > timing["total"] + 1e-6:
        raise ValueError("method audit phase timings exceed total timing")


def _validate_source_hashes(result: Mapping[str, Any]) -> dict[str, str]:
    hashes = result.get("source_hashes")
    if not isinstance(hashes, Mapping) or set(hashes) != _SOURCE_HASH_FIELDS:
        raise ValueError("method audit result source_hashes is incomplete or has unknown entries")
    validated = {key: _digest(hashes[key], f"source_hashes.{key}") for key in sorted(_SOURCE_HASH_FIELDS)}
    source_sha256 = _digest(result.get("source_sha256"), "source_sha256")
    if source_sha256 != validated["nova/experiments/method_sensitivity.py"]:
        raise ValueError("source_sha256 does not match the method_sensitivity source hash")
    return validated


def _require_exact_keys(value: Any, expected: set[str] | frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError(f"{label} does not match the frozen schema")
    return value


def _validate_aggregate_shape(result: Mapping[str, Any]) -> None:
    arms = _require_exact_keys(result.get("arms"), set(ARM_ORDER), "method audit arms")
    arm_keys = {"groups_summary", "delta", "resampling_interval", "scientific_status", "quality_flags"}
    group_keys = {"n_total", "n_observed", "n_pass", "coverage", "observed_rate"}
    arm_quality_keys = {
        "minimum_sample_and_coverage_pass",
        "endpoint_non_degenerate",
        "interval_contains_zero",
        "paired_scope_conditional_only",
        *FAMILY_ORDER,
    }
    family_quality_keys = {
        "minimum_evaluable_count_pass",
        "minimum_coverage_pass",
        "endpoint_has_pass_and_fail",
    }
    for arm_name in ARM_ORDER:
        arm = _require_exact_keys(arms[arm_name], arm_keys, f"method arm {arm_name}")
        groups = _require_exact_keys(arm["groups_summary"], set(FAMILY_ORDER), f"method arm {arm_name} groups")
        for family in FAMILY_ORDER:
            _require_exact_keys(groups[family], group_keys, f"method arm {arm_name} {family} summary")
        flags = _require_exact_keys(arm["quality_flags"], arm_quality_keys, f"method arm {arm_name} quality flags")
        for family in FAMILY_ORDER:
            _require_exact_keys(flags[family], family_quality_keys, f"method arm {arm_name} {family} quality flags")

    contrast = _require_exact_keys(
        result.get("paired_method_change"),
        {"groups_summary", "delta", "resampling_interval", "scientific_status", "quality_flags"},
        "paired method contrast",
    )
    contrast_groups = _require_exact_keys(
        contrast["groups_summary"], set(FAMILY_ORDER), "paired method contrast groups",
    )
    contrast_group_keys = {
        "n_paired", "n_opt_pass", "n_mbj_pass", "n_gained", "n_lost", "mean_change", "resampling_interval",
    }
    for family in FAMILY_ORDER:
        _require_exact_keys(contrast_groups[family], contrast_group_keys, f"paired method contrast {family}")
    contrast_flags = _require_exact_keys(
        contrast["quality_flags"],
        {
            "minimum_paired_rows_pass",
            "paired_differences_nonconstant",
            "interval_contains_zero",
            "coverage_limits_generalization_to_all_eligible",
            *FAMILY_ORDER,
        },
        "paired method contrast quality flags",
    )
    for family in FAMILY_ORDER:
        _require_exact_keys(
            contrast_flags[family],
            {"minimum_paired_rows_pass", "paired_differences_constant"},
            f"paired method contrast {family} quality flags",
        )

    _require_exact_keys(result.get("subset_shift"), set(FAMILY_ORDER), "method subset shift")
    transition_keys = {"pass_to_pass", "pass_to_fail", "fail_to_pass", "fail_to_fail"}
    transitions = _require_exact_keys(result.get("transitions"), set(FAMILY_ORDER), "method transitions")
    for family in FAMILY_ORDER:
        _require_exact_keys(transitions[family], transition_keys, f"method transitions {family}")
    _require_exact_keys(result.get("candidate_counts"), set(CANDIDATE_LABELS), "method candidate counts")
    counts_by_family = _require_exact_keys(
        result.get("candidate_counts_by_family"), set(FAMILY_ORDER), "method candidate counts by family",
    )
    for family in FAMILY_ORDER:
        _require_exact_keys(counts_by_family[family], set(CANDIDATE_LABELS), f"method candidate counts {family}")


def _same_number(actual: Any, expected: Any, label: str) -> None:
    if expected is None:
        if actual is not None:
            raise ValueError(f"parent Result {label} does not match method audit OPT arm")
        return
    if not _is_finite_number(actual) or not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"parent Result {label} does not match method audit OPT arm")


def _validate_parent_opt_arm(parent_result: Result, opt_all: Mapping[str, Any]) -> None:
    """Require the extension's all-OPT projection to reproduce the parent Result."""
    if parent_result.scientific_status != opt_all.get("scientific_status"):
        raise ValueError("parent Result scientific_status does not match method audit opt_all")
    _same_number(parent_result.delta, opt_all.get("delta"), "delta")
    parent_interval = parent_result.resampling_interval
    arm_interval = opt_all.get("resampling_interval")
    if parent_interval is None or arm_interval is None or len(parent_interval) != 2 or len(arm_interval) != 2:
        if parent_interval != arm_interval:
            raise ValueError("parent Result resampling_interval does not match method audit opt_all")
    else:
        for index, label in enumerate(("resampling_interval.lower", "resampling_interval.upper")):
            _same_number(parent_interval[index], arm_interval[index], label)

    summaries = {item.group: item for item in parent_result.groups_summary}
    if set(summaries) != set(FAMILY_ORDER):
        raise ValueError("parent Result must summarize both frozen families")
    opt_groups = opt_all["groups_summary"]
    for family in FAMILY_ORDER:
        expected = opt_groups[family]
        actual = summaries[family]
        for key in ("n_total", "n_observed", "n_pass"):
            if getattr(actual, key) != expected[key]:
                raise ValueError(f"parent Result {family} {key} does not match method audit opt_all")
        for key in ("coverage", "observed_rate"):
            _same_number(getattr(actual, key), expected[key], f"{family}.{key}")
        n_total = expected["n_total"]
        n_observed = expected["n_observed"]
        n_pass = expected["n_pass"]
        missing_lower = n_pass / n_total if n_total else None
        missing_upper = (n_pass + n_total - n_observed) / n_total if n_total else None
        _same_number(actual.missing_lower, missing_lower, f"{family}.missing_lower")
        _same_number(actual.missing_upper, missing_upper, f"{family}.missing_upper")

    oxide = summaries["oxide"]
    chalcogenide = summaries["chalcogenide"]
    expected_missing = None
    if all(value is not None for value in (
        oxide.missing_lower,
        oxide.missing_upper,
        chalcogenide.missing_lower,
        chalcogenide.missing_upper,
    )):
        expected_missing = (
            chalcogenide.missing_lower - oxide.missing_upper,
            chalcogenide.missing_upper - oxide.missing_lower,
        )
    actual_missing = parent_result.missingness_interval
    if expected_missing is None:
        if actual_missing is not None:
            raise ValueError("parent Result missingness_interval does not match OPT counts")
    elif actual_missing is None or len(actual_missing) != 2:
        raise ValueError("parent Result missingness_interval is missing")
    else:
        _same_number(actual_missing[0], expected_missing[0], "missingness_interval.lower")
        _same_number(actual_missing[1], expected_missing[1], "missingness_interval.upper")


def _validate_science_payload(
    request: Mapping[str, Any],
    audit_output: Mapping[str, Any],
    protocol: Mapping[str, Any],
    protocol_sha256: str,
) -> tuple[dict[str, Any], list[Mapping[str, Any]], dict[str, str]]:
    if not isinstance(audit_output, Mapping):
        raise TypeError("audit_output must be a mapping")
    if set(audit_output) != {"audit_id", "result", "audit_rows"}:
        raise ValueError("audit_output must contain only audit_id, result, and audit_rows")
    if audit_output.get("audit_id") != request["audit_id"]:
        raise ValueError("audit_output audit_id does not match its registered request")
    result_value = audit_output.get("result")
    if not isinstance(result_value, Mapping):
        raise ValueError("audit_output result must be an object")
    result = dict(result_value)
    fixed_metadata = {
        "schema_version": 1,
        "execution_status": "success",
        "template": "method_sensitivity",
        "split": "discovery",
        "dataset_sha256": protocol.get("dataset_sha256"),
        "protocol_sha256": protocol_sha256,
        "parent_protocol_sha256": protocol.get("parent_protocol_sha256"),
        "representative_compositions_csv_sha256": protocol.get("representative_compositions_csv_sha256"),
        "split_assignment_sha256": protocol.get("split_assignment_sha256"),
        "selection_mode": "human_selected",
        "no_new_model_calls": True,
        "interpretation_scope": _INTERPRETATION_SCOPE,
    }
    for key, expected in fixed_metadata.items():
        if result.get(key) != expected:
            raise ValueError(f"method audit result {key} does not match its frozen metadata")
    arms = result.get("arms")
    if not isinstance(arms, Mapping) or set(arms) != set(ARM_ORDER):
        raise ValueError("method audit result must contain exactly the three frozen arms")
    if request["dataset_sha256"] != protocol.get("dataset_sha256"):
        raise ValueError("method audit request dataset hash does not match the frozen protocol")
    if request["protocol_sha256"] != protocol_sha256:
        raise ValueError("method audit request protocol hash does not match the frozen protocol")

    _validate_runtime_fields(result)
    source_hashes = _validate_source_hashes(result)
    rows_value = audit_output.get("audit_rows")
    if not isinstance(rows_value, list):
        raise ValueError("audit_output audit_rows must be a list")
    rows = _validate_rows(rows_value)
    _validate_aggregate_shape(result)
    _validate_result(result)
    _validate_row_aggregates(result, rows)
    for index, row in enumerate(rows):
        expected_reason = method_sensitivity._reason(
            row["ehull_valid"], row["ehull_ev_atom"], row["opt_gap_ev"], row["mbj_gap_ev"],
        )
        expected_next = method_sensitivity._next_validation(row["candidate_label"])
        if row["reason"] != expected_reason:
            raise ValueError(f"audit row {index} reason does not match frozen method rules")
        if row["next_validation"] != expected_next:
            raise ValueError(f"audit row {index} next_validation does not match frozen method rules")
    n_eligible = result.get("n_eligible")
    n_shortlisted = result.get("n_shortlisted")
    if isinstance(n_eligible, bool) or not isinstance(n_eligible, int) or n_eligible != len(rows):
        raise ValueError("method audit n_eligible does not match validated audit rows")
    candidate_rows = [row for row in rows if row["shortlisted"]]
    if isinstance(n_shortlisted, bool) or not isinstance(n_shortlisted, int) or n_shortlisted != len(candidate_rows):
        raise ValueError("method audit n_shortlisted does not match candidate rows")
    return result, rows, source_hashes


def build_method_evidence(
    request: Mapping[str, Any],
    audit_output: Mapping[str, Any],
    parent_result: Result | Mapping[str, Any],
    parent_spec: ExperimentSpec | Mapping[str, Any],
) -> dict[str, Any]:
    """Build validated, portable evidence without retaining the full audit rows.

    The only filesystem read is the frozen extension protocol itself. Prepared
    data, host state, and scientific execution are outside this builder.
    """
    canonical_request = _request_body(request)
    request_sha256 = _sha256(_canonical_json(canonical_request).encode("utf-8"))
    spec = _coerce_parent_spec(parent_spec)
    parent = _coerce_parent_result(parent_result)
    protocol, protocol_sha256 = method_sensitivity._read_method_protocol()
    _validate_parent(canonical_request, protocol, parent, spec)
    result, rows, source_hashes = _validate_science_payload(
        canonical_request, audit_output, protocol, protocol_sha256,
    )
    _validate_parent_opt_arm(parent, result["arms"]["opt_all"])

    candidates = [
        {key: row[key] for key in _CANDIDATE_FIELDS}
        for row in rows
        if row["shortlisted"]
    ]
    protocol_record = {
        key: value for key, value in protocol.items()
        if key != "created_at_utc"
    }
    science_result = {
        key: result[key]
        for key in (
            "schema_version",
            "template",
            "split",
            "dataset_sha256",
            "parent_protocol_sha256",
            "protocol_sha256",
            "representative_compositions_csv_sha256",
            "split_assignment_sha256",
            "interpretation_scope",
            "no_new_model_calls",
            "arms",
            "subset_shift",
            "paired_method_change",
            "transitions",
            "candidate_counts",
            "candidate_counts_by_family",
            "n_eligible",
            "n_shortlisted",
        )
    }
    science_result["candidates"] = candidates
    science_result["quality_scope"] = {
        "status_scope": "Each arm and the paired method contrast carry their own frozen status.",
        "overall_scientific_status": None,
        "missingness_bounds": None,
        "missingness_note": "No method-audit missingness bounds are computed or inferred.",
    }

    return {
        "schema_version": 1,
        "artifact_type": "nova.method_evidence.v1",
        "request": {
            **canonical_request,
            "request_sha256": request_sha256,
        },
        "registered_execution": {
            "mode": "registered_host_execution",
            "audit_id": canonical_request["audit_id"],
            "run_id": canonical_request["run_id"],
        },
        "parent": {
            "result_id": parent.result_id,
            "experiment_id": spec.experiment_id,
            "spec_sha256": spec.sha256,
            "dataset_sha256": parent.dataset_sha256,
        },
        "frozen_protocol": protocol_record,
        "provenance": {
            "scientific_executor": {
                "selection_mode": result["selection_mode"],
                "no_new_model_calls": result["no_new_model_calls"],
                "no_new_model_calls_scope": "scientific_executor_only",
                "source_sha256": result["source_sha256"],
                "source_hashes": source_hashes,
            }
        },
        "science_result": science_result,
    }


def build_method_evidence_packet(
    evidence_body: Mapping[str, Any],
    evidence_sha256: str,
) -> dict[str, Any]:
    """Return hash-bound JSON Pointer citations into a canonical evidence body.

    The digest covers canonical JSON plus one final LF, matching the immutable
    artifact writer convention. The body never contains its own digest.
    """
    if not isinstance(evidence_body, Mapping) or evidence_body.get("artifact_type") != "nova.method_evidence.v1":
        raise ValueError("evidence_body must be a nova.method_evidence.v1 object")
    digest = _digest(evidence_sha256, "evidence_sha256")
    canonical = (_canonical_json(dict(evidence_body)) + "\n").encode("utf-8")
    if _sha256(canonical) != digest:
        raise ValueError("evidence_sha256 does not match canonical evidence body bytes")
    science = evidence_body.get("science_result")
    if not isinstance(science, Mapping):
        raise ValueError("evidence body science_result is missing")
    arms = science.get("arms")
    if not isinstance(arms, Mapping) or set(arms) != set(ARM_ORDER):
        raise ValueError("evidence body must contain all frozen method arms")
    if "paired_method_change" not in science:
        raise ValueError("evidence body paired_method_change is missing")
    candidates = science.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("evidence body candidates must be a list")

    references = [
        {
            "ref_id": f"method-arm-{arm}",
            "kind": "method_arm",
            "json_pointer": f"/science_result/arms/{arm}",
            "evidence_sha256": digest,
        }
        for arm in ARM_ORDER
    ]
    references.append({
        "ref_id": "paired-method-change",
        "kind": "paired_method_change",
        "json_pointer": "/science_result/paired_method_change",
        "evidence_sha256": digest,
    })
    for ref_id, pointer, kind in (
        ("candidate-counts", "/science_result/candidate_counts", "candidate_counts"),
        ("candidate-counts-by-family", "/science_result/candidate_counts_by_family", "candidate_counts_by_family"),
        ("subset-shift", "/science_result/subset_shift", "subset_shift"),
        ("transitions", "/science_result/transitions", "transitions"),
        ("registered-request", "/request", "registered_request"),
        ("parent-result-link", "/parent", "parent_result_linkage"),
    ):
        references.append({
            "ref_id": ref_id,
            "kind": kind,
            "json_pointer": pointer,
            "evidence_sha256": digest,
        })
    seen_jids: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("jid"), str) or not candidate["jid"]:
            raise ValueError(f"evidence candidate {index} has no JID")
        if candidate["jid"] in seen_jids:
            raise ValueError("evidence body has duplicate candidate JIDs")
        seen_jids.add(candidate["jid"])
        references.append({
            "ref_id": f"method-candidate-{index}",
            "kind": "candidate",
            "jid": candidate["jid"],
            "json_pointer": f"/science_result/candidates/{index}",
            "evidence_sha256": digest,
        })
    return {
        "schema_version": 1,
        "artifact_type": "nova.method_evidence_packet.v1",
        "evidence_artifact_type": evidence_body["artifact_type"],
        "evidence_sha256": digest,
        "references": references,
    }


__all__ = ["build_method_evidence", "build_method_evidence_packet"]
