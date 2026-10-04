"""Build and validate a bounded review of completed method-audit evidence.

This module is deliberately pure: it does not read files, run science, call a
model, or authorize an action. It binds a review to one canonical evidence
body and checks every echoed fact and citation against that body's packet.
Free-text assessment language is bounded but cannot be semantically validated;
passing validation does not establish reviewer independence or scientific
correctness beyond the exact source facts and structural rules checked here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from nova.method_audit_report import ARM_ORDER, CANDIDATE_LABELS, FAMILY_ORDER, _validate_result
from nova.method_evidence import build_method_evidence_packet


_INPUT_TYPE = "nova.method_review_input.v1"
_EVIDENCE_TYPE = "nova.method_evidence.v1"
_PACKET_TYPE = "nova.method_evidence_packet.v1"
_ACTIONS = ("stop", "threshold_sensitivity")
_ARM_STATUSES = ("data_limited", "inconclusive", "supported_in_snapshot", "reversed_in_snapshot")
_CHANGE_STATUSES = ("data_limited", "inconclusive", "direction_positive", "direction_negative")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT_LIMIT = 600

_BODY_KEYS = {
    "schema_version", "artifact_type", "request", "registered_execution",
    "parent", "frozen_protocol", "provenance", "science_result",
}
_SCIENCE_KEYS = {
    "schema_version", "template", "split", "dataset_sha256",
    "parent_protocol_sha256", "protocol_sha256",
    "representative_compositions_csv_sha256", "split_assignment_sha256",
    "interpretation_scope", "no_new_model_calls", "arms", "subset_shift",
    "paired_method_change", "transitions", "candidate_counts",
    "candidate_counts_by_family", "n_eligible", "n_shortlisted", "candidates",
    "quality_scope",
}
_CANDIDATE_KEYS = {
    "family", "jid", "reduced_formula", "opt_gap_ev", "mbj_gap_ev",
    "ehull_ev_atom", "opt_status", "mbj_status", "candidate_label", "reason",
    "next_validation",
}
_ARM_KEYS = {"groups_summary", "delta", "resampling_interval", "scientific_status", "quality_flags"}
_GROUP_KEYS = {"n_total", "n_observed", "n_pass", "coverage", "observed_rate"}
_CONTRAST_GROUP_KEYS = {
    "mean_change", "n_gained", "n_lost", "n_mbj_pass", "n_opt_pass",
    "n_paired", "resampling_interval",
}
_LIMITATIONS = [
    {
        "code": "same_representative_pairing",
        "statement": "OPT-paired and MBJ-paired comparisons use the same representatives; they are not independent samples.",
    },
    {
        "code": "subset_only_scope",
        "statement": "The method comparison covers only the observed subset in the discovery split and is conditional on that subset.",
    },
    {
        "code": "mbj_not_ground_truth",
        "statement": "MBJ is another computational method, not ground truth.",
    },
    {
        "code": "method_contrast_not_replication",
        "statement": "The paired method contrast measures method sensitivity and is not independent replication.",
    },
    {
        "code": "no_new_material_discovery",
        "statement": "The method audit does not establish discovery of new materials.",
    },
    {
        "code": "no_holdout_authorization",
        "statement": "Nothing in this review authorizes opening, analyzing, or executing on the holdout split.",
    },
]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256((_canonical_json(value) + "\n").encode("utf-8")).hexdigest()


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA256 digest")
    return value


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _number_or_null(value: Any, label: str) -> None:
    if value is not None and not _is_number(value):
        raise ValueError(f"{label} must be a finite number or null")


def _count(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")


def _text(value: Any, label: str, *, limit: int = _TEXT_LIMIT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{label} must be nonempty text no longer than {limit} characters")
    return value


def _exact_keys(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{label} does not match the expected schema")
    return value


def _same_json(left: Any, right: Any) -> bool:
    try:
        return _canonical_json(left) == _canonical_json(right)
    except (TypeError, ValueError):
        return False


def _fact_equal(left: Any, right: Any) -> bool:
    """Compare JSON facts numerically exactly while keeping booleans distinct."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if _is_number(left) and _is_number(right):
        return left == right
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        return (
            isinstance(left, Mapping)
            and isinstance(right, Mapping)
            and set(left) == set(right)
            and all(_fact_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_fact_equal(a, b) for a, b in zip(left, right))
        )
    return type(left) is type(right) and left == right


def _candidate_label(opt_status: str, mbj_status: str) -> str:
    by_status = {
        ("pass", "pass"): "passes_both_methods",
        ("pass", "fail"): "opt_only",
        ("fail", "pass"): "mbj_only",
        ("pass", "unknown"): "opt_pass_mbj_unknown",
        ("unknown", "pass"): "mbj_pass_opt_unknown",
        ("fail", "fail"): "neither_passes",
        ("unknown", "unknown"): "insufficient_evidence",
    }
    return by_status.get((opt_status, mbj_status), "no_current_pass_incomplete_evidence")


def _validate_candidate_source(candidate: Any, index: int) -> None:
    row = _exact_keys(candidate, _CANDIDATE_KEYS, f"candidate {index}")
    if row["family"] not in FAMILY_ORDER:
        raise ValueError(f"candidate {index} has an unknown family")
    _text(row["jid"], f"candidate {index} JID", limit=100)
    _text(row["reduced_formula"], f"candidate {index} formula", limit=100)
    for key in ("opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom"):
        _number_or_null(row[key], f"candidate {index} {key}")
    for key in ("opt_status", "mbj_status"):
        if row[key] not in {"pass", "fail", "unknown"}:
            raise ValueError(f"candidate {index} {key} is invalid")
    if row["candidate_label"] not in CANDIDATE_LABELS:
        raise ValueError(f"candidate {index} has an unknown category")
    for key in ("reason", "next_validation"):
        _text(row[key], f"candidate {index} {key}", limit=500)

    # Unknown means the gap or the hull input is absent. A missing comparator
    # remains unknown and is never coerced to failure.
    for gap_key, status_key in (("opt_gap_ev", "opt_status"), ("mbj_gap_ev", "mbj_status")):
        missing = row[gap_key] is None or row["ehull_ev_atom"] is None
        if missing != (row[status_key] == "unknown"):
            raise ValueError(f"candidate {index} {status_key} contradicts null versus failure semantics")
    if row["candidate_label"] != _candidate_label(row["opt_status"], row["mbj_status"]):
        raise ValueError(f"candidate {index} category does not match its two method statuses")


