#!/usr/bin/env python3
"""Offline-by-default driver for the bounded parallel self-test.

The existing 84-turn serial benchmark runner is not reused. This runner keeps
science engines, scientific registries, and holdout modules out of process.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova.benchmark_parallel_report import (  # noqa: E402
    ARMS, DEADLINE_SECONDS, AtomicTurnBudget, DurableRunStore, create_run_directory,
    safe_text, sha256_file, sha256_json, summarize_report,
)

DEFAULT_CORPUS = ROOT / "docs" / "examples" / "parallel_selftest_v1.json"
MODEL = "gpt-6-luna"
REASONING_EFFORT = "medium"
MAX_BATCH_SECONDS = 1800.0
TOTAL_EXPLORATORY_SECONDS = 10800.0
PAIR_RESERVATION_SECONDS = 300.0
PERSISTENCE_MARGIN_SECONDS = 10.0
FATAL_RUNTIME_STATUSES = {"fatal_audit_error", "cleanup_failed", "thread_identity_unavailable",
                         "session_reset", "raw_overflow", "budget_denied",
                         "unauthorized_tool_request", "cleanup_unverified"}


def _safe_raw(value: Any) -> str | None:
    if value is None:
        return None
    # Preserve the complete response for audit; redact credentials but do not
    # silently truncate evidence. Error messages use bounded safe_text instead.
    import re
    text = str(value).replace("\x00", "")
    return re.sub(r"(?i)\b(?:bearer\s+|sk-|rk-|gh[pousr]_|xox[baprs]-)[A-Za-z0-9._-]{12,}",
                  "[redacted]", text)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("development", "exploratory"), default="development")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="frozen synthetic corpus JSON")
    parser.add_argument("--output", help="new exclusive run directory under runs/; never overwritten")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--reasoning-effort", default=REASONING_EFFORT)
    parser.add_argument("--enable-model-calls", action="store_true", help="explicitly enable paid SDK calls")
    parser.add_argument("--dependency-audit-approved", action="store_true",
                        help="assert independent pre-run review of pair/stem dependencies")
    parser.add_argument("--offline-gold-fixture", action="store_true",
                        help="grade synthetic answer-key fixtures; NOT model evidence")
    return parser


def _groups(cases: list[dict[str, Any]], repetitions: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    groups: list[dict[str, Any]] = []
    scheduled_cases = list(cases)
    rng.shuffle(scheduled_cases)
    for repetition in range(1, repetitions + 1):
        for case in scheduled_cases:
            order = list(ARMS)
            rng.shuffle(order)
            groups.append({
                "case_id": case["id"], "repetition": repetition,
                "scheduled_arm_order": order, "status": "not_started",
                "arms": {arm: {"status": "not_started", "turns": [],
                               "delivery_valid": False,
                               "observed_delivery_seconds": None,
                               "deadline_penalty_seconds": None,
                               "structured_semantic_score": None,
                               "structured_delivery_utility": None,
                               "grade": None, "error": None, "usage": None}
                         for arm in ARMS},
            })
    return groups


def _gold_output(case: Mapping[str, Any]) -> dict[str, Any]:
    return {"answers": {q["id"]: q["expected"] for q in case["questions"]},
            "citations": list(case.get("required_citations", [])),
            "explanation": "synthetic-only; offline gold fixture, not a model response."}


def _grade(case: dict[str, Any], raw: str | dict[str, Any]) -> dict[str, Any]:
    from nova.benchmark_parallel_cases import grade_response
    return grade_response(case, raw)


async def _mark_arm_failure(*, case: dict[str, Any], group: dict[str, Any], arm: str,
                            message: Any, arm_row: dict[str, Any], arm_start: float,
                            store: DurableRunStore, report: dict[str, Any]) -> None:
    arm_row.update({"status": "failed", "error": safe_text(message),
                    "runtime_status": "cleanup_unverified", "cleanup_ok": False,
                    "fatal_audit": True,
                    "terminal_seconds": max(0.0, time.monotonic() - arm_start),
                    "delivery_valid": False, "observed_delivery_seconds": None,
                    "deadline_penalty_seconds": DEADLINE_SECONDS,
                    "structured_delivery_utility": 0.0})
    store.append("arm_failed", {"case_id": case["id"], "repetition": group["repetition"],
                                "arm": arm, "error": safe_text(message),
                                "deadline_penalty_seconds": DEADLINE_SECONDS})
    store.checkpoint(report)


async def _execute_arm(*, case: dict[str, Any], group: dict[str, Any], arm: str,
                       model: str, reasoning_effort: str, budget: AtomicTurnBudget,
                       store: DurableRunStore, report: dict[str, Any],
                       arm_deadline_at: float) -> None:
    arm_row = group["arms"][arm]
    arm_row["status"] = "running"
    arm_start = time.monotonic()
    store.append("arm_started", {"case_id": case["id"], "repetition": group["repetition"], "arm": arm})
    store.checkpoint(report)
    from nova.benchmark_parallel_runtime import run_arm

    async def before_dispatch(role: str) -> int:
        return await budget.before_dispatch(packet_id=case["id"], repetition=group["repetition"],
                                            arm=arm, role=role)

    try:
        runtime_budget = arm_deadline_at - time.monotonic() - PERSISTENCE_MARGIN_SECONDS
        if runtime_budget <= 0:
            await _mark_arm_failure(case=case, group=group, arm=arm,
                                    message="reserved delivery deadline exhausted", arm_row=arm_row,
                                    arm_start=arm_start, store=store, report=report)
            return
        result = await asyncio.wait_for(
            run_arm(case["packet"], arm, model, reasoning_effort, before_dispatch,
                    turn_timeout=45, arm_timeout=runtime_budget),
            timeout=runtime_budget,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if budget.failed:
            raise RuntimeError("parent budget/journal failed closed") from exc
        await _mark_arm_failure(case=case, group=group, arm=arm, message=exc,
                                arm_row=arm_row, arm_start=arm_start, store=store, report=report)
        return

    if not isinstance(result, Mapping):
        raise TypeError("run_arm must return a mapping")
    raw = _safe_raw(result.get("final_raw"))
    arm_row["turns"] = result.get("turns") if isinstance(result.get("turns"), list) else []
    arm_row["usage"] = result.get("usage")
    runtime_status = result.get("status")
    arm_row["runtime_status"] = safe_text(runtime_status, 120)
    unauthorized_tool = any(
        isinstance(turn, Mapping) and turn.get("status") == "unauthorized_tool_request"
        for turn in arm_row["turns"]
    )
    arm_row["fatal_audit"] = result.get("fatal_audit") is True or unauthorized_tool
    arm_row["cleanup_ok"] = result.get("cleanup_ok") is True
    arm_row["runtime_wall_seconds"] = result.get("wall_seconds")
    arm_row["raw_response"] = raw
    arm_row["error"] = safe_text(result.get("error")) if result.get("error") else None
    grade = _grade(case, raw) if raw is not None else None
    arm_row["grade"] = grade
    arm_row["structured_semantic_score"] = grade.get("semantic_score") if grade else None
    arm_row["status"] = "completed" if runtime_status == "success" and arm_row["cleanup_ok"] else "failed"
    arm_row["delivery_valid"] = bool(
        runtime_status == "success" and arm_row["cleanup_ok"] and grade
        and grade.get("strict_schema_pass") is True
        and grade.get("citation_pass") is True and grade.get("scope_pass") is True
    )
    score = grade.get("semantic_score") if grade else None
    arm_row["structured_delivery_utility"] = (
        float(score) if arm_row["delivery_valid"] and isinstance(score, (int, float))
        and not isinstance(score, bool) and math.isfinite(float(score)) else 0.0
    )
    arm_row["terminal_seconds"] = max(0.0, time.monotonic() - arm_start)
    store.append("arm_output_graded", {
        "case_id": case["id"], "repetition": group["repetition"], "arm": arm,
        "status": arm_row["status"], "raw_response_sha256": sha256_json(raw),
        "grade": grade, "delivery_valid": arm_row["delivery_valid"],
        "cleanup_ok": arm_row["cleanup_ok"],
    })
    store.checkpoint(report)
    if runtime_status in FATAL_RUNTIME_STATUSES or arm_row["fatal_audit"] or not arm_row["cleanup_ok"]:
        group["status"] = "failed"
        store.checkpoint(report)
        raise RuntimeError(f"fatal runtime/cleanup state: {runtime_status}")
    elapsed = max(0.0, time.monotonic() - arm_start)
    if arm_row["delivery_valid"] and elapsed <= DEADLINE_SECONDS:
        arm_row["observed_delivery_seconds"] = elapsed
        arm_row["deadline_penalty_seconds"] = elapsed
    else:
        arm_row["delivery_valid"] = False
        arm_row["observed_delivery_seconds"] = None
        arm_row["deadline_penalty_seconds"] = DEADLINE_SECONDS
        arm_row["structured_delivery_utility"] = 0.0
    store.append("arm_terminal", {
        "case_id": case["id"], "repetition": group["repetition"], "arm": arm,
        "status": arm_row["status"], "observed_delivery_seconds": arm_row["observed_delivery_seconds"],
        "deadline_penalty_seconds": arm_row["deadline_penalty_seconds"],
    })
    store.checkpoint(report)


async def _run(args: argparse.Namespace) -> int:
    from nova.benchmark_parallel_cases import load_corpus

    corpus_path = Path(args.corpus).resolve()
    corpus = load_corpus(corpus_path)
    cases = corpus.get(args.stage)
    if not isinstance(cases, list) or len(cases) != (4 if args.stage == "development" else 24):
        raise ValueError("corpus has the wrong frozen case count for selected stage")
    repetitions = 1 if args.stage == "development" else 2
    turns_limit = len(cases) * repetitions * len(ARMS) * 3
    if args.enable_model_calls and args.offline_gold_fixture:
        raise ValueError("gold fixture and live model calls are mutually exclusive")
    if args.enable_model_calls and args.stage == "exploratory" and not args.dependency_audit_approved:
        raise ValueError("live exploratory calls require explicit independent dependency-audit approval")
    if args.offline_gold_fixture and args.enable_model_calls:
        raise ValueError("offline gold fixtures may never be mixed with model calls")

    run_dir = create_run_directory(args.output)
    store = DurableRunStore(run_dir)
    runtime_path = ROOT / "nova" / "benchmark_parallel_runtime.py"
    worker_path = ROOT / "scripts" / "parallel_selftest_worker.py"
    cases_module_path = ROOT / "nova" / "benchmark_parallel_cases.py"
    host_helper_path = ROOT / "scripts" / "run_omnigent_live.py"
    groups = _groups(cases, repetitions, seed=1729)
    scheduled_batches = [groups[i:i + 8] for i in range(0, len(groups), 8)]
    report: dict[str, Any] = {
        "schema_version": 1, "benchmark": "nova_parallel_selftest_v1",
        "stage": args.stage, "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "synthetic_offline_engineering_self_test_only",
        "corpus_version": corpus.get("version"), "corpus_sha256": sha256_file(corpus_path),
        "script_sha256": sha256_file(Path(__file__)),
        "report_module_sha256": sha256_file(Path(__file__).parents[1] / "nova" / "benchmark_parallel_report.py"),
        "runtime_module_sha256": sha256_file(runtime_path) if runtime_path.exists() else None,
        "worker_module_sha256": sha256_file(worker_path) if worker_path.exists() else None,
        "case_grader_sha256": sha256_file(cases_module_path) if cases_module_path.exists() else None,
        "host_helper_sha256": sha256_file(host_helper_path) if host_helper_path.exists() else None,
        "omnigent_version": _package_version("omnigent"),
        "python_version": sys.version.split()[0], "platform": sys.platform,
        "requested_max_tokens_per_turn": 1200 if args.enable_model_calls else None,
        "provider_hard_token_limit_verified": False,
        "model_identity_attested": None, "provider_request_count": None,
        "provider_usage_attested": None, "billed_cost": None,
        "dependency_audit_approved": bool(args.dependency_audit_approved),
        "blind_prose_review_status": "pending", "full_semantic_quality": None,
        "full_delivery_utility_delta": None,
        "structured_grader_scope": "objective_schema_and_numeric_answer_proxy_only; prose_unreviewed",
        "model_calls_enabled": bool(args.enable_model_calls),
        "offline_gold_fixture": bool(args.offline_gold_fixture),
        "offline_gold_is_model_evidence": False,
        "model_requested": args.model if args.enable_model_calls else None,
        "reasoning_effort_requested": args.reasoning_effort if args.enable_model_calls else None,
        "repetitions": repetitions, "cases": cases,
        "limits": {"sdk_turns": turns_limit, "per_evaluation_turns": 3,
                   "turn_timeout_seconds": 45, "arm_deadline_seconds": 150,
                   "exploratory_batch_seconds": MAX_BATCH_SECONDS,
                   "exploratory_total_seconds": TOTAL_EXPLORATORY_SECONDS,
                   "pair_reservation_seconds": PAIR_RESERVATION_SECONDS,
                   "pair_persistence_margin_seconds": PERSISTENCE_MARGIN_SECONDS,
                   "retries": 0},
        "schedule_seed": 1729,
        "scheduled_group_order": [{"case_id": g["case_id"], "repetition": g["repetition"],
                                    "arm_order": g["scheduled_arm_order"]} for g in groups],
        "scheduled_group_order_sha256": sha256_json(groups),
        "fixed_batches": [[{"case_id": g["case_id"], "repetition": g["repetition"]} for g in b]
                          for b in scheduled_batches],
        "groups": groups,
        "sdk_turns_reserved": 0, "scope_complete": False,
    }
    report["frozen_manifest_sha256"] = sha256_json({
        "version": report["corpus_version"], "corpus_sha256": report["corpus_sha256"],
        "script_sha256": report["script_sha256"], "cases": cases,
        "report_module_sha256": report["report_module_sha256"],
        "limits": report["limits"],
        "stage": args.stage, "repetitions": repetitions, "sdk_turns": turns_limit,
        "model_requested": report["model_requested"],
        "reasoning_effort_requested": report["reasoning_effort_requested"],
        "runtime_module_sha256": report["runtime_module_sha256"],
        "worker_module_sha256": report["worker_module_sha256"],
        "case_grader_sha256": report["case_grader_sha256"],
        "host_helper_sha256": report["host_helper_sha256"],
        "omnigent_version": report["omnigent_version"],
        "requested_max_tokens_per_turn": report["requested_max_tokens_per_turn"],
        "provider_hard_token_limit_verified": report["provider_hard_token_limit_verified"],
        "schedule_seed": report["schedule_seed"],
        "scheduled_group_order_sha256": report["scheduled_group_order_sha256"],
        "dependency_audit_approved": report["dependency_audit_approved"],
    })
    summarize_report(report, dependency_audit_approved=args.dependency_audit_approved)
    store.append("run_manifest_frozen", {"manifest_sha256": report["frozen_manifest_sha256"],
                                         "stage": args.stage, "planned_sdk_turns": turns_limit,
                                         "model_calls_enabled": report["model_calls_enabled"]})
    store.checkpoint(report)
    budget = AtomicTurnBudget(turns_limit if args.enable_model_calls else 0, store, report)
    failed = False
    try:
        if args.offline_gold_fixture:
            for group in report["groups"]:
                case = next(c for c in cases if c["id"] == group["case_id"])
                for arm in ARMS:
                    raw = _gold_output(case)
                    grade = _grade(case, raw)
                    group["arms"][arm].update({
                        "status": "offline_gold_fixture", "raw_response": raw,
                        "grade": grade, "structured_semantic_score": grade["semantic_score"],
                        "structured_delivery_utility": None, "delivery_valid": False,
                        "observed_delivery_seconds": None, "deadline_penalty_seconds": None,
                    })
                group["status"] = "offline_gold_fixture"
            report["offline_gold_note"] = "Answer-key fixture only; no model/runtime call and no empirical claim."
            store.append("offline_gold_fixture_scored", {"groups": len(report["groups"]),
                                                          "model_calls": 0})
        elif args.enable_model_calls:
            total_cap = TOTAL_EXPLORATORY_SECONDS if args.stage == "exploratory" else MAX_BATCH_SECONDS
            total_deadline = time.monotonic() + total_cap
            batch_size = 8 if args.stage == "exploratory" else len(report["groups"])
            for batch_no, batch_offset in enumerate(range(0, len(report["groups"]), batch_size), 1):
                batch_deadline = min(total_deadline, time.monotonic() + MAX_BATCH_SECONDS)
                batch = report["groups"][batch_offset:batch_offset + batch_size]
                store.append("fixed_batch_started", {"batch": batch_no,
                                                      "planned_groups": [g["case_id"] for g in batch]})
                store.checkpoint(report)
                for group in batch:
                    now = time.monotonic()
                    # Reserve the full sequential arm pair + persistence margin
                    # before starting either arm. No final-arm shortening.
                    if min(batch_deadline, total_deadline) - now < PAIR_RESERVATION_SECONDS + PERSISTENCE_MARGIN_SECONDS:
                        group["status"] = "not_started"
                        failed = True
                        store.checkpoint(report)
                        continue
                    case = next(c for c in cases if c["id"] == group["case_id"])
                    group["status"] = "running"
                    pair_start = time.monotonic()
                    store.append("paired_group_reserved", {
                        "case_id": group["case_id"], "repetition": group["repetition"],
                        "arm_order": group["scheduled_arm_order"],
                        "reserved_seconds": PAIR_RESERVATION_SECONDS + PERSISTENCE_MARGIN_SECONDS,
                    })
                    store.checkpoint(report)
                    for arm in group["scheduled_arm_order"]:
                        # Each arm gets a fresh, full 150-second deadline from
                        # its own packet release; waiting for the other arm is
                        # outside this arm's wall-clock measurement.
                        arm_deadline_at = time.monotonic() + DEADLINE_SECONDS
                        await _execute_arm(case=case, group=group, arm=arm, model=args.model,
                                           reasoning_effort=args.reasoning_effort, budget=budget,
                                           store=store, report=report, arm_deadline_at=arm_deadline_at)
                        if group["arms"][arm].get("runtime_status") in FATAL_RUNTIME_STATUSES or \
                                group["arms"][arm].get("fatal_audit") is True or \
                                group["arms"][arm].get("cleanup_ok") is False:
                            raise RuntimeError("fatal runtime audit/cleanup state; stopping run")
                    group["status"] = "completed" if all(group["arms"][a]["status"] == "completed" for a in ARMS) else "failed"
                    if group["status"] != "completed":
                        failed = True
                    report["sdk_turns_reserved"] = budget.used
                    summarize_report(report, dependency_audit_approved=args.dependency_audit_approved)
                    store.append("paired_group_terminal", {"case_id": group["case_id"],
                                                           "repetition": group["repetition"],
                                                           "status": group["status"]})
                    store.checkpoint(report)
                store.append("fixed_batch_terminal", {"batch": batch_no,
                                                      "end_utc": datetime.now(timezone.utc).isoformat()})
                store.checkpoint(report)
        else:
            store.append("offline_manifest_created", {"groups": len(report["groups"]),
                                                       "model_calls": 0})
        report["sdk_turns_reserved"] = budget.used
        report["scope_complete"] = all(g["status"] == "completed" for g in report["groups"])
        summarize_report(report, dependency_audit_approved=args.dependency_audit_approved)
        report["runner_status"] = "completed" if report["scope_complete"] else (
            "offline_gold_fixture" if args.offline_gold_fixture else
            "offline_manifest_only" if not args.enable_model_calls else "incomplete_or_failed")
        store.append("run_terminal", {"status": report["runner_status"],
                                     "sdk_turns_reserved": budget.used})
        store.checkpoint(report)
    except BaseException as exc:
        failed = True
        for group in report.get("groups", []):
            if group.get("status") == "running":
                group["status"] = "interrupted"
        report["runner_status"] = "interrupted_or_failed"
        report["runner_error"] = safe_text(exc)
        store.append("run_interrupted", {"error": safe_text(exc), "sdk_turns_reserved": budget.used})
        store.checkpoint(report)
    finally:
        store.close()
    print(json.dumps({"run_dir": str(run_dir), "stage": args.stage,
                      "model_calls_enabled": bool(args.enable_model_calls),
                      "sdk_turns_reserved": budget.used,
                      "screening_status": report.get("summary", {}).get("screening_status")}, sort_keys=True))
    return 3 if failed else 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"parallel self-test failed: {safe_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
