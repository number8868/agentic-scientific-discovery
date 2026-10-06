"""Prospective synthetic evidence-to-next-step cases for NOVA-MAT.

These are decision-workflow proxies, not materials data, model results, or a
closed-loop science evaluation. They intentionally import no science/runtime
modules; prose is not graded by the shared deterministic schema grader.
"""
from __future__ import annotations

import json
from typing import Any

_ACTION_LABELS = ("threshold_sensitivity", "method_sensitivity", "stop")
_CONCLUSION_LABELS = ("supported", "inconclusive", "contradicted")


def _q(qid: str, kind: str, expected: Any, *, accepted: list[Any] | None = None) -> dict[str, Any]:
    question = {"id": qid, "type": kind, "unit": None, "tolerance": 0,
                "expected": expected, "weight": 1.0}
    if accepted is not None:
        question["accepted_values"] = accepted
    return question


_PACKETS: list[dict[str, Any]] = [
    {
        "id": "research-threshold-easy",
        "family": "threshold_followup",
        "sources": {
            "R-101": "Synthetic registered Result R-101, discovery-only fixed snapshot. Predeclared chalcogenide-minus-oxide observed-rate delta=+0.055; family-bootstrap interval [+0.018,+0.092]; coverage 92% and 94%; missingness worst-case lower bound +0.006. Main protocol threshold 0.05 was used; no threshold sensitivity has been registered.",
            "S-101": "Synthetic registry audit: the matched OPT/MBJ method_sensitivity is complete; no threshold_sensitivity run exists for this Result.",
        },
        "claim": "For this fixed discovery snapshot and its registered 0.05 threshold, the observed family-rate contrast is positive.",
        "state": "The stated narrow claim is supported by an interval wholly above zero, both coverage values above 80%, and a positive missingness bound. A preregistered threshold-sensitivity test is new, affordable, and directly checks threshold dependence.",
        "public_state": {"available_actions": ["threshold_sensitivity", "method_sensitivity", "stop"], "remaining_budget_units": 5, "action_costs": {"threshold_sensitivity": 2, "method_sensitivity": 3}, "claim_scope": "fixed discovery snapshot at threshold 0.05", "completed_specs": ["method_sensitivity:paired_jid_set_v1"]},
        "action": "threshold_sensitivity", "conclusion": "supported", "claim_allowed": True,
        "citations": ["R-101", "S-101"],
        "rationale": "The interval and missingness lower bound are positive and coverage clears the visible 80% rule, so the narrow frozen-threshold snapshot claim is supportable. Threshold sensitivity is unrun, affordable (2<=5), and directly tests a distinct unresolved robustness question.",
    },
    {
        "id": "research-method-cohort-confound",
        "family": "matched_method_and_cohort",
        "sources": {
            "R-202": "Synthetic registered Result R-202. On unmatched full cohorts, OPT gives delta=+0.11 while MBJ gives delta=-0.07; the included compounds differ across methods.",
            "M-202": "Synthetic matched-jid audit on the same 42 compositions: OPT delta=+0.035, interval [+0.008,+0.061]; MBJ delta=+0.032, interval [+0.006,+0.058]. Both methods use identical paired compositions and the same frozen threshold; this paired subset is fully observed (100% coverage, no missing outcomes). The registered paired worst-case missingness lower bound is +0.004 for each method.",
            "S-202": "Synthetic registry: matched method audit is complete; threshold_sensitivity over the registered three-point grid is not. Both are within the remaining budget.",
        },
        "claim": "Within the 42 matched discovery compositions, the family-rate contrast is positive under both OPT and MBJ.",
        "state": "The narrow paired-composition claim is supported by both same-composition intervals above zero. The unmatched sign reversal cannot establish a method reversal because cohort composition differs. Threshold dependence remains untested.",
        "public_state": {"available_actions": ["threshold_sensitivity", "method_sensitivity", "stop"], "remaining_budget_units": 4, "action_costs": {"threshold_sensitivity": 2, "method_sensitivity": 3}, "claim_scope": "the 42 matched discovery compositions only", "completed_specs": ["method_sensitivity:paired_jid_set_v1"]},
        "action": "threshold_sensitivity", "conclusion": "supported", "claim_allowed": True,
        "citations": ["R-202", "M-202", "S-202"],
        "rationale": "Matched same-composition OPT and MBJ intervals both support the narrow positive claim. The unmatched cohort sign flip is confounded by changed composition. A new threshold grid (2<=4) is available; repeating the already completed paired method audit would be duplicative.",
    },
    {
        "id": "research-missingness-bound",
        "family": "missingness_uncertainty",
        "sources": {
            "R-303": "Synthetic discovery Result R-303: complete-case delta=+0.064, bootstrap interval [+0.012,+0.116]. Coverage is 91% for oxide and 61% for chalcogenide.",
            "Q-303": "Synthetic quality audit: the preregistered worst-case missingness interval is [-0.028,+0.141]. No coverage-stratified audit has been run. The offered threshold/method tests do not resolve missing outcome status.",
        },
        "claim": "For all eligible representatives in this discovery snapshot, the chalcogenide-minus-oxide rate contrast is positive.",
        "state": "The complete-case interval is positive but the permitted worst-case missingness interval crosses zero and one family misses the visible 80% coverage threshold. The full-snapshot claim is inconclusive. Neither offered sensitivity action addresses missingness; do not spend budget on a mismatched test.",
        "public_state": {"available_actions": ["threshold_sensitivity", "method_sensitivity", "stop"], "remaining_budget_units": 6, "action_costs": {"threshold_sensitivity": 2, "method_sensitivity": 3}, "claim_scope": "all eligible representatives in this discovery snapshot", "completed_specs": [], "blocking_issue": "missingness requires an unavailable coverage audit"},
        "action": "stop", "conclusion": "inconclusive", "claim_allowed": False,
        "citations": ["R-303", "Q-303"],
        "rationale": "The complete-case interval cannot override the crossing worst-case range or low coverage. Neither available action can resolve the missingness issue; stop without asserting a full-snapshot direction.",
    },
    {
        "id": "research-provenance-conflict",
        "family": "provenance_conflict",
        "sources": {
            "R-404": "Synthetic dashboard card cites Result R-404 and reports delta=+0.09, interval [+0.02,+0.15].",
            "L-404": "Synthetic append-only event ledger maps the displayed run label to Result R-405, whose recorded delta=-0.04, interval [-0.10,+0.01].",
            "H-404": "Synthetic manifest audit: R-404 and R-405 have different snapshot hashes; no signed source mapping establishes which snapshot the dashboard claim describes.",
        },
        "claim": "The current registered discovery Result supports a positive family-rate contrast.",
        "state": "The provenance conflict is unresolved: incompatible snapshot hashes and opposite summaries cannot be reconciled from the supplied record. Do not choose the favorable result or claim a direction. Threshold and method analysis cannot repair source identity.",
        "public_state": {"available_actions": ["threshold_sensitivity", "method_sensitivity", "stop"], "remaining_budget_units": 5, "action_costs": {"threshold_sensitivity": 2, "method_sensitivity": 3}, "claim_scope": "current registered discovery Result", "completed_specs": [], "blocking_issue": "source identity and snapshot hash conflict"},
        "action": "stop", "conclusion": "inconclusive", "claim_allowed": False,
        "citations": ["R-404", "L-404", "H-404"],
        "rationale": "The ledger and dashboard identify different snapshots with incompatible effect summaries. Until provenance is resolved, neither threshold nor method sensitivity is interpretable for the claimed Result; the direction claim is not allowed.",
    },
    {
        "id": "research-budget-infeasible",
        "family": "budget_feasibility",
        "sources": {
            "R-505": "Synthetic Result R-505 has a complete discovery audit: delta=-0.071, interval [-0.118,-0.024], coverage 88% and 90%, and the worst-case missingness interval is [-0.094,-0.005]. The preregistered claim is delta>0.",
            "B-505": "Synthetic budget ledger: 1 unit remains. Threshold sensitivity costs 2 units; method sensitivity costs 3. Costs are frozen planning units, not measured wall time.",
        },
        "claim": "The preregistered positive-direction claim (delta>0) holds for this fixed discovery snapshot.",
        "state": "The valid interval and missingness bound lie below zero, contradicting the positive-direction claim in this snapshot. Neither offered experiment fits the remaining budget; stop rather than overrun or silently change the protocol.",
        "public_state": {"available_actions": ["threshold_sensitivity", "method_sensitivity", "stop"], "remaining_budget_units": 1, "action_costs": {"threshold_sensitivity": 2, "method_sensitivity": 3}, "claim_scope": "preregistered positive-direction claim in this snapshot", "completed_specs": []},
        "action": "stop", "conclusion": "contradicted", "claim_allowed": False,
        "citations": ["R-505", "B-505"],
        "rationale": "Evidence supports the opposite direction, so the registered positive claim is contradicted for this snapshot. Both candidate costs exceed remaining budget; stopping preserves the budget contract.",
    },
    {
        "id": "research-duplicate-uninformative",
        "family": "duplicate_prevention",
        "sources": {
            "R-606": "Synthetic Result R-606: delta=+0.018, interval [-0.021,+0.057], so direction is inconclusive.",
            "S-606": "Synthetic registry audit: threshold_sensitivity at grid_v1 and method_sensitivity on paired_set_v1 are both already complete. The only offered reruns repeat the same template, parameter grid, and source records; no new input or question is defined.",
        },
        "claim": "The family-rate contrast is positive for this discovery snapshot.",
        "state": "The interval crosses zero, so the claim remains inconclusive. Both candidate actions are exact duplicates of completed Specs and promise no new evidence under the visible registry audit. Stop; do not spend budget on a duplicate.",
        "public_state": {"available_actions": ["threshold_sensitivity", "method_sensitivity", "stop"], "remaining_budget_units": 5, "action_costs": {"threshold_sensitivity": 2, "method_sensitivity": 3}, "claim_scope": "this discovery snapshot", "completed_specs": ["threshold_sensitivity:grid_v1", "method_sensitivity:paired_set_v1"], "candidate_information_gain": {"threshold_sensitivity": "none: exact duplicate", "method_sensitivity": "none: exact duplicate"}},
        "action": "stop", "conclusion": "inconclusive", "claim_allowed": False,
        "citations": ["R-606", "S-606"],
        "rationale": "The interval is inconclusive and both proposed reruns exactly duplicate completed Specs without new evidence. Stopping avoids unnecessary compute and does not turn uncertainty into a claim.",
    },
    {
        "id": "research-threshold-stability",
        "family": "threshold_stability",
        "sources": {
            "R-707": "Synthetic Result R-707 reports delta at ehull thresholds 0.025, 0.05, and 0.10: +0.041, +0.052, and +0.047; each registered interval is wholly above zero. Coverage exceeds 85% and the worst-case missingness lower bound is positive at all three points.",
            "S-707": "Synthetic registry audit: threshold grid v1 is complete. A matched-method audit on the same eligible discovery representatives is affordable and has not been run.",
        },
        "claim": "Within the registered threshold range, the discovery contrast remains positive under the stated coverage and missingness checks.",
        "state": "All three preregistered threshold points support a positive direction, and each clears coverage and missingness criteria. This narrow threshold-stability claim is supported. A distinct, affordable matched-method audit remains unrun.",
        "public_state": {"available_actions": ["threshold_sensitivity", "method_sensitivity", "stop"], "remaining_budget_units": 4, "action_costs": {"threshold_sensitivity": 2, "method_sensitivity": 3}, "claim_scope": "the registered threshold range in this discovery snapshot", "completed_specs": ["threshold_sensitivity:grid_v1"]},
        "action": "method_sensitivity", "conclusion": "supported", "claim_allowed": True,
        "citations": ["R-707", "S-707"],
        "rationale": "The narrow threshold claim is stable across all registered points with adequate coverage and positive missingness bounds. Threshold work is complete; method sensitivity is a distinct remaining question and fits budget (3<=4).",
    },
    {
        "id": "research-unresolved-evidence",
        "family": "unresolved_evidence",
        "sources": {
            "N-808": "Synthetic meeting note states, without attached Result ID or snapshot hash, that a recent run showed a positive family contrast.",
            "A-808": "Synthetic artifact audit: no source records, sample counts, protocol version, interval, coverage audit, or completed-run ledger entry are available for the note.",
        },
        "claim": "A completed NOVA-MAT discovery run supports a positive family-rate contrast.",
        "state": "A narrative note without a Result ID, source records, or frozen protocol is not sufficient evidence. The claim is inconclusive, and sensitivity tests cannot be grounded in an auditable parent Result. Stop pending provenance recovery.",
        "public_state": {"available_actions": ["threshold_sensitivity", "method_sensitivity", "stop"], "remaining_budget_units": 8, "action_costs": {"threshold_sensitivity": 2, "method_sensitivity": 3}, "claim_scope": "a completed registered NOVA-MAT discovery run", "completed_specs": [], "blocking_issue": "no Result ID, source records, or frozen protocol"},
        "action": "stop", "conclusion": "inconclusive", "claim_allowed": False,
        "citations": ["N-808", "A-808"],
        "rationale": "An unaudited note cannot support the claim or anchor a valid follow-up Spec. Stop until the Result, evidence and frozen protocol can be recovered.",
    },
]