def _validate_body_structure(body: Any) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    body = _exact_keys(body, _BODY_KEYS, "evidence body")
    if isinstance(body["schema_version"], bool) or body["schema_version"] != 1:
        raise ValueError("evidence body schema_version must be 1")
    if body["artifact_type"] != _EVIDENCE_TYPE:
        raise ValueError("evidence body artifact_type is invalid")

    request_keys = {
        "schema_version", "audit_id", "run_id", "parent_result_id",
        "parent_experiment_id", "parent_spec_sha256", "dataset_sha256",
        "protocol_sha256", "request_sha256",
    }
    request = _exact_keys(body["request"], request_keys, "evidence request")
    if isinstance(request["schema_version"], bool) or request["schema_version"] != 1:
        raise ValueError("evidence request schema_version must be 1")
    request_core = {key: value for key, value in request.items() if key != "request_sha256"}
    for key, value in request_core.items():
        if key == "schema_version":
            continue
        _text(value, f"evidence request {key}", limit=200)
    _digest(request["parent_spec_sha256"], "request.parent_spec_sha256")
    _digest(request["dataset_sha256"], "request.dataset_sha256")
    _digest(request["protocol_sha256"], "request.protocol_sha256")
    if request["request_sha256"] != hashlib.sha256(_canonical_json(request_core).encode("utf-8")).hexdigest():
        raise ValueError("evidence request digest does not match its canonical fields")

    parent = _exact_keys(body["parent"], {"result_id", "experiment_id", "spec_sha256", "dataset_sha256"}, "parent linkage")
    expected_parent = {
        "result_id": request["parent_result_id"],
        "experiment_id": request["parent_experiment_id"],
        "spec_sha256": request["parent_spec_sha256"],
        "dataset_sha256": request["dataset_sha256"],
    }
    if not _same_json(parent, expected_parent):
        raise ValueError("evidence parent linkage does not match the registered request")

    execution = _exact_keys(body["registered_execution"], {"mode", "audit_id", "run_id"}, "registered execution")
    if execution != {
        "mode": "registered_host_execution",
        "audit_id": request["audit_id"],
        "run_id": request["run_id"],
    }:
        raise ValueError("registered execution does not match the request")

    protocol = body["frozen_protocol"]
    if not isinstance(protocol, Mapping):
        raise ValueError("frozen protocol must be an object")
    protocol_keys = {
        "schema_version", "protocol_id", "template", "split", "dataset_sha256",
        "parent_protocol_sha256", "representative_compositions_csv_sha256",
        "split_assignment_sha256", "groups", "gap_window_ev", "ehull_max_ev_atom",
        "bootstrap_repeats", "seed", "arms", "methods", "contrasts", "pairing",
        "measurement", "quality", "candidate_labels", "candidate_rules",
        "next_validation_rules", "interpretation", "registration_context",
        "representatives", "sources", "holdout_execution_allowed",
    }
    _exact_keys(protocol, protocol_keys, "frozen protocol")
    if (
        isinstance(protocol["schema_version"], bool)
        or protocol["schema_version"] != 1
        or protocol["template"] != "method_sensitivity"
        or protocol["split"] != "discovery"
        or protocol["dataset_sha256"] != request["dataset_sha256"]
        or protocol["parent_protocol_sha256"] != body["science_result"].get("parent_protocol_sha256")
        or protocol["representative_compositions_csv_sha256"]
        != body["science_result"].get("representative_compositions_csv_sha256")
        or protocol["split_assignment_sha256"] != body["science_result"].get("split_assignment_sha256")
        or protocol["holdout_execution_allowed"] is not False
    ):
        raise ValueError("frozen protocol does not describe this discovery-only method audit")
    for key in ("dataset_sha256", "parent_protocol_sha256", "representative_compositions_csv_sha256", "split_assignment_sha256"):
        _digest(protocol[key], f"frozen_protocol.{key}")

    provenance = _exact_keys(body["provenance"], {"scientific_executor"}, "evidence provenance")
    executor = _exact_keys(
        provenance["scientific_executor"],
        {"selection_mode", "no_new_model_calls", "no_new_model_calls_scope", "source_sha256", "source_hashes"},
        "scientific executor provenance",
    )
    if (
        executor["selection_mode"] != "human_selected"
        or executor["no_new_model_calls"] is not True
        or executor["no_new_model_calls_scope"] != "scientific_executor_only"
    ):
        raise ValueError("scientific executor provenance is invalid")
    source_hashes = _exact_keys(
        executor["source_hashes"],
        {"nova/experiments/method_sensitivity.py", "nova/statistics.py", "nova/data/pipeline.py"},
        "source hashes",
    )
    for key, value in source_hashes.items():
        _digest(value, f"source_hashes.{key}")
    if executor["source_sha256"] != source_hashes["nova/experiments/method_sensitivity.py"]:
        raise ValueError("scientific executor source hash does not match its source inventory")

    science = _exact_keys(body["science_result"], _SCIENCE_KEYS, "science_result")
    for key, expected in (("schema_version", 1), ("template", "method_sensitivity"), ("split", "discovery")):
        if isinstance(science[key], bool) or science[key] != expected:
            raise ValueError(f"science_result.{key} is invalid")
    if science["no_new_model_calls"] is not True:
        raise ValueError("scientific executor must state no_new_model_calls=true")
    _text(science["interpretation_scope"], "interpretation_scope", limit=300)
    for key, expected in (
        ("dataset_sha256", request["dataset_sha256"]),
        ("protocol_sha256", request["protocol_sha256"]),
        ("parent_protocol_sha256", protocol["parent_protocol_sha256"]),
        ("representative_compositions_csv_sha256", protocol["representative_compositions_csv_sha256"]),
        ("split_assignment_sha256", protocol["split_assignment_sha256"]),
    ):
        if science[key] != expected:
            raise ValueError(f"science_result.{key} does not match the registered protocol")
        _digest(science[key], f"science_result.{key}")
    if science["quality_scope"] != {
        "status_scope": "Each arm and the paired method contrast carry their own frozen status.",
        "overall_scientific_status": None,
        "missingness_bounds": None,
        "missingness_note": "No method-audit missingness bounds are computed or inferred.",
    }:
        raise ValueError("quality_scope must preserve separate arm and method-change statuses")

    _count(science["n_eligible"], "science_result.n_eligible")
    _count(science["n_shortlisted"], "science_result.n_shortlisted")
    if science["n_shortlisted"] > science["n_eligible"]:
        raise ValueError("n_shortlisted cannot exceed n_eligible")

    arms = _exact_keys(science["arms"], set(ARM_ORDER), "science_result.arms")
    for arm_name in ARM_ORDER:
        arm = _exact_keys(arms[arm_name], _ARM_KEYS, f"arm {arm_name}")
        if arm["scientific_status"] not in _ARM_STATUSES:
            raise ValueError(f"arm {arm_name} has an invalid scientific status")
        _number_or_null(arm["delta"], f"arm {arm_name} delta")
        _interval(arm["resampling_interval"], f"arm {arm_name} interval")
        groups = _exact_keys(arm["groups_summary"], set(FAMILY_ORDER), f"arm {arm_name} groups")
        for family in FAMILY_ORDER:
            group = _exact_keys(groups[family], _GROUP_KEYS, f"arm {arm_name} {family} summary")
            _count(group["n_total"], f"arm {arm_name} {family} n_total")
            _count(group["n_observed"], f"arm {arm_name} {family} n_observed")
            _count(group["n_pass"], f"arm {arm_name} {family} n_pass")
            _number_or_null(group["coverage"], f"arm {arm_name} {family} coverage")
            _number_or_null(group["observed_rate"], f"arm {arm_name} {family} observed_rate")

    change = _exact_keys(
        science["paired_method_change"], _ARM_KEYS, "paired method change"
    )
    if change["scientific_status"] not in _CHANGE_STATUSES:
        raise ValueError("paired method change has an invalid scientific status")
    _number_or_null(change["delta"], "paired method change delta")
    _interval(change["resampling_interval"], "paired method change interval")
    change_groups = _exact_keys(change["groups_summary"], set(FAMILY_ORDER), "paired method change groups")
    for family in FAMILY_ORDER:
        group = _exact_keys(change_groups[family], _CONTRAST_GROUP_KEYS, f"method change {family} summary")
        for key in ("n_gained", "n_lost", "n_mbj_pass", "n_opt_pass", "n_paired"):
            _count(group[key], f"method change {family} {key}")
        _number_or_null(group["mean_change"], f"method change {family} mean_change")
        _interval(group["resampling_interval"], f"method change {family} interval")

    # This existing pure validator checks aggregate count/rate/interval
    # relationships; no data, protocol file, model, or runtime state is read.
    _validate_result(science)

    candidates = science["candidates"]
    if not isinstance(candidates, list):
        raise ValueError("science_result.candidates must be a list")
    if len(candidates) != science["n_shortlisted"]:
        raise ValueError("shortlisted candidate records do not match n_shortlisted")
    seen_jids: set[str] = set()
    for index, candidate in enumerate(candidates):
        _validate_candidate_source(candidate, index)
        if candidate["jid"] in seen_jids:
            raise ValueError("science_result.candidates has duplicate JIDs")
        seen_jids.add(candidate["jid"])
        if candidate["opt_status"] != "pass" and candidate["mbj_status"] != "pass":
            raise ValueError(f"candidate {index} is not a shortlisted candidate")

    counts = _exact_keys(science["candidate_counts"], set(CANDIDATE_LABELS), "candidate_counts")
    for label, value in counts.items():
        _count(value, f"candidate_counts.{label}")
    if sum(counts.values()) != science["n_eligible"]:
        raise ValueError("candidate_counts do not sum to n_eligible")
    by_family = _exact_keys(science["candidate_counts_by_family"], set(FAMILY_ORDER), "candidate_counts_by_family")
    for family in FAMILY_ORDER:
        family_counts = _exact_keys(by_family[family], set(CANDIDATE_LABELS), f"candidate_counts_by_family.{family}")
        for label, value in family_counts.items():
            _count(value, f"candidate_counts_by_family.{family}.{label}")
    for label in CANDIDATE_LABELS:
        if sum(by_family[family][label] for family in FAMILY_ORDER) != counts[label]:
            raise ValueError(f"family candidate counts do not reconcile for {label}")

    # References for the remaining fixed evidence fields must remain present
    # in the source body even though the compact review does not export them.
    for key in ("subset_shift", "transitions"):
        value = _exact_keys(science[key], set(FAMILY_ORDER), f"science_result.{key}")
        if key == "subset_shift":
            for family in FAMILY_ORDER:
                _number_or_null(value[family], f"subset_shift.{family}")
        else:
            for family in FAMILY_ORDER:
                row = _exact_keys(value[family], {"fail_to_fail", "fail_to_pass", "pass_to_fail", "pass_to_pass"}, f"transitions.{family}")
                for field, count in row.items():
                    _count(count, f"transitions.{family}.{field}")
    return request, science


