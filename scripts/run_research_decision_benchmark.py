#!/usr/bin/env python3
"""Offline-first paired pilot for research decision workflow utility.

This measures the structured case rubric and operational timing only. It does
not establish scientific validity or prove specialist-role causality.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova.benchmark_parallel_report import (  # noqa: E402
    ARMS, AtomicTurnBudget, DurableRunStore, create_run_directory,
    safe_text, sha256_file, sha256_json,
)
from scripts.run_parallel_selftest import _execute_arm, _groups  # noqa: E402

MODEL = "gpt-6-luna"
EFFORT = "medium"
MAX_CASES = 8
PILOT_CASES = 4
TURN_LIMIT_PER_CASE = 6
PAIR_RESERVATION_SECONDS = 310
TOTAL_DEADLINE_SECONDS = 2700


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", help="new exclusive output directory; existing data is never overwritten")
    p.add_argument("--limit-cases", type=int, default=PILOT_CASES,
                   help="bounded pilot size (default 4; maximum 8)")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--reasoning-effort", default=EFFORT)
    p.add_argument("--enable-model-calls", action="store_true",
                   help="explicitly enable SDK calls; otherwise writes an offline manifest only")
    return p


def _rule_reference(case: dict[str, Any]) -> dict[str, Any]:
    """Action-only threshold-first rule; it does not grade full decision quality."""
    state = case.get("public_state")
    if not isinstance(state, dict):
        return {"status": "unavailable", "action": None}
    menu = state.get("available_actions")
    costs = state.get("action_costs")
    budget = state.get("remaining_budget_units")
    completed = state.get("completed_specs", [])
    if not isinstance(menu, list) or not isinstance(costs, dict) or not isinstance(budget, (int, float)):
        return {"status": "unavailable", "action": None}
    if state.get("blocking_issue") or not isinstance(completed, list):
        return {"status": "scored", "action": "stop", "scope": "action_only",
                "policy": "stop_if_blocked"}
    choices = []
    for priority, action in enumerate(("threshold_sensitivity", "method_sensitivity")):
        already_done = any(isinstance(item, str) and item.startswith(action + ":") for item in completed)
        cost = costs.get(action)
        if (action in menu and not already_done and isinstance(cost, (int, float))
                and not isinstance(cost, bool) and math.isfinite(float(cost))
                and 0 <= float(cost) <= float(budget)):
            choices.append((priority, action))
    return {"status": "scored", "action": choices[0][1] if choices else "stop",
            "scope": "action_only", "policy": "threshold_first_affordable_not_already_completed"}


def _rule_row(case: dict[str, Any]) -> dict[str, Any]:
    row = _rule_reference(case)
    action_question = next((q for q in case.get("questions", []) if q.get("id") == "action"), None)
    if action_question is not None and row.get("status") == "scored":
        accepted = action_question.get("accepted_values")
        allowed = accepted if isinstance(accepted, list) else [action_question.get("expected")]
        row["action_correct"] = row.get("action") in allowed
    else:
        row["action_correct"] = None
    return row


async def _run(args: argparse.Namespace) -> int:
    if isinstance(args.limit_cases, bool) or not 1 <= args.limit_cases <= MAX_CASES:
        raise ValueError("--limit-cases must be between 1 and 8")
    from nova.benchmark_research_cases import load_cases

    cases = load_cases()
    version = "frozen-in-module"
    if not isinstance(cases, list) or len(cases) != MAX_CASES:
        raise ValueError("research decision corpus must contain exactly eight frozen cases")
    cases = cases[:args.limit_cases]
    repetitions = 1
    turns_limit = len(cases) * TURN_LIMIT_PER_CASE
    groups = _groups(cases, repetitions, seed=1729)
    run_dir = create_run_directory(args.output)
    store = DurableRunStore(run_dir)
    script_hash = sha256_file(Path(__file__))
    cases_module = ROOT / "nova" / "benchmark_research_cases.py"
    grader_module = ROOT / "nova" / "benchmark_parallel_cases.py"
    runtime_module = ROOT / "nova" / "benchmark_parallel_runtime.py"
    worker_module = ROOT / "scripts" / "parallel_selftest_worker.py"
    inherited_runner = ROOT / "scripts" / "run_parallel_selftest.py"
    report_module = ROOT / "nova" / "benchmark_parallel_report.py"
    host_helper = ROOT / "scripts" / "run_omnigent_live.py"
    try:
        omnigent_version = importlib.metadata.version("omnigent")
    except importlib.metadata.PackageNotFoundError:
        omnigent_version = None
    groups_schedule = [{"case_id": g["case_id"], "repetition": g["repetition"],
                       "arm_order": g["scheduled_arm_order"]} for g in groups]
    report: dict[str, Any] = {
        "schema_version": 1,
        "benchmark": "nova_research_decision_pilot_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "bounded paired engineering pilot; not scientific validation",
        "arm_labels": {ARMS[0]: "persistent single-agent three-turn review",
                       ARMS[1]: "parallel independent reviews plus PI synthesis"},
        "corpus_version": version,
        "corpus_sha256": sha256_json(cases),
        "runner_sha256": script_hash,
        "case_module_sha256": sha256_file(cases_module) if cases_module.exists() else None,
        "grader_module_sha256": sha256_file(grader_module) if grader_module.exists() else None,
        "runtime_module_sha256": sha256_file(runtime_module) if runtime_module.exists() else None,
        "worker_module_sha256": sha256_file(worker_module) if worker_module.exists() else None,
        "inherited_runner_sha256": sha256_file(inherited_runner),
        "report_module_sha256": sha256_file(report_module),
        "host_helper_sha256": sha256_file(host_helper) if host_helper.exists() else None,
        "model_calls_enabled": bool(args.enable_model_calls),
        "model_requested": args.model if args.enable_model_calls else None,
        "reasoning_effort_requested": args.reasoning_effort if args.enable_model_calls else None,
        "requested_max_tokens_per_turn": 1200 if args.enable_model_calls else None,
        "provider_hard_token_limit_verified": False,
        "provider_request_count": None, "provider_usage_attested": None,
        "model_identity_attested": None, "billed_cost": None,
        "omnigent_version": omnigent_version,
        "cases": cases, "repetitions": repetitions, "groups": groups,
        "schedule_seed": 1729,
        "scheduled_group_order": groups_schedule,
        "scheduled_group_order_sha256": sha256_json(groups_schedule),
        "limits": {"sdk_turns": turns_limit, "per_arm_turns": 3,
                   "turn_timeout_seconds": 45, "per_arm_deadline_seconds": 150,
                   "max_concurrent_sdk_execution_slots": 2,
                   "provider_internal_concurrency_attested": None,
                   "pair_reservation_seconds": PAIR_RESERVATION_SECONDS,
                   "total_deadline_seconds": TOTAL_DEADLINE_SECONDS, "retries": 0,
                   "limit_cases": args.limit_cases},
        "claims": "descriptive case-level pair results only; no formal benefit claim or CI",
        "deterministic_rule_reference": {c["id"]: _rule_row(c) for c in cases},
        "descriptive_results": None,
        "scope_complete": False, "sdk_turns_reserved": 0,
    }
    report["frozen_manifest_sha256"] = sha256_json({
        "corpus_sha256": report["corpus_sha256"], "runner_sha256": script_hash,
        "case_module_sha256": report["case_module_sha256"],
        "grader_module_sha256": report["grader_module_sha256"],
        "runtime_module_sha256": report["runtime_module_sha256"],
        "worker_module_sha256": report["worker_module_sha256"],
        "inherited_runner_sha256": report["inherited_runner_sha256"],
        "report_module_sha256": report["report_module_sha256"],
        "host_helper_sha256": report["host_helper_sha256"],
        "model_requested": report["model_requested"],
        "reasoning_effort_requested": report["reasoning_effort_requested"],
        "requested_max_tokens_per_turn": report["requested_max_tokens_per_turn"],
        "omnigent_version": report["omnigent_version"],
        "limits": report["limits"], "schedule_seed": report["schedule_seed"],
        "scheduled_group_order_sha256": report["scheduled_group_order_sha256"],
        "arm_labels": report["arm_labels"],
        "cases": cases,
    })
    store.append("manifest_frozen", {"sha256": report["frozen_manifest_sha256"],
                                     "planned_sdk_turns": turns_limit,
                                     "model_calls_enabled": args.enable_model_calls})
    store.checkpoint(report)
    budget = AtomicTurnBudget(turns_limit if args.enable_model_calls else 0, store, report)
    status = "offline_manifest_only"
    run_deadline = time.monotonic() + TOTAL_DEADLINE_SECONDS
    try:
        if args.enable_model_calls:
            status = "completed"
            for group in groups:
                if run_deadline - time.monotonic() < PAIR_RESERVATION_SECONDS:
                    group["status"] = "not_started"
                    status = "incomplete_or_failed"
                    store.checkpoint(report)
                    continue
                case = next(c for c in cases if c["id"] == group["case_id"])
                group["status"] = "running"
                store.append("paired_group_reserved", {
                    "case_id": group["case_id"], "repetition": group["repetition"],
                    "arm_order": group["scheduled_arm_order"],
                    "reserved_seconds": PAIR_RESERVATION_SECONDS,
                })
                store.checkpoint(report)
                for arm in group["scheduled_arm_order"]:
                    await _execute_arm(case=case, group=group, arm=arm, model=args.model,
                                       reasoning_effort=args.reasoning_effort, budget=budget,
                                       store=store, report=report,
                                       arm_deadline_at=time.monotonic() + 150)
                    result = group["arms"][arm]
                    if result.get("fatal_audit") or result.get("cleanup_ok") is False:
                        raise RuntimeError("fatal runtime/audit or cleanup state")
                group["status"] = "completed" if all(
                    group["arms"][a]["status"] == "completed" for a in ARMS) else "failed"
                if group["status"] != "completed":
                    status = "incomplete_or_failed"
                store.checkpoint(report)
            report["scope_complete"] = all(g["status"] == "completed" for g in groups)
            if not report["scope_complete"]:
                status = "incomplete_or_failed"
            report["descriptive_results"] = _summarize(groups, cases)
        report["sdk_turns_reserved"] = budget.used
        report["runner_status"] = status
        store.append("run_terminal", {"status": status, "sdk_turns_reserved": budget.used})
        store.checkpoint(report)
    except BaseException as exc:
        report["sdk_turns_reserved"] = budget.used
        report["descriptive_results"] = _summarize(groups, cases)
        report["runner_status"] = "interrupted_or_failed"
        report["runner_error"] = safe_text(exc)
        for group in groups:
            if group.get("status") == "running":
                group["status"] = "interrupted"
        store.append("run_interrupted", {"error": safe_text(exc), "sdk_turns_reserved": budget.used})
        store.checkpoint(report)
        status = "interrupted_or_failed"
    finally:
        store.close()
    print(json.dumps({"run_dir": str(run_dir), "status": report["runner_status"],
                      "model_calls_enabled": args.enable_model_calls,
                      "sdk_turns_reserved": budget.used}, sort_keys=True))
    return 0 if status in ("completed", "offline_manifest_only") else 3


def _summarize(groups: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_case = {case["id"]: case for case in cases}
    paired = []
    for group in groups:
        arms = group.get("arms", {})
        left, right = (arms.get(a, {}) for a in ARMS)
        complete = all(row.get("status") == "completed" for row in (left, right))
        lg, rg = left.get("grade") or {}, right.get("grade") or {}
        def score(g: dict[str, Any]) -> float | None:
            value = g.get("semantic_score")
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) else None
        paired.append({
            "case_id": group["case_id"], "status": group.get("status"),
            "both_valid_deliveries": bool(left.get("delivery_valid") and right.get("delivery_valid")),
            "single_semantic_proxy": score(lg), "parallel_semantic_proxy": score(rg),
            "single_elapsed_seconds": left.get("observed_delivery_seconds"),
            "parallel_elapsed_seconds": right.get("observed_delivery_seconds"),
            "rule_reference": _rule_row(by_case[group["case_id"]]),
            "complete_pair": complete,
        })
    eligible = [row for row in paired if row["complete_pair"]]
    allcorrect = lambda g: (g.get("semantic_score") == 1 and g.get("strict_schema_pass") is True
                            and g.get("citation_pass") is True and g.get("scope_pass") is True)
    strict_pair_successes = sum(
        1 for group in groups
        if group.get("arms", {}).get(ARMS[0], {}).get("delivery_valid")
        and group.get("arms", {}).get(ARMS[1], {}).get("delivery_valid")
        and allcorrect(group["arms"][ARMS[0]].get("grade") or {})
        and allcorrect(group["arms"][ARMS[1]].get("grade") or {})
    )
    return {
        "scheduled_cases": len(groups), "completed_pairs": len(eligible),
        "failed_or_incomplete_pairs": len(groups) - len(eligible),
        "all_answers_and_contract_correct_both_arms": strict_pair_successes,
        "per_arm_all_answers_and_contract_correct_rate_over_all_scheduled": {
            arm: (sum(1 for group in groups
                      if group.get("arms", {}).get(arm, {}).get("delivery_valid")
                      and allcorrect(group["arms"][arm].get("grade") or {})) / len(groups))
            if groups else None for arm in ARMS
        },
        "semantic_proxy_mean_by_arm": {
            arm: (sum(x[key] for x in eligible if x[key] is not None)
                  / sum(1 for x in eligible if x[key] is not None))
            if any(x[key] is not None for x in eligible) else None
            for arm, key in ((ARMS[0], "single_semantic_proxy"),
                             (ARMS[1], "parallel_semantic_proxy"))
        },
        "delivery_utility_mean_all_scheduled_zero_for_failed": {
            arm: (sum((float(g["arms"][arm]["grade"]["semantic_score"])
                       if g["arms"][arm].get("delivery_valid")
                       and isinstance((g["arms"][arm].get("grade") or {}).get("semantic_score"), (int, float))
                       and not isinstance((g["arms"][arm].get("grade") or {}).get("semantic_score"), bool)
                       else 0.0) for g in groups) / len(groups)) if groups else None
            for arm in ARMS
        },
        "rule_action_correct_rate": (
            sum(1 for g in groups if _rule_row(by_case[g["case_id"]]).get("action_correct") is True)
            / len(groups)) if groups else None,
        "paired_elapsed_seconds": [
            {"case_id": row["case_id"], ARMS[0]: row["single_elapsed_seconds"],
             ARMS[1]: row["parallel_elapsed_seconds"]}
            for row in eligible
        ],
        "paired_deadline_penalty_seconds_all_scheduled": [
            {"case_id": group["case_id"],
             ARMS[0]: group["arms"][ARMS[0]].get("deadline_penalty_seconds"),
             ARMS[1]: group["arms"][ARMS[1]].get("deadline_penalty_seconds"),
             "pair_status": group.get("status")}
            for group in groups
        ],
        "quality_win_tie_loss_on_semantic_proxy": {
            "parallel_win": sum(1 for row in eligible if row["single_semantic_proxy"] is not None
                                and row["parallel_semantic_proxy"] is not None
                                and row["parallel_semantic_proxy"] > row["single_semantic_proxy"]),
            "tie": sum(1 for row in eligible if row["single_semantic_proxy"] is not None
                       and row["parallel_semantic_proxy"] is not None
                       and row["parallel_semantic_proxy"] == row["single_semantic_proxy"]),
            "parallel_loss": sum(1 for row in eligible if row["single_semantic_proxy"] is not None
                                 and row["parallel_semantic_proxy"] is not None
                                 and row["parallel_semantic_proxy"] < row["single_semantic_proxy"]),
        },
        "note": "Descriptive pilot only; incomplete cases reported, no inferential claim/CI.",
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"research decision pilot failed: {safe_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
