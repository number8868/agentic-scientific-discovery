#!/usr/bin/env python3
"""Run a bounded, decision-only benchmark over the frozen NOVA corpus.

By default this runs the fixed-rule arm only and makes no model calls. The
optional Omnigent arm is a hosted SDK decision comparison, not native dispatch
and not the complete scientific workflow. It cannot execute science.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNS = ROOT / "runs"
MODEL = "gpt-6-luna"
MAX_CASES = 1
MAX_REPETITIONS = 1
MAX_MODEL_CALLS = 4
PER_CALL_TIMEOUT_SECONDS = 45
TOTAL_TIMEOUT_SECONDS = 180
ROLES = ("planner", "skeptic", "pi")
_SECRETISH = re.compile(r"(?i)\b(?:bearer\s+|sk-|rk-|gh[pousr]_|xox[baprs]-)[A-Za-z0-9._-]{12,}")


def _safe_text(value: Any, limit: int = 1200) -> str:
    return _SECRETISH.sub("[redacted]", str(value)).replace("\x00", "")[:limit]


def _parse_decision(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:].strip()
    decision = json.loads(raw)
    if not isinstance(decision, dict) or set(decision) != {"action", "citations", "claim_tags"}:
        raise ValueError("model response must be JSON with action, citations, and claim_tags only")
    if not isinstance(decision["action"], str) or not isinstance(decision["citations"], list) or not isinstance(decision["claim_tags"], list):
        raise ValueError("model decision fields have invalid types")
    if not all(isinstance(item, str) for item in decision["citations"] + decision["claim_tags"]):
        raise ValueError("citations and claim_tags must contain strings")
    return decision


def _report_path(requested: str | None) -> Path:
    runs_resolved = RUNS.resolve()
    path = Path(requested) if requested else RUNS / f"decision-benchmark-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.json"
    if not path.is_absolute():
        path = ROOT / path
    parent = path.parent
    # Reject symlinked path components so containment cannot be redirected.
    cursor = parent
    while cursor != cursor.parent:
        if cursor.exists() and cursor.is_symlink():
            raise ValueError("report path may not traverse a symlink")
        if cursor == ROOT:
            break
        cursor = cursor.parent
    resolved_parent = parent.resolve()
    try:
        resolved_parent.relative_to(runs_resolved)
    except ValueError as exc:
        raise ValueError("report must be written under runs/") from exc
    if path.exists():
        raise FileExistsError("report path already exists; choose a new path")
    resolved_parent.mkdir(parents=True, exist_ok=True)
    return resolved_parent / path.name


class _ReportFile:
    def __init__(self, path: Path):
        self.path = path
        self.stream = path.open("x", encoding="utf-8")

    def checkpoint(self, report: dict[str, Any]) -> None:
        data = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        self.stream.seek(0)
        self.stream.write(data)
        self.stream.truncate()
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self) -> None:
        self.stream.close()


def _tool_for_roles() -> list[Any]:
    # No SDK tools are exposed to model turns; fail closed if this API changes.
    return []


async def _ask_role(case: Mapping[str, Any], role: str, model: str, timeout: int,
                   prior_decisions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    from importlib.metadata import version
    from omnigent.inner.codex_executor import CodexExecutor
    from omnigent.inner.executor import ExecutorConfig, ExecutorError, TextChunk, ToolCallRequest, TurnComplete
    from scripts.run_omnigent_live import _minimal_codex_config, _new_codex_executor

    started = time.monotonic()
    result: dict[str, Any] = {"role": role, "model_requested": model, "raw_response": None,
                              "usage": None, "elapsed_seconds": None, "error": None}
    session_id = f"nova-decision-benchmark-{uuid.uuid4().hex}"
    executor = None
    try:
        with tempfile.TemporaryDirectory(prefix="nova-decision-benchmark-") as cwd:
            executor = _new_codex_executor(CodexExecutor, cwd, version("omnigent"), model=model)
            chunks: list[str] = []
            completed: TurnComplete | None = None
            # Only the evidence packet and decision constraints reach the model;
            # rubric answer keys (acceptable_actions, required refs, supported tags) stay host-side.
            prompt_data = {key: case.get(key) for key in (
                "id", "context", "available_actions", "remaining_experiment_slots",
                "available_citations", "available_claim_tags", "evidence")}
            if prior_decisions:
                prompt_data["prior_role_outputs"] = prior_decisions
            prompt = (
                "This is a decision-only benchmark. Do not run experiments, execute SQL, use tools, or claim that "
                "any action has been authorized or performed. Choose a proposed action from available_actions. "
                "Return exactly one JSON object with keys action, citations, claim_tags. Citations must be exact "
                "result references shown in the supplied case. claim_tags must be selected only from the supplied "
                "labels and must not imply execution. "
                + {"planner": "Propose a cautious option using the packet.",
                   "skeptic": "Independently challenge the prior roles for unsupported inference and citation errors.",
                   "pi": "Make the final decision after weighing the prior role outputs."}.get(role, "Choose independently for the single-role arm.") + " "
                "Input:\n" + json.dumps(prompt_data, sort_keys=True, ensure_ascii=False, allow_nan=False)
            )
            async def consume() -> None:
                nonlocal completed
                async for event in executor.run_turn(
                    messages=[{"role": "user", "content": prompt, "session_id": session_id}],
                    tools=_tool_for_roles(),
                    system_prompt=f"You are the independent {role} decision role in a bounded benchmark. No tools are available.",
                    config=ExecutorConfig(model=model, max_tokens=600, extra={"reasoning_effort": "low"}),
                ):
                    if isinstance(event, ToolCallRequest):
                        raise RuntimeError("SDK emitted a tool request despite the empty tool allowlist")
                    if isinstance(event, TextChunk) and event.text:
                        chunks.append(event.text)
                    if isinstance(event, ExecutorError):
                        result["error"] = _safe_text(event.message)
                        result["usage"] = dict(event.usage) if isinstance(event.usage, Mapping) else None
                        raise RuntimeError(result["error"])
                    if isinstance(event, TurnComplete):
                        completed = event
                        if event.response:
                            chunks.append(event.response)
            try:
                with _minimal_codex_config():
                    await asyncio.wait_for(consume(), timeout=timeout)
            except BaseException:
                interrupt = getattr(executor, "interrupt_session", None)
                if callable(interrupt):
                    try:
                        await asyncio.wait_for(interrupt(session_id), timeout=1)
                    except Exception:
                        pass
                raise
            finally:
                close_session = getattr(executor, "close_session", None)
                if callable(close_session):
                    try:
                        await asyncio.wait_for(close_session(session_id), timeout=1)
                    except Exception:
                        pass
                close = getattr(executor, "close", None)
                if callable(close):
                    try:
                        await asyncio.wait_for(close(), timeout=2)
                    except Exception:
                        pass
            if completed is None or completed.continue_turn:
                raise RuntimeError("SDK turn did not complete as a single bounded decision")
            response = completed.response if completed.response is not None else "".join(chunks)
            result["raw_response"] = _safe_text(response)
            result["usage"] = dict(completed.usage) if isinstance(completed.usage, Mapping) else None
            result["decision"] = _parse_decision(response)
    except Exception as exc:
        if result["raw_response"] is None and "chunks" in locals():
            result["raw_response"] = _safe_text("".join(chunks))
        result["error"] = _safe_text(exc)
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


async def _run_live(case: Mapping[str, Any], model: str, deadline: float,
                    report: dict[str, Any], checkpoint: Any) -> int:
    from nova.benchmark_decisions import score_decision

    report.update({"model": model, "single_decision": None, "single_score": None,
                   "multi_role_decisions": {}, "role_scores": {}, "score": None,
                   "single_error": None, "multi_role_error": None})
    calls = 0
    remaining = deadline - time.monotonic()
    if remaining > 13:
        single_timeout = min(PER_CALL_TIMEOUT_SECONDS, int(remaining - 13))
        result = await _ask_role(case, "single", model, single_timeout)
        calls += 1
        report["roles"].append(result)
        if result.get("error") or "decision" not in result:
            report["single_error"] = result.get("error") or "single role returned no decision"
        else:
            selected = result["decision"]
            report["single_decision"] = selected
            try:
                report["single_score"] = score_decision(case, selected)
            except Exception as exc:
                report["single_score"] = {"structural_pass": False, "error": _safe_text(exc),
                                          "scoring_scope": "structural_check_only_not_semantic_accuracy"}
        checkpoint(calls)
    else:
        report["single_error"] = "global model-call deadline leaves no time for a bounded call and cleanup"
    prior: dict[str, Any] = {}
    failed_roles: list[str] = []
    for role in ROLES:
        remaining = deadline - time.monotonic()
        cleanup_reserve = 3 * (3 - ROLES.index(role))
        if remaining <= cleanup_reserve + 1:
            report["multi_role_error"] = "global model-call deadline expired"
            break
        timeout = min(PER_CALL_TIMEOUT_SECONDS, int(remaining - cleanup_reserve - 1))
        result = await _ask_role(case, role, model, timeout, prior)
        calls += 1
        report["roles"].append(result)
        if result.get("error") or "decision" not in result:
            failed_roles.append(role)
            prior[role] = {"error": result.get("error") or "role returned no decision"}
        else:
            prior[role] = result["decision"]
            report["multi_role_decisions"][role] = result["decision"]
            try:
                report["role_scores"][role] = score_decision(case, result["decision"])
            except Exception as exc:
                report["role_scores"][role] = {"structural_pass": False, "error": _safe_text(exc),
                                                "scoring_scope": "structural_check_only_not_semantic_accuracy"}
        checkpoint(calls)
    if failed_roles:
        report["multi_role_error"] = "failed roles: " + ", ".join(failed_roles)
    if "pi" in report["multi_role_decisions"]:
        report["decision"] = report["multi_role_decisions"]["pi"]
        try:
            report["score"] = score_decision(case, report["decision"])
        except Exception as exc:
            report["score"] = {"structural_pass": False, "error": _safe_text(exc),
                                "scoring_scope": "structural_check_only_not_semantic_accuracy"}
    invalid_scores = any(not score.get("structural_pass", False) for score in
                         [report.get("single_score") or {}, report.get("score") or {},
                          *report["role_scores"].values()])
    if report["single_error"] or report["multi_role_error"] or invalid_scores:
        report["status"] = "failed"
    else:
        report["status"] = "completed"
    return calls


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-model-calls", action="store_true", help="enable the bounded Omnigent SDK decision arm (up to four calls)")
    parser.add_argument("--model", default=MODEL, help="requested Omnigent model (default: gpt-6-luna)")
    parser.add_argument("--output", help="new JSON report path under runs/ (must not already exist)")
    return parser


async def _run(args: argparse.Namespace) -> int:
    from nova.benchmark_decisions import (FROZEN_CORPUS_SHA256, corpus_sha256, fixed_decision,
                                          load_corpus, score_decision)

    corpus = load_corpus()
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("decision benchmark corpus has no cases")
    actual_corpus_sha256 = corpus_sha256(corpus)
    if actual_corpus_sha256 != FROZEN_CORPUS_SHA256:
        raise ValueError("decision benchmark corpus does not match the frozen v1 digest")
    fixed_cases = cases
    report: dict[str, Any] = {
        "schema_version": 1,
        "benchmark": "nova_decision_benchmark_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_sha256": actual_corpus_sha256,
        "limits": {"max_cases": MAX_CASES, "repetitions": MAX_REPETITIONS,
                   "max_model_calls": MAX_MODEL_CALLS, "per_call_timeout_seconds": PER_CALL_TIMEOUT_SECONDS,
                   "total_timeout_seconds": TOTAL_TIMEOUT_SECONDS},
        "model_calls_enabled": bool(args.enable_model_calls),
        "model_calls_used": 0,
        "arms": [],
    }
    for case in fixed_cases:
        fixed = fixed_decision(case)
        report["arms"].append({"kind": "fixed_rule", "case_id": case["id"], "decision": fixed,
                               "score": score_decision(case, fixed)})
    report_path = _report_path(args.output)
    output_file = _ReportFile(report_path)
    output_file.checkpoint(report)
    if args.enable_model_calls:
        # The live pilot is deliberately one frozen case and at most four calls.
        case = cases[0]
        live_case = dict(case)
        live_case["evidence"] = corpus.get("evidence", {})
        arm: dict[str, Any] = {"kind": "omnigent_sdk_decision_benchmark", "case_id": case["id"],
                               "claim_scope": "sdk_hosted_role_decision_only_not_native_dispatch_or_full_workflow",
                               "roles": [], "status": "running", "single_decision": None,
                               "single_score": None, "multi_role_decisions": {}, "role_scores": {},
                               "score": None, "single_error": None, "multi_role_error": None}
        report["arms"].append(arm)
        output_file.checkpoint(report)
        deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
        try:
            calls = await _run_live(
                live_case, args.model, deadline, arm,
                lambda used: (report.__setitem__("model_calls_used", used), output_file.checkpoint(report)),
            )
            report["model_calls_used"] = calls
        except Exception as exc:
            arm["status"] = "failed"
            arm["error"] = _safe_text(exc)
        output_file.checkpoint(report)
    print(json.dumps({"report": str(report_path), "model_calls_enabled": report["model_calls_enabled"],
                      "model_calls_used": report["model_calls_used"], "cases": len(fixed_cases)}, sort_keys=True))
    output_file.close()
    return 3 if args.enable_model_calls and any(arm.get("kind") == "omnigent_sdk_decision_benchmark" and
                                                 arm.get("status") != "completed"
                                                 for arm in report["arms"]) else 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"decision benchmark failed: {_safe_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