def _interval(value: Any, label: str) -> None:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be a two-value interval")
    if not all(_is_number(item) for item in value):
        raise ValueError(f"{label} endpoints must be finite numbers")
    if value[0] > value[1]:
        raise ValueError(f"{label} lower endpoint exceeds its upper endpoint")


def _validate_packet(packet: Any, body: Mapping[str, Any]) -> tuple[str, dict[str, Mapping[str, Any]]]:
    if not isinstance(packet, Mapping):
        raise ValueError("evidence packet must be an object")
    packet_keys = {
        "schema_version", "artifact_type", "evidence_artifact_type", "evidence_sha256", "references",
    }
    allowed = packet_keys | {
        "evidence_file", "evidence_root_json_pointer", "parent_result_ref", "selection_ref",
    }
    if set(packet) - allowed or packet_keys - set(packet):
        raise ValueError("evidence packet has missing or unsupported fields")
    for key in ("evidence_file",):
        if key in packet:
            _text(packet[key], f"packet.{key}", limit=255)
    if "evidence_root_json_pointer" in packet and packet["evidence_root_json_pointer"] != "":
        raise ValueError("packet.evidence_root_json_pointer must identify the evidence root")
    for key in ("parent_result_ref", "selection_ref"):
        if key in packet and not isinstance(packet[key], Mapping):
            raise ValueError(f"packet.{key} must be an object when supplied")

    digest = _digest(packet["evidence_sha256"], "packet.evidence_sha256")
    if digest != _canonical_digest(dict(body)):
        raise ValueError("packet evidence digest does not match the canonical body")
    regenerated = build_method_evidence_packet(body, digest)
    for key in packet_keys:
        if not _same_json(packet[key], regenerated[key]):
            raise ValueError(f"packet {key} does not match the regenerated core inventory")

    reference_map: dict[str, Mapping[str, Any]] = {}
    for ref in regenerated["references"]:
        reference_map[ref["ref_id"]] = ref
    return digest, reference_map