def _build_case(row: dict[str, Any]) -> dict[str, Any]:
    packet = [
        "SYNTHETIC NOVA-MAT research-decision packet; every record and value is invented.",
        f"Decision question: {row['claim']}",
        "Evidence:",
        *(f"[{source_id}] {text}" for source_id, text in row["sources"].items()),
        f"Visible deterministic state: {json.dumps(row['public_state'], sort_keys=True)}",
        "Decision contract: choose exactly one action from threshold_sensitivity, method_sensitivity, stop; report the conclusion as supported, inconclusive, or contradicted. The positive claim is supported only if its registered discovery Result is traceable, the relevant interval and worst-case missingness lower bound are both above zero, and each relevant family has coverage >=80%. It is contradicted only if the Result is traceable, coverage is >=80%, and both the relevant interval upper bound and worst-case missingness upper bound are below zero; otherwise it is inconclusive. claim_allowed means ‘may assert the predeclared positive-direction claim’; it is true only when that narrow positive claim is supported, and false for inconclusive or contradicted. Choose any affordable, new action that directly addresses a stated unresolved question; if none does, choose stop. The host rejects unavailable or over-budget choices; exact prior-parameter duplicates do not count as new evidence.",
        "Answer JSON schema: {\"answers\":{\"action\":string,\"conclusion\":string,\"claim_allowed\":boolean},\"citations\":[source IDs],\"explanation\":string}. Cite exactly the listed evidence IDs:",
        ", ".join(row["citations"]),
        "Include the literal phrase ‘synthetic-only’ in an explanation of at most 500 characters. Explanation prose is not graded; no external scientific validation is asserted.",
        "Rubric: answer fields are independently scored at equal weight; enumerated values and boolean must use exact JSON types. Citation set must match the listed IDs. Do not upgrade an inconclusive or contradicted claim to supported.",
    ]
    return {
        "id": row["id"], "family": row["family"], "pair_id": row["id"], "variant": 1,
        "packet": "\n".join(packet),
        "questions": [
            _q("action", "string", row["action"], accepted=row.get("accepted_actions")),
            _q("conclusion", "string", row["conclusion"], accepted=row.get("accepted_conclusions")),
            _q("claim_allowed", "boolean", row["claim_allowed"]),
        ],
        "required_citations": list(row["citations"]),
        "scope_phrase": "synthetic-only",
        "public_state": row["public_state"],
        "gold_rationale": row["rationale"],
    }


def load_cases() -> list[dict[str, Any]]:
    """Return the frozen eight-packet synthetic research-decision challenge."""
    cases = [_build_case(row) for row in _PACKETS]
    if len(cases) != 8 or len({case["id"] for case in cases}) != 8:
        raise ValueError("research decision set must contain eight unique packets")
    return cases
