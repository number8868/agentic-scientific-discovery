from __future__ import annotations

import pytest

from nova.adaptive_policy import propose_followups, validate_choice
from nova.contracts import Result


def _result(**overrides):
    values = dict(
        result_id="r-123", experiment_id="NOVA-0123456789abcdef",
        spec_sha256="s" * 64, dataset_sha256="d" * 64,
        execution_status="completed", scientific_status="inconclusive",
        started_at="2026-01-01T00:00:00Z", finished_at="2026-01-01T00:01:00Z",
        elapsed_seconds=30.0, groups_summary=(), delta=0.1,
        resampling_interval=(-0.1, 0.2), missingness_interval=None,
        quality_flags=(), artifact_ids=("artifact-1",), error=None,
    )
    values.update(overrides)
    return Result(**values)


def test_completed_result_offers_only_bounded_discovery_choices():
    packet = propose_followups(_result(), remaining_seconds=500)
    assert packet["allowed_choices"] == ["threshold_sensitivity", "method_sensitivity", "stop"]
    assert packet["selection"] is None
    assert packet["parent_result_id"] == "r-123"
    assert packet["evidence_summary"]["delta"] == 0.1
    assert packet["evidence_summary"]["resampling_interval"] == [-0.1, 0.2]
    method = next(x for x in packet["candidate_tests"] if x["choice"] == "method_sensitivity")
    assert method["scope"] == "discovery_only_exploratory_not_holdout_validation_or_replication"
    assert method["estimate_kind"] == "planning_estimate_not_measured"
    assert method["evidence_refs"] == ["result:r-123", "method_audit:paired_method_audit_v1"]
    assert validate_choice(packet, "method_sensitivity", "Explore method-dependent instability") == {
        "choice": "method_sensitivity", "reason": "Explore method-dependent instability",
        "evidence_refs": method["evidence_refs"], "scope": method["scope"],
    }


def test_method_option_omitted_when_audit_unavailable():
    packet = propose_followups(_result(), remaining_seconds=500, method_audit_available=False)
    assert packet["allowed_choices"] == ["threshold_sensitivity", "stop"]


@pytest.mark.parametrize("experiment_id", ["unsupported", "NOVA-not-a-registered-id"])
def test_unsupported_experiment_ids_rejected(experiment_id):
    with pytest.raises(ValueError, match="unsupported experiment ID"):
        propose_followups(_result(experiment_id=experiment_id), remaining_seconds=500)


@pytest.mark.parametrize("budget", [float("nan"), float("inf"), -1, True])
def test_nonfinite_or_invalid_budget_rejected(budget):
    with pytest.raises(ValueError, match="remaining_seconds"):
        propose_followups(_result(), remaining_seconds=budget)


def test_insufficient_budget_marks_followups_infeasible_and_blocks_selection():
    packet = propose_followups(_result(), remaining_seconds=100)
    assert [x["feasibility"] for x in packet["candidate_tests"]] == [True, False, True]
    with pytest.raises(ValueError, match="infeasible"):
        validate_choice(packet, "method_sensitivity", "Try anyway")


@pytest.mark.parametrize("status", ["failed", "timeout", "running"])
def test_invalid_or_incomplete_result_fails_closed(status):
    with pytest.raises(ValueError, match="completed"):
        propose_followups(_result(execution_status=status, scientific_status=None), remaining_seconds=1000)


def test_unoffered_choice_and_method_scope_contradiction_are_rejected():
    packet = propose_followups(_result(), remaining_seconds=500)
    with pytest.raises(ValueError, match="not offered"):
        validate_choice(packet, "holdout_validation", "Validate")
    method = next(x for x in packet["candidate_tests"] if x["choice"] == "method_sensitivity")
    method["scope"] = "holdout_validation"
    with pytest.raises(ValueError, match="exploratory discovery-only"):
        validate_choice(packet, "method_sensitivity", "Validate")