def _source_reference(reference_map: Mapping[str, Mapping[str, Any]], ref_id: str) -> dict[str, Any]:
    try:
        return dict(reference_map[ref_id])
    except KeyError:
        raise ValueError(f"evidence packet is missing required reference {ref_id}") from None


def _default_candidate_sample(candidates: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    first_by_category: dict[str, Mapping[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda row: (row["candidate_label"], row["jid"])):
        first_by_category.setdefault(candidate["candidate_label"], candidate)
    return [first_by_category[key] for key in sorted(first_by_category)]


def _input_payload_without_digest(review_input: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in review_input.items() if key != "review_input_sha256"}


def _input_digest(review_input: Mapping[str, Any]) -> str:
    return _canonical_digest(_input_payload_without_digest(review_input))


def build_method_review_input(
    evidence_body: Mapping[str, Any],
    evidence_packet: Mapping[str, Any],
    *,
    candidate_jids: list[str] | tuple[str, ...] | None = None,
    available_actions: list[str] | tuple[str, ...] = ("stop",),
) -> dict[str, Any]:
    """Create compact, host-bounded facts for reviewing a completed method audit.

    With no explicit JIDs, this exports the first JID per observed category
    after stable category/JID sorting. That is a host-selected sample, not a
    ranking and not an all-candidate review.
    """
    request, science = _validate_body_structure(evidence_body)
    digest, refs = _validate_packet(evidence_packet, evidence_body)

    if not isinstance(available_actions, (list, tuple)):
        raise ValueError("available_actions must be a list or tuple")
    if any(not isinstance(action, str) or action not in _ACTIONS for action in available_actions):
        raise ValueError("available_actions contains an unsupported action")
    if len(set(available_actions)) != len(available_actions):
        raise ValueError("available_actions must not contain duplicates")
    if "stop" not in available_actions:
        raise ValueError("available_actions must always include stop")

    candidates = science["candidates"]
    by_jid = {candidate["jid"]: candidate for candidate in candidates}
    if candidate_jids is None:
        selected = _default_candidate_sample(candidates)
        mode = "host_selected_default_sample"
        policy = "First JID per observed shortlist category, sorted by category label then JID; this is a host-selected sample, not ranking or all-candidate review."
    else:
        if not isinstance(candidate_jids, (list, tuple)) or not candidate_jids:
            raise ValueError("explicit candidate_jids must be a nonempty list or tuple")
        if any(not isinstance(jid, str) or not jid.strip() for jid in candidate_jids):
            raise ValueError("candidate_jids entries must be nonempty JID strings")
        if len(set(candidate_jids)) != len(candidate_jids):
            raise ValueError("candidate_jids must not contain duplicates")
        unknown = [jid for jid in candidate_jids if jid not in by_jid]
        if unknown:
            raise ValueError(f"candidate_jids contains unknown shortlisted JIDs: {unknown}")
        selected = [by_jid[jid] for jid in candidate_jids]
        mode = "host_selected_explicit"
        policy = "Exact candidate JIDs explicitly selected by the host, in supplied order; this is a host-selected review set, not ranking."

    arm_records = []
    for name in ARM_ORDER:
        arm = science["arms"][name]
        arm_records.append({
            "name": name,
            "source_ref": _source_reference(refs, f"method-arm-{name}"),
            "scientific_status": arm["scientific_status"],
            "delta": arm["delta"],
            "resampling_interval": list(arm["resampling_interval"]),
            "quality_flags": copy.deepcopy(arm["quality_flags"]),
            "groups_summary": {
                family: {key: arm["groups_summary"][family][key] for key in (
                    "n_total", "n_observed", "n_pass", "coverage", "observed_rate",
                )}
                for family in FAMILY_ORDER
            },
        })

    contrast = science["paired_method_change"]
    method_change = {
        "source_ref": _source_reference(refs, "paired-method-change"),
        "scientific_status": contrast["scientific_status"],
        "delta": contrast["delta"],
        "resampling_interval": list(contrast["resampling_interval"]),
        "quality_flags": copy.deepcopy(contrast["quality_flags"]),
        "groups_summary": {
            family: {key: contrast["groups_summary"][family][key] for key in (
                "n_paired", "n_opt_pass", "n_mbj_pass", "n_gained", "n_lost",
                "mean_change", "resampling_interval",
            )}
            for family in FAMILY_ORDER
        },
    }
    candidate_records = []
    for candidate in selected:
        index = next(i for i, row in enumerate(candidates) if row["jid"] == candidate["jid"])
        candidate_records.append({
            "jid": candidate["jid"],
            "source_ref": _source_reference(refs, f"method-candidate-{index}"),
            **{key: candidate[key] for key in (
                "family", "opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom", "opt_status",
                "mbj_status", "candidate_label", "reason", "next_validation",
            )},
        })

    payload = {
        "schema_version": 1,
        "artifact_type": _INPUT_TYPE,
        "evidence_sha256": digest,
        "selection": {
            "mode": mode,
            "policy": policy,
            "total_shortlist_count": science["n_shortlisted"],
            "sampled_count": len(selected),
            "selected_jids": [candidate["jid"] for candidate in selected],
        },
        "available_actions": list(available_actions),
        "scope": {
            "template": "method_sensitivity",
            "split": "discovery",
            "interpretation_scope": science["interpretation_scope"],
            "validator_limit": "Exact facts, citations, required limitations, and allowed actions are checked. Free-text assessments cannot be semantically validated; validation does not establish model independence.",
        },
        "units": {
            "gaps": "eV",
            "ehull_ev_atom": "eV/atom",
            "coverage": "fraction",
            "observed_rate": "fraction",
            "arm_delta_and_interval": "fraction difference",
            "method_change_delta_mean_and_interval": "fraction difference",
        },
        "required_limitations": copy.deepcopy(_LIMITATIONS),
        "action_boundary": {
            "recommendation_is_advisory": True,
            "host_must_independently_gate_action_and_feasibility": True,
            "no_method_rerun_holdout_dft_or_new_spec_authorization": True,
        },
        "arms": arm_records,
        "method_change": method_change,
        "candidates": candidate_records,
    }
    result = {**payload, "review_input_sha256": _canonical_digest(payload)}
    _validate_review_input(result)
    return result


def _validate_review_input(review_input: Any) -> Mapping[str, Any]:
    keys = {
        "schema_version", "artifact_type", "review_input_sha256", "evidence_sha256",
        "selection", "available_actions", "scope", "required_limitations",
        "action_boundary", "arms", "method_change", "candidates", "units",
    }
    value = _exact_keys(review_input, keys, "review input")
    if isinstance(value["schema_version"], bool) or value["schema_version"] != 1 or value["artifact_type"] != _INPUT_TYPE:
        raise ValueError("review input schema identity is invalid")
    _digest(value["evidence_sha256"], "review_input.evidence_sha256")
    _digest(value["review_input_sha256"], "review_input.review_input_sha256")
    if value["review_input_sha256"] != _input_digest(value):
        raise ValueError("review_input_sha256 does not match the canonical review input")

    selection = _exact_keys(
        value["selection"],
        {"mode", "policy", "total_shortlist_count", "sampled_count", "selected_jids"},
        "review selection",
    )
    if selection["mode"] not in {"host_selected_default_sample", "host_selected_explicit"}:
        raise ValueError("review selection mode is invalid")
    _text(selection["policy"], "selection policy", limit=300)
    _count(selection["total_shortlist_count"], "total_shortlist_count")
    _count(selection["sampled_count"], "sampled_count")
    if selection["sampled_count"] < 1 or selection["sampled_count"] > selection["total_shortlist_count"]:
        raise ValueError("sampled_count must be positive and no greater than the shortlist")
    selected_jids = selection["selected_jids"]
    if (
        not isinstance(selected_jids, list)
        or len(selected_jids) != selection["sampled_count"]
        or any(not isinstance(jid, str) or not jid.strip() for jid in selected_jids)
        or len(set(selected_jids)) != len(selected_jids)
    ):
        raise ValueError("selected_jids does not match the disclosed sample count")

    actions = value["available_actions"]
    if (
        not isinstance(actions, list)
        or any(not isinstance(action, str) or action not in _ACTIONS for action in actions)
        or len(set(actions)) != len(actions)
        or "stop" not in actions
    ):
        raise ValueError("review input has invalid available_actions")
    scope = _exact_keys(value["scope"], {"template", "split", "interpretation_scope", "validator_limit"}, "review scope")
    if scope["template"] != "method_sensitivity" or scope["split"] != "discovery":
        raise ValueError("review scope must be the discovery method-sensitivity audit")
    _text(scope["interpretation_scope"], "interpretation_scope", limit=300)
    _text(scope["validator_limit"], "validator_limit", limit=500)
    units = _exact_keys(
        value["units"],
        {"gaps", "ehull_ev_atom", "coverage", "observed_rate", "arm_delta_and_interval", "method_change_delta_mean_and_interval"},
        "review units",
    )
    if units != {
        "gaps": "eV",
        "ehull_ev_atom": "eV/atom",
        "coverage": "fraction",
        "observed_rate": "fraction",
        "arm_delta_and_interval": "fraction difference",
        "method_change_delta_mean_and_interval": "fraction difference",
    }:
        raise ValueError("review input units are invalid")

    boundary = _exact_keys(
        value["action_boundary"],
        {"recommendation_is_advisory", "host_must_independently_gate_action_and_feasibility", "no_method_rerun_holdout_dft_or_new_spec_authorization"},
        "action boundary",
    )
    if any(item is not True for item in boundary.values()):
        raise ValueError("review action boundary must preserve all host gates")
    if not _same_json(value["required_limitations"], _LIMITATIONS):
        raise ValueError("review input has invalid required scientific limitations")

    arms = value["arms"]
    if not isinstance(arms, list) or len(arms) != len(ARM_ORDER):
        raise ValueError("review input must include all three method arms")
    for expected_name, arm in zip(ARM_ORDER, arms):
        arm = _exact_keys(arm, {"name", "source_ref", "scientific_status", "delta", "resampling_interval", "quality_flags", "groups_summary"}, f"review arm {expected_name}")
        if arm["name"] != expected_name or arm["scientific_status"] not in _ARM_STATUSES:
            raise ValueError(f"review input arm {expected_name} identity or status is invalid")
        _source_ref_shape(
            arm["source_ref"], value["evidence_sha256"], f"method-arm-{expected_name}",
            expected_pointer=f"/science_result/arms/{expected_name}",
        )
        _number_or_null(arm["delta"], f"arm {expected_name} delta")
        _interval(arm["resampling_interval"], f"arm {expected_name} interval")
        _validate_arm_quality(arm["quality_flags"], expected_name)
        groups = _exact_keys(arm["groups_summary"], set(FAMILY_ORDER), f"arm {expected_name} groups")
        for family in FAMILY_ORDER:
            group = _exact_keys(groups[family], _GROUP_KEYS, f"arm {expected_name} {family}")
            for key in ("n_total", "n_observed", "n_pass"):
                _count(group[key], f"arm {expected_name} {family} {key}")
            for key in ("coverage", "observed_rate"):
                _number_or_null(group[key], f"arm {expected_name} {family} {key}")

    change = _exact_keys(
        value["method_change"],
        {"source_ref", "scientific_status", "delta", "resampling_interval", "quality_flags", "groups_summary"},
        "review method change",
    )
    if change["scientific_status"] not in _CHANGE_STATUSES:
        raise ValueError("review method-change status is invalid")
    _source_ref_shape(
        change["source_ref"], value["evidence_sha256"], "paired-method-change",
        expected_pointer="/science_result/paired_method_change",
    )
    _number_or_null(change["delta"], "method-change delta")
    _interval(change["resampling_interval"], "method-change interval")
    _validate_change_quality(change["quality_flags"])
    groups = _exact_keys(change["groups_summary"], set(FAMILY_ORDER), "method-change groups")
    for family in FAMILY_ORDER:
        group = _exact_keys(groups[family], _CONTRAST_GROUP_KEYS, f"method-change {family}")
        for key in ("n_paired", "n_opt_pass", "n_mbj_pass", "n_gained", "n_lost"):
            _count(group[key], f"method change {family} {key}")
        _number_or_null(group["mean_change"], f"method change {family} mean_change")
        _interval(group["resampling_interval"], f"method change {family} interval")

    candidates = value["candidates"]
    if not isinstance(candidates, list) or len(candidates) != selection["sampled_count"]:
        raise ValueError("review candidates do not match sampled_count")
    seen: set[str] = set()
    seen_candidate_refs: set[str] = set()
    for candidate in candidates:
        candidate = _exact_keys(
            candidate,
            {"jid", "source_ref", "family", "opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom", "opt_status", "mbj_status", "candidate_label", "reason", "next_validation"},
            "review candidate",
        )
        jid = _text(candidate["jid"], "candidate JID", limit=100)
        if jid in seen:
            raise ValueError("review input contains duplicate candidate JIDs")
        seen.add(jid)
        if candidate["family"] not in FAMILY_ORDER:
            raise ValueError("review input candidate family is invalid")
        candidate_ref = candidate["source_ref"]
        _source_ref_shape(candidate_ref, value["evidence_sha256"], None, jid=jid)
        match = re.fullmatch(r"method-candidate-(\d+)", candidate_ref["ref_id"])
        if not match or candidate_ref["json_pointer"] != f"/science_result/candidates/{match.group(1)}":
            raise ValueError("candidate source reference ID and pointer do not match")
        if candidate_ref["ref_id"] in seen_candidate_refs:
            raise ValueError("review input contains duplicate candidate source references")
        seen_candidate_refs.add(candidate_ref["ref_id"])
        _validate_candidate_source({
            "family": candidate["family"], "jid": jid, "reduced_formula": "review-input",
            "opt_gap_ev": candidate["opt_gap_ev"], "mbj_gap_ev": candidate["mbj_gap_ev"],
            "ehull_ev_atom": candidate["ehull_ev_atom"], "opt_status": candidate["opt_status"],
            "mbj_status": candidate["mbj_status"], "candidate_label": candidate["candidate_label"],
            "reason": candidate["reason"], "next_validation": candidate["next_validation"],
        }, 0)
    if selected_jids != [candidate["jid"] for candidate in candidates]:
        raise ValueError("selected_jids does not match candidate records in input order")
    return value


def _source_ref_shape(
    reference: Any,
    evidence_sha256: str,
    ref_id: str | None,
    *,
    jid: str | None = None,
    expected_pointer: str | None = None,
) -> None:
    expected_keys = {"ref_id", "kind", "json_pointer", "evidence_sha256"}
    if jid is not None:
        expected_keys.add("jid")
    ref = _exact_keys(reference, expected_keys, "source reference")
    if ref["kind"] != ("candidate" if jid is not None else "method_arm" if ref_id and ref_id.startswith("method-arm-") else "paired_method_change"):
        raise ValueError("source reference kind does not match its assessment")
    if ref_id is not None and ref["ref_id"] != ref_id:
        raise ValueError("source reference ID does not match its assessment")
    if jid is not None and ref["jid"] != jid:
        raise ValueError("candidate source reference JID does not match the candidate")
    if ref["evidence_sha256"] != evidence_sha256:
        raise ValueError("source reference evidence digest does not match review input")
    if not isinstance(ref["json_pointer"], str) or not ref["json_pointer"].startswith("/"):
        raise ValueError("source reference JSON Pointer is invalid")
    if expected_pointer is not None and ref["json_pointer"] != expected_pointer:
        raise ValueError("source reference JSON Pointer does not match its evidence field")


def _validate_arm_quality(flags: Any, arm_name: str) -> None:
    flag_keys = {
        "minimum_sample_and_coverage_pass", "endpoint_non_degenerate",
        "interval_contains_zero", "paired_scope_conditional_only", *FAMILY_ORDER,
    }
    flags = _exact_keys(flags, flag_keys, f"arm {arm_name} quality flags")
    for key in flag_keys - set(FAMILY_ORDER):
        if flags[key] is not None and not isinstance(flags[key], bool):
            raise ValueError(f"arm {arm_name} quality flag {key} must be boolean or null")
    family_keys = {
        "minimum_evaluable_count_pass", "minimum_coverage_pass", "endpoint_has_pass_and_fail",
    }
    for family in FAMILY_ORDER:
        family_flags = _exact_keys(flags[family], family_keys, f"arm {arm_name} {family} quality flags")
        for key, value in family_flags.items():
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"arm {arm_name} {family} quality flag {key} must be boolean or null")


def _validate_change_quality(flags: Any) -> None:
    flag_keys = {
        "coverage_limits_generalization_to_all_eligible", "interval_contains_zero",
        "minimum_paired_rows_pass", "paired_differences_nonconstant", *FAMILY_ORDER,
    }
    flags = _exact_keys(flags, flag_keys, "paired method-change quality flags")
    for key in flag_keys - set(FAMILY_ORDER):
        if not isinstance(flags[key], bool):
            raise ValueError(f"method-change quality flag {key} must be boolean")
    family_keys = {"minimum_paired_rows_pass", "paired_differences_constant"}
    for family in FAMILY_ORDER:
        family_flags = _exact_keys(flags[family], family_keys, f"method-change {family} quality flags")
        if any(not isinstance(value, bool) for value in family_flags.values()):
            raise ValueError(f"method-change {family} quality flags must be boolean")


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required if required is not None else list(properties),
        "additionalProperties": False,
    }


