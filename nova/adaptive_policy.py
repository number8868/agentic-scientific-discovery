"""Pure, host-owned follow-up option packets for discovery runs.

This module proposes bounded choices only. It does not choose a scientific
answer, execute an experiment, or authorize holdout work.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .contracts import Result


_SUPPORTED_ID = re.compile(r"(?:NOVA-[0-9a-f]{16}|live-[A-Za-z0-9-]+-family-screen)")


def propose_followups(
    result: Result,
    *,
    remaining_seconds: float,
    method_audit_available: bool = True,
) -> dict[str, Any]:
    """Build a stable decision packet from a completed family screen.

    Durations are planning estimates, not measured costs. Unsupported result
    identities and invalid or incomplete outcomes raise without offering follow-up.
    """
    if isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or not math.isfinite(float(remaining_seconds)) or remaining_seconds < 0:
        raise ValueError("remaining_seconds must be finite and nonnegative")
    if not isinstance(result, Result):
        raise TypeError("result must be a Result")
    experiment_id = result.experiment_id
    if not isinstance(experiment_id, str) or not _SUPPORTED_ID.fullmatch(experiment_id):
        raise ValueError("unsupported experiment ID for adaptive follow-up")
    if not isinstance(method_audit_available, bool):
        raise ValueError("method_audit_available must be boolean")

    result_ref = f"result:{result.result_id}"
    if result.execution_status != "completed" or result.error is not None or result.scientific_status is None:
        raise ValueError("adaptive follow-up requires a completed, error-free result")
    # Conservative estimates scale with the observed parent duration, with a
    # modest floor for tiny/fixture timings. They are never reported as data.
    elapsed = result.elapsed_seconds
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(float(elapsed)) or elapsed < 0:
        raise ValueError("result elapsed_seconds must be finite and nonnegative")
    threshold_cost = max(60.0, float(elapsed) * 3.0)
    method_cost = max(120.0, float(elapsed) * 4.0)

    options: list[dict[str, Any]] = []
    summary = {
        "scientific_status": result.scientific_status,
        "delta": result.delta,
        "resampling_interval": list(result.resampling_interval) if result.resampling_interval is not None else None,
        "missingness_interval": list(result.missingness_interval) if result.missingness_interval is not None else None,
        "groups_summary": [
            {
                "group": group.group,
                "n_total": group.n_total,
                "n_observed": group.n_observed,
                "n_pass": group.n_pass,
                "coverage": group.coverage,
                "observed_rate": group.observed_rate,
                "missing_lower": group.missing_lower,
                "missing_upper": group.missing_upper,
            }
            for group in result.groups_summary
        ],
        "quality_flags": list(result.quality_flags),
    }
    uncertainty_note = (
        "The reported interval includes zero; the discovery contrast is inconclusive in this snapshot."
        if result.resampling_interval is not None and result.resampling_interval[0] <= 0 <= result.resampling_interval[1]
        else "Use the reported interval and quality flags to judge uncertainty; this packet does not interpret them as validation."
    )
    options.append({
            "choice": "threshold_sensitivity",
            "feasibility": remaining_seconds >= threshold_cost,
            "estimated_seconds": threshold_cost,
            "estimate_kind": "planning_estimate_not_measured",
            "learning_reasons": ["Checks whether the discovery contrast changes across the registered threshold axis.", uncertainty_note],
            "evidence_refs": [result_ref, "host_template:threshold_sensitivity"],
            "scope": "discovery_only",
        })
    if method_audit_available:
            options.append({
                "choice": "method_sensitivity",
                "feasibility": remaining_seconds >= method_cost,
                "estimated_seconds": method_cost,
                "estimate_kind": "planning_estimate_not_measured",
                "learning_reasons": ["Explores whether conclusions are sensitive to OPT versus MBJ on paired discovery representatives; this is descriptive method sensitivity."],
                "evidence_refs": [result_ref, "method_audit:paired_method_audit_v1"],
                "scope": "discovery_only_exploratory_not_holdout_validation_or_replication",
            })
    options.append({
        "choice": "stop",
        "feasibility": True,
        "estimated_seconds": 0.0,
        "estimate_kind": "planning_estimate_not_measured",
        "learning_reasons": ["Preserves the current discovery record without additional analysis."],
        "evidence_refs": [result_ref],
        "scope": "discovery_only",
    })
    return {
        "schema_version": 1,
        "packet_type": "adaptive_discovery_followups",
        "parent_result_id": result.result_id,
        "evidence_summary": summary,
        "remaining_seconds": float(remaining_seconds),
        "candidate_tests": [
            {
                "proposal_id": f"adaptive-{option['choice']}",
                "template": option["choice"],
                "choice": option["choice"],
                "feasibility": option["feasibility"],
                "estimated_seconds": option["estimated_seconds"],
                "estimate_kind": option["estimate_kind"],
                "reason": " ".join(option["learning_reasons"]),
                "learning_reasons": list(option["learning_reasons"]),
                "evidence_refs": list(option["evidence_refs"]),
                "scope": option["scope"],
            }
            for option in options
        ],
        "allowed_choices": [option["choice"] for option in options],
        "selection": None,
        "policy_note": "Options are host-generated; caller supplies only one listed choice and a reason. No option asserts a preferred scientific answer.",
    }


def validate_choice(packet: dict[str, Any], choice: str, reason: str) -> dict[str, Any]:
    """Validate a caller's bounded choice and return a selection record."""
    if not isinstance(packet, dict) or packet.get("packet_type") != "adaptive_discovery_followups" or packet.get("schema_version") != 1:
        raise ValueError("unsupported adaptive decision packet")
    if not isinstance(choice, str) or choice not in packet.get("allowed_choices", ()):
        raise ValueError("choice is not offered by this packet")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ValueError("reason must be nonempty and at most 500 characters")
    option = next((item for item in packet.get("candidate_tests", ()) if item.get("choice", item.get("template")) == choice), None)
    if option is None or option.get("feasibility") is not True:
        raise ValueError("choice is infeasible under the current budget or result status")
    if choice == "method_sensitivity" and option.get("scope") != "discovery_only_exploratory_not_holdout_validation_or_replication":
        raise ValueError("method sensitivity must remain exploratory discovery-only")
    return {
        "choice": choice,
        "reason": reason.strip(),
        "evidence_refs": list(option.get("evidence_refs", ())),
        "scope": option.get("scope"),
    }
