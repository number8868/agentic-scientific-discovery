"""Acceptance checks for the prospective synthetic research-decision packets."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova.benchmark_parallel_cases import grade_response
from nova.benchmark_research_cases import load_cases


def _gold_response(case: dict) -> dict:
    return {
        "answers": {question["id"]: question["expected"] for question in case["questions"]},
        "citations": list(case["required_citations"]),
        "explanation": "synthetic-only; decision based on the visible registered evidence.",
    }


def test_eight_unique_visible_packets_and_no_gold_label_in_state():
    cases = load_cases()
    assert len(cases) == 8
    assert len({case["id"] for case in cases}) == 8
    assert len({case["family"] for case in cases}) == 8
    for case in cases:
        state = case["public_state"]
        assert {"available_actions", "remaining_budget_units", "action_costs", "claim_scope", "completed_specs"} <= set(state)
        assert "initial_conclusion" not in state
        assert json.dumps(state, sort_keys=True) in case["packet"]
        assert "Decision contract:" in case["packet"]
        assert "Answer JSON schema:" in case["packet"]
        assert "synthetic-only" in case["packet"]
        assert "expected" not in case["packet"]


def test_every_frozen_gold_passes_shared_strict_grader():
    for case in load_cases():
        result = grade_response(case, _gold_response(case))
        assert result["strict_schema_pass"], (case["id"], result)
        assert result["semantic_score"] == 1.0, (case["id"], result)
        assert result["citation_pass"], (case["id"], result)
        assert result["scope_pass"], (case["id"], result)
        assert case["gold_rationale"]


def test_independent_case_judgments_match_visible_decision_criteria():
    by_id = {case["id"]: case for case in load_cases()}
    answers = {
        case_id: {q["id"]: q["expected"] for q in by_id[case_id]["questions"]}
        for case_id in by_id
    }
    assert answers["research-threshold-easy"] == {
        "action": "threshold_sensitivity", "conclusion": "supported", "claim_allowed": True}
    assert answers["research-method-cohort-confound"] == {
        "action": "threshold_sensitivity", "conclusion": "supported", "claim_allowed": True}
    assert answers["research-missingness-bound"]["conclusion"] == "inconclusive"
    assert answers["research-provenance-conflict"]["conclusion"] == "inconclusive"
    assert answers["research-budget-infeasible"]["conclusion"] == "contradicted"
    assert answers["research-duplicate-uninformative"]["action"] == "stop"
    assert answers["research-threshold-stability"]["action"] == "method_sensitivity"
    assert answers["research-unresolved-evidence"]["claim_allowed"] is False


def test_wrong_citations_and_missing_scope_marker_fail_separately():
    case = load_cases()[0]
    response = _gold_response(case)
    response["citations"] = [case["required_citations"][0]]
    response["explanation"] = "Evidence supports this result."
    result = grade_response(case, response)
    assert result["strict_schema_pass"]
    assert not result["citation_pass"]
    assert not result["scope_pass"]