def _schema_for_facts(review_input: Mapping[str, Any]) -> dict[str, Any]:
    ref_ids = [arm["source_ref"]["ref_id"] for arm in review_input["arms"]]
    fact_number = {"type": ["number", "null"]}
    interval = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
    group = _object_schema({
        "n_total": {"type": "integer", "minimum": 0},
        "n_observed": {"type": "integer", "minimum": 0},
        "n_pass": {"type": "integer", "minimum": 0},
        "coverage": fact_number,
        "observed_rate": fact_number,
    })
    groups = _object_schema({family: group for family in FAMILY_ORDER})
    arm_schema = _object_schema({
        "arm": {"type": "string", "enum": list(ARM_ORDER)},
        "source_ref_id": {"type": "string", "enum": ref_ids},
        "scientific_status": {"type": "string", "enum": list(_ARM_STATUSES)},
        "delta": fact_number,
        "resampling_interval": interval,
        "groups_summary": groups,
        "assessment": {"type": "string", "minLength": 1, "maxLength": _TEXT_LIMIT},
    })
    change_group = _object_schema({
        "n_paired": {"type": "integer", "minimum": 0},
        "n_opt_pass": {"type": "integer", "minimum": 0},
        "n_mbj_pass": {"type": "integer", "minimum": 0},
        "n_gained": {"type": "integer", "minimum": 0},
        "n_lost": {"type": "integer", "minimum": 0},
        "mean_change": fact_number,
        "resampling_interval": interval,
    })
    method_change = _object_schema({
        "kind": {"type": "string", "const": "paired_method_change"},
        "source_ref_id": {"type": "string", "const": review_input["method_change"]["source_ref"]["ref_id"]},
        "scientific_status": {"type": "string", "enum": list(_CHANGE_STATUSES)},
        "delta": fact_number,
        "resampling_interval": interval,
        "groups_summary": _object_schema({family: change_group for family in FAMILY_ORDER}),
        "assessment": {"type": "string", "minLength": 1, "maxLength": _TEXT_LIMIT},
    })
    candidates = review_input["candidates"]
    candidate_schema = _object_schema({
        "jid": {"type": "string", "enum": [item["jid"] for item in candidates]},
        "source_ref_id": {"type": "string", "enum": [item["source_ref"]["ref_id"] for item in candidates]},
        "family": {"type": "string", "enum": list(FAMILY_ORDER)},
        "opt_gap_ev": fact_number,
        "mbj_gap_ev": fact_number,
        "ehull_ev_atom": fact_number,
        "opt_status": {"type": "string", "enum": ["pass", "fail", "unknown"]},
        "mbj_status": {"type": "string", "enum": ["pass", "fail", "unknown"]},
        "category": {"type": "string", "enum": list(CANDIDATE_LABELS)},
        "next_validation": {"type": "string", "enum": sorted({item["next_validation"] for item in candidates})},
        "assessment": {"type": "string", "minLength": 1, "maxLength": _TEXT_LIMIT},
    })
    recommendation = _object_schema({
        "action": {"type": "string", "enum": list(review_input["available_actions"])},
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string", "enum": (
                ref_ids
                + [review_input["method_change"]["source_ref"]["ref_id"]]
                + [item["source_ref"]["ref_id"] for item in candidates]
            )},
            "minItems": 1,
            "uniqueItems": True,
        },
        "rationale": {"type": "string", "minLength": 1, "maxLength": _TEXT_LIMIT},
    })
    return _object_schema({
        "review_input_sha256": {"type": "string", "const": review_input["review_input_sha256"]},
        "evidence_sha256": {"type": "string", "const": review_input["evidence_sha256"]},
        "arms": {"type": "array", "items": arm_schema, "minItems": len(ARM_ORDER), "maxItems": len(ARM_ORDER)},
        "method_change": method_change,
        "candidates": {"type": "array", "items": candidate_schema, "minItems": len(candidates), "maxItems": len(candidates)},
        "limitations": {"type": "array", "const": review_input["required_limitations"]},
        "recommendation": recommendation,
    })


def method_review_output_schema(review_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return a strict JSON Schema for one already-built review input."""
    validated = _validate_review_input(review_input)
    return _schema_for_facts(validated)


def validate_method_review(review: Mapping[str, Any], review_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return a validated copy or raise ``ValueError`` on any mismatch.

    Exact factual echoes, references, null semantics, completeness, permitted
    actions, and mandatory limitations are checked. Free text remains bounded
    but semantically unverified, and this function cannot prove that a model
    turn was independent.
    """
    source = _validate_review_input(review_input)
    output_keys = {
        "review_input_sha256", "evidence_sha256", "arms", "method_change",
        "candidates", "limitations", "recommendation",
    }
    result = _exact_keys(review, output_keys, "method review")
    if result["review_input_sha256"] != source["review_input_sha256"]:
        raise ValueError("method review is bound to a different review input")
    if result["evidence_sha256"] != source["evidence_sha256"]:
        raise ValueError("method review is bound to different evidence")

    arms = result["arms"]
    if not isinstance(arms, list) or len(arms) != len(source["arms"]):
        raise ValueError("method review must assess each of the three arms exactly once")
    for expected, observed in zip(source["arms"], arms):
        observed = _exact_keys(
            observed,
            {"arm", "source_ref_id", "scientific_status", "delta", "resampling_interval", "groups_summary", "assessment"},
            "arm assessment",
        )
        if observed["arm"] != expected["name"]:
            raise ValueError("arm assessments must be named and ordered as the source arms")
        if observed["source_ref_id"] != expected["source_ref"]["ref_id"]:
            raise ValueError("arm assessment cites a reference for a different arm")
        for key in ("scientific_status", "delta", "resampling_interval", "groups_summary"):
            if not _fact_equal(observed[key], expected[key]):
                raise ValueError(f"arm assessment {expected['name']} {key} does not match source facts")
        _text(observed["assessment"], f"arm assessment {expected['name']} text")

    change = _exact_keys(
        result["method_change"],
        {"kind", "source_ref_id", "scientific_status", "delta", "resampling_interval", "groups_summary", "assessment"},
        "paired method-change assessment",
    )
    expected_change = source["method_change"]
    if change["kind"] != "paired_method_change":
        raise ValueError("method-change assessment must retain its distinct paired estimand")
    if change["source_ref_id"] != expected_change["source_ref"]["ref_id"]:
        raise ValueError("method-change assessment cites a non-contrast reference")
    for key in ("scientific_status", "delta", "resampling_interval", "groups_summary"):
        if not _fact_equal(change[key], expected_change[key]):
            raise ValueError(f"paired method-change {key} does not match contrast facts")
    _text(change["assessment"], "method-change assessment text")

    candidates = result["candidates"]
    if not isinstance(candidates, list) or len(candidates) != len(source["candidates"]):
        raise ValueError("method review must include each selected candidate exactly once")
    for expected, observed in zip(source["candidates"], candidates):
        observed = _exact_keys(
            observed,
            {"jid", "source_ref_id", "family", "opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom", "opt_status", "mbj_status", "category", "next_validation", "assessment"},
            "candidate assessment",
        )
        if observed["jid"] != expected["jid"]:
            raise ValueError("candidate assessment JIDs must match the host-selected order")
        if observed["source_ref_id"] != expected["source_ref"]["ref_id"]:
            raise ValueError("candidate assessment cites a different JID's evidence")
        expected_candidate_fields = {
            "family": expected["family"],
            "opt_gap_ev": expected["opt_gap_ev"],
            "mbj_gap_ev": expected["mbj_gap_ev"],
            "ehull_ev_atom": expected["ehull_ev_atom"],
            "opt_status": expected["opt_status"],
            "mbj_status": expected["mbj_status"],
            "category": expected["candidate_label"],
            "next_validation": expected["next_validation"],
        }
        for key, fact in expected_candidate_fields.items():
            if not _fact_equal(observed[key], fact):
                raise ValueError(f"candidate {expected['jid']} {key} does not match its exact source value")
        _text(observed["assessment"], f"candidate {expected['jid']} assessment text")

    if not _same_json(result["limitations"], source["required_limitations"]):
        raise ValueError("method review must retain every required scientific limitation")
    recommendation = _exact_keys(result["recommendation"], {"action", "evidence_refs", "rationale"}, "recommendation")
    if recommendation["action"] not in source["available_actions"]:
        raise ValueError("review recommendation is not among the host-supplied actions")
    input_ref_ids = {
        arm["source_ref"]["ref_id"] for arm in source["arms"]
    } | {source["method_change"]["source_ref"]["ref_id"]} | {
        candidate["source_ref"]["ref_id"] for candidate in source["candidates"]
    }
    evidence_refs = recommendation["evidence_refs"]
    if (
        not isinstance(evidence_refs, list)
        or not evidence_refs
        or any(not isinstance(ref_id, str) or ref_id not in input_ref_ids for ref_id in evidence_refs)
        or len(set(evidence_refs)) != len(evidence_refs)
    ):
        raise ValueError("recommendation must cite unique evidence references present in this input")
    _text(recommendation["rationale"], "recommendation rationale")
    return copy.deepcopy(dict(result))


__all__ = [
    "build_method_review_input",
    "method_review_output_schema",
    "validate_method_review",
]
