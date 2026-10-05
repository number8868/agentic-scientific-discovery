#!/usr/bin/env python3
"""Run the bounded, decision-audit quality benchmark (offline by default).

This benchmark compares one-shot answering, same-role self-review, and a
three-role Planner/Skeptic/PI sequence. It is not a native workflow or science
throughput benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess
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
MAX_CASES = 6
MAX_REPETITIONS = 2
MAX_MODEL_CALLS = 84
PER_CALL_TIMEOUT_SECONDS = 45
CLEANUP_RESERVE_SECONDS = 4
TOTAL_TIMEOUT_SECONDS = 900
MAX_TOKENS = 1200
REASONING_EFFORT = "medium"
ARMS = ("single_once", "single_self_review", "multi_role")
_SECRETISH = re.compile(r"(?i)\b(?:bearer\s+|sk-|rk-|gh[pousr]_|xox[baprs]-)[A-Za-z0-9._-]{12,}")


def _safe_text(value: Any, limit: int = 3000) -> str:
    return _SECRETISH.sub("[redacted]", str(value)).replace("\x00", "")[:limit]


def _digest(value: Any) -> str:
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_decision(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    value = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid numeric constant: {value}")))
    if not isinstance(value, dict) or set(value) != {"answers", "action", "citations"}:
        raise ValueError("response must be JSON with answers, action, and citations only")
    if not isinstance(value["answers"], dict) or not isinstance(value["action"], str) or not isinstance(value["citations"], list):
        raise ValueError("decision fields have invalid types")
    if not all(isinstance(v, (str, int, float, bool)) or v is None for v in value["answers"].values()):
        raise ValueError("answers values must be scalar")
    if not all(isinstance(v, str) for v in value["citations"]):
        raise ValueError("citations must contain strings")
    return value


def _report_path(requested: str | None) -> Path:
    path = Path(requested) if requested else RUNS / f"quality-benchmark-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.json"
    if not path.is_absolute():
        path = ROOT / path
    cursor = path.parent
    while cursor != cursor.parent:
        if cursor.exists() and cursor.is_symlink():
            raise ValueError("report path may not traverse a symlink")
        if cursor == ROOT:
            break
        cursor = cursor.parent
    try:
        path.parent.resolve().relative_to(RUNS.resolve())
    except ValueError as exc:
        raise ValueError("report must be written under runs/") from exc
    if path.exists():
        raise FileExistsError("report path already exists; choose a new path")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.parent.resolve() / path.name


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


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=2, check=True).stdout.strip()
    except Exception:
        return None


def _environment() -> dict[str, Any]:
    from importlib.metadata import version
    try:
        omnigent_version = version("omnigent")
    except Exception:
        omnigent_version = None
    return {"python": sys.version.split()[0], "platform": sys.platform,
            "omnigent": omnigent_version, "model_requested": None,
            "reasoning_effort": REASONING_EFFORT,
            "requested_max_tokens_per_turn": MAX_TOKENS,
            "provider_hard_token_limit_verified": False}


def _tools() -> list[Any]:
    return []


def _role_frame(arm: str, role: str) -> str:
    if arm == "single_once":
        return "Answer the decision independently."
    if arm == "single_self_review":
        if role == "single_critique":
            return "Audit prior work for unsupported answers, action errors, and citation errors; return a complete corrected decision, not commentary."
        if role == "single_final":
            return "Make the final decision after weighing the prior role outputs; return a complete decision."
        return "Propose a complete cautious decision."
    return {"Planner": "Propose a complete cautious decision.",
            "Skeptic": ("Audit prior work for unsupported answers, action errors, and citation "
                        "errors; return a complete corrected decision, not commentary."),
            "PI": "Make the final decision after weighing the prior role outputs; return a complete decision."}[role]


async def _ask(case: Mapping[str, Any], packet: Any, arm: str, role: str,
               prior: Mapping[str, Any] | None, model: str, timeout: float) -> dict[str, Any]:
    from importlib.metadata import version
    from omnigent.inner.codex_executor import CodexExecutor
    from omnigent.inner.executor import ExecutorConfig, ExecutorError, TextChunk, ToolCallRequest, TurnComplete
    from scripts.run_omnigent_live import _minimal_codex_config, _new_codex_executor

    start = time.monotonic()
    observed: dict[str, Any] = {"arm": arm, "role": role, "model_requested": model,
                                "prompt_sha256": None, "raw_response": None, "usage": None,
                                "turn_seconds": None, "error": None, "decision": None}
    session_id = f"nova-quality-benchmark-{uuid.uuid4().hex}"
    executor = None
    chunks: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="nova-quality-benchmark-") as cwd:
            executor = _new_codex_executor(CodexExecutor, cwd, version("omnigent"), model=model)
            inp = {"case_id": case["id"], "packet": packet}
            if prior is not None:
                inp["prior_outputs"] = prior
            # Identical audit directions for both critique arms; only role framing differs.
            shared = ("Decision-audit benchmark. Use only the visible packet and the prior structured outputs, "
                      "if supplied. Do not invent evidence or citations. Do not use tools, browse, or claim an "
                      "action was performed. Answer every question ID in the packet exactly once in answers. "
                      "Cite exactly the evidence references required by the packet citation policy. Return exactly "
                      "one JSON object with keys answers (object of scalar values), action (string), citations "
                      "(array of exact citation strings). The packet contains "
                      "all task information needed; do not seek hidden rubric details.")
            role_frame = _role_frame(arm, role)
            prompt = shared + "\nRole: " + role_frame + "\nInput:\n" + json.dumps(inp, ensure_ascii=False, sort_keys=True, allow_nan=False)
            observed["prompt_sha256"] = _digest(prompt)
            completed = None
            async def consume() -> None:
                nonlocal completed
                async for event in executor.run_turn(
                    messages=[{"role": "user", "content": prompt, "session_id": session_id}],
                    tools=_tools(),
                    system_prompt=("You are the single decision-maker in a bounded, no-tools decision benchmark."
                                   if arm == "single_self_review" else
                                   f"You are the {role} in a bounded, no-tools decision benchmark."),
                    config=ExecutorConfig(model=model, max_tokens=MAX_TOKENS,
                                          extra={"reasoning_effort": REASONING_EFFORT}),
                ):
                    if isinstance(event, ToolCallRequest):
                        raise RuntimeError("SDK emitted a tool request despite the empty allowlist")
                    if isinstance(event, TextChunk) and event.text:
                        chunks.append(event.text)
                    if isinstance(event, ExecutorError):
                        observed["usage"] = dict(event.usage) if isinstance(event.usage, Mapping) else None
                        raise RuntimeError(_safe_text(event.message))
                    if isinstance(event, TurnComplete):
                        completed = event
                        if event.response:
                            chunks.append(event.response)
            try:
                with _minimal_codex_config():
                    await asyncio.wait_for(consume(), timeout=max(0.1, timeout))
            except BaseException:
                interrupt = getattr(executor, "interrupt_session", None)
                if callable(interrupt):
                    try: await asyncio.wait_for(interrupt(session_id), timeout=1)
                    except Exception: pass
                raise
            finally:
                close_session = getattr(executor, "close_session", None)
                if callable(close_session):
                    try: await asyncio.wait_for(close_session(session_id), timeout=1)
                    except Exception: pass
                close = getattr(executor, "close", None)
                if callable(close):
                    try: await asyncio.wait_for(close(), timeout=2)
                    except Exception: pass
            if completed is None or completed.continue_turn:
                raise RuntimeError("turn did not complete as a single bounded response")
            raw = completed.response if completed.response is not None else "".join(chunks)
            observed["raw_response"] = _safe_text(raw)
            observed["usage"] = dict(completed.usage) if isinstance(completed.usage, Mapping) else None
            observed["decision"] = _parse_decision(raw)
    except Exception as exc:
        if observed["raw_response"] is None and chunks:
            observed["raw_response"] = _safe_text("".join(chunks))
        observed["error"] = _safe_text(exc)
    observed["turn_seconds"] = round(time.monotonic() - start, 3)
    return observed


def _score(case: Mapping[str, Any], decision: Any) -> dict[str, Any]:
    from nova.benchmark_quality import score_decision
    try:
        value = score_decision(case, decision) if isinstance(decision, dict) else None
        if value is None:
            return {"quality_score": 0, "exact_pass": False}
        return value
    except Exception as exc:
        return {"quality_score": 0, "exact_pass": False, "score_error": _safe_text(exc)}


def _planned_prompt_hashes(case_id: str, packet: Any, arm: str) -> list[dict[str, str]]:
    roles = {"single_once": ["single"], "single_self_review": ["single_initial", "single_critique", "single_final"],
             "multi_role": ["Planner", "Skeptic", "PI"]}[arm]
    # Hash intended input structure up front; actual per-call hash additionally
    # captures the exact prior structured output when it exists.
    return [{"role": role, "sha256": _digest(json.dumps({"case_id": case_id, "packet": packet,
             "prior_outputs": "<prior output inserted only for critique/final turns>" if index else None,
             "arm": arm, "turn_index": index}, ensure_ascii=False, sort_keys=True))}
            for index, role in enumerate(roles)]


async def _execute_arm(case: Mapping[str, Any], packet: Any, arm_name: str, model: str,
                       deadline: float, call_state: dict[str, int], checkpoint: Any,
                       group: dict[str, Any]) -> None:
    from nova.benchmark_quality import score_decision
    arm = group["arms"][arm_name]
    arm["status"] = "running"
    arm_start = time.monotonic()
    turn_plans = {"single_once": [("single", None)],
                  "single_self_review": [("single_initial", None), ("single_critique", "initial"), ("single_final", "critique")],
                  "multi_role": [("Planner", None), ("Skeptic", "Planner"), ("PI", "Skeptic")]}[arm_name]
    prior: dict[str, Any] = {}
    failed = False
    for role, prior_key in turn_plans:
        # Count immediately before starting the request. Never exceed the cap.
        remaining = deadline - time.monotonic()
        if remaining <= CLEANUP_RESERVE_SECONDS + 0.1 or call_state["calls"] >= call_state.get("max_calls", MAX_MODEL_CALLS):
            failed = True
            arm["error"] = "global deadline or hard model-call cap left no bounded call"
            break
        call_state["calls"] += 1
        arm["calls_started"] = arm.get("calls_started", 0) + 1
        checkpoint()
        timeout = min(PER_CALL_TIMEOUT_SECONDS, remaining - CLEANUP_RESERVE_SECONDS)
        prior_input: dict[str, Any] | None = None
        if prior_key:
            prior_input = {"draft": prior.get(prior_key)}
        result = await _ask(case, packet, arm_name, role, prior_input, model, timeout)
        arm["turns"].append(result)
        checkpoint()
        if result.get("error") or not isinstance(result.get("decision"), dict):
            failed = True
        else:
            prior[role] = result["decision"]
            if arm_name == "single_self_review":
                prior[{"single_initial": "initial", "single_critique": "critique", "single_final": "final"}[role]] = result["decision"]
        if failed:
            break
    final = None
    if arm["turns"] and arm["turns"][-1].get("decision"):
        final = arm["turns"][-1]["decision"]
    arm["decision"] = final
    arm["final_answer_score"] = _score(case, final)
    arm["score"] = ({"quality_score": 0, "exact_pass": False, "failed_required_turn": True}
                    if failed or len(arm["turns"]) != len(turn_plans) else arm["final_answer_score"])
    arm["status"] = "failed" if failed or len(arm["turns"]) != len(turn_plans) else "completed"
    arm["elapsed_seconds"] = round(time.monotonic() - arm_start, 3)
    arm["turn_seconds_sum"] = round(sum(x.get("turn_seconds") or 0 for x in arm["turns"]), 3)
    checkpoint()


def _sign_test(deltas: list[float]) -> dict[str, Any]:
    positive = sum(x > 0 for x in deltas)
    negative = sum(x < 0 for x in deltas)
    n = positive + negative
    # Exact two-sided binomial sign test, ties excluded and reported separately.
    p = min(1.0, 2 * sum(__import__("math").comb(n, k) for k in range(min(positive, negative) + 1)) / (2 ** n)) if n else 1.0
    return {"positive": positive, "negative": negative, "ties": len(deltas) - n, "n_non_tied": n, "two_sided_p": p}


def _aggregate(report: dict[str, Any]) -> None:
    groups = report["groups"]
    rows: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
    pairdeltas = []
    case_deltas: dict[str, list[float]] = {}
    fully_complete = bool(groups) and all(all(g["arms"][name]["status"] == "completed" for name in ARMS) for g in groups)
    for g in groups:
        sr_arm, mr_arm = g["arms"]["single_self_review"], g["arms"]["multi_role"]
        sr = sr_arm["score"].get("quality_score") if sr_arm["status"] != "not_started" else None
        mr = mr_arm["score"].get("quality_score") if mr_arm["status"] != "not_started" else None
        delta = (mr - sr) if sr is not None and mr is not None else None
        pairdeltas.append(delta)
        if delta is not None:
            case_deltas.setdefault(g["case_id"], []).append(delta)
        for name in ARMS:
            arm = g["arms"][name]
            score = arm["score"].get("quality_score") if arm["status"] != "not_started" else None
            rows[name].append({"case_id": g["case_id"], "repetition": g["repetition"], "status": arm["status"],
                               "score": score,
                               "exact_pass": arm["score"].get("exact_pass") if score is not None else None,
                               "elapsed_seconds": arm.get("elapsed_seconds"),
                               "turn_seconds_sum": arm.get("turn_seconds_sum")})
    summaries = {}
    for name, vals in rows.items():
        attempted = [v for v in vals if v["score"] is not None]
        scores = [v["score"] for v in attempted]
        exact = [v["exact_pass"] for v in attempted]
        times = [v["elapsed_seconds"] for v in vals if v["elapsed_seconds"] is not None]
        turntimes = [v["turn_seconds_sum"] for v in vals if v["turn_seconds_sum"] is not None]
        summaries[name] = {"n_planned": len(vals), "n_attempted": len(attempted),
                           "n_completed": sum(v["status"] == "completed" for v in vals),
                           "n_failed": sum(v["status"] == "failed" for v in vals),
                           "n_not_started": sum(v["status"] == "not_started" for v in vals), "raw": vals,
                           "mean_quality_score": sum(scores) / len(scores) if scores else None,
                           "exact_pass_rate": sum(exact) / len(exact) if exact else None,
                           "mean_arm_elapsed_seconds": sum(times) / len(times) if times else None,
                           "mean_turn_seconds_sum": sum(turntimes) / len(turntimes) if turntimes else None}
    report["summary"] = summaries
    report["summary_status"] = ("not_run" if not report.get("model_calls_enabled") else
                                 "measured_complete_requested_scope" if fully_complete else "measured_partial")
    comparison = {"raw_group_deltas": pairdeltas,
                                                       "n_paired_attempted": sum(d is not None for d in pairdeltas),
                                                       "n_unmatched_not_started": sum(d is None for d in pairdeltas),
                                                       "mean_delta": sum(d for d in pairdeltas if d is not None) / sum(d is not None for d in pairdeltas) if any(d is not None for d in pairdeltas) else None,
                                                       "repeat_pair_signs_descriptive_only": _sign_test([d for d in pairdeltas if d is not None]),
                                                       "case_mean_deltas": {cid: sum(ds) / len(ds) for cid, ds in case_deltas.items()},
                                                       "casewise_sign_test": _sign_test([sum(ds) / len(ds) for ds in case_deltas.values()]) if fully_complete and report.get("scope_complete") else None,
                                                       "bootstrap_95_percentile_ci": _cluster_bootstrap(groups, lambda g: g["arms"]["multi_role"]["score"]["quality_score"] - g["arms"]["single_self_review"]["score"]["quality_score"]) if fully_complete else {"lower": None, "upper": None, "not_computed_incomplete": True},
                                                       "predeclared_interpretation": "quality gain is established only if mean delta > 0, the case-cluster 95% interval excludes 0, and the exact casewise two-sided sign test has p < 0.05; otherwise report descriptive evidence only",
                                                       "efficiency_interpretation": "no efficiency claim unless paired elapsed-time reduction has a confidence interval above 0 and quality is non-inferior within 0.02; score-per-second alone is not evidence"}
    comparison["quality_classification"] = "descriptive_only"
    comparison["efficiency_classification"] = "not_established"
    if report.get("model_calls_enabled") and report.get("scope_complete") and fully_complete:
        ci = comparison["bootstrap_95_percentile_ci"]
        st = comparison["casewise_sign_test"]
        mean = comparison["mean_delta"]
        if mean > 0 and ci["lower"] is not None and ci["lower"] > 0 and st["two_sided_p"] < .05:
            comparison["quality_classification"] = "gain_established_under_preregistered_rule"
        times = []
        for g in groups:
            srtime = g["arms"]["single_self_review"].get("elapsed_seconds")
            mrtime = g["arms"]["multi_role"].get("elapsed_seconds")
            if srtime is not None and mrtime is not None:
                times.append((g["case_id"], srtime - mrtime,
                              g["arms"]["multi_role"]["score"]["quality_score"] - g["arms"]["single_self_review"]["score"]["quality_score"]))
        if len(times) == len(groups):
            tc = _cluster_bootstrap(groups, lambda g: (g["arms"]["single_self_review"]["elapsed_seconds"] - g["arms"]["multi_role"]["elapsed_seconds"]))
            noninferior = all(x[2] >= -0.02 for x in times)
            comparison["paired_time_reduction_ci"] = tc
            comparison["quality_noninferiority_margin"] = 0.02
            comparison["quality_noninferior_all_pairs"] = noninferior
            if tc["lower"] is not None and tc["lower"] > 0 and noninferior:
                comparison["efficiency_classification"] = "elapsed_time_reduction_with_quality_noninferiority"
    report["paired_multi_role_minus_self_review"] = comparison


def _cluster_bootstrap(groups: list[dict[str, Any]], value: Any = None) -> dict[str, Any]:
    rng = random.Random(7419)
    by_case: dict[str, list[float]] = {}
    for g in groups:
        val = value(g) if value is not None else g["arms"]["multi_role"]["score"]["quality_score"] - g["arms"]["single_self_review"]["score"]["quality_score"]
        by_case.setdefault(g["case_id"], []).append(val)
    ids = list(by_case)
    if not ids:
        return {"lower": None, "upper": None, "resamples": 5000, "seed": 7419, "unit": "case_cluster"}
    dist = []
    for _ in range(5000):
        sampled = [rng.choice(ids) for __ in ids]
        ds = [d for cid in sampled for d in by_case[cid]]
        dist.append(sum(ds) / len(ds))
    dist.sort()
    return {"lower": dist[int(.025 * (len(dist) - 1))], "upper": dist[int(.975 * (len(dist) - 1))],
            "resamples": 5000, "seed": 7419, "unit": "case_cluster", "case_clusters": len(ids)}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--enable-model-calls", action="store_true", help="enable bounded model calls (otherwise offline manifest only)")
    p.add_argument("--output", help="new report path under runs/; never overwrite")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--repetitions", type=int, default=2)
    p.add_argument("--max-calls", type=int, default=MAX_MODEL_CALLS)
    p.add_argument("--case-limit", type=int, default=MAX_CASES, help=argparse.SUPPRESS)
    return p


async def _run(args: argparse.Namespace) -> int:
    from nova.benchmark_quality import FROZEN_CORPUS_SHA256, corpus_sha256, load_corpus, visible_packet
    if not 1 <= args.repetitions <= MAX_REPETITIONS or not 1 <= args.case_limit <= MAX_CASES:
        raise ValueError("repetitions and case-limit must be within frozen limits")
    if not 1 <= args.max_calls <= MAX_MODEL_CALLS:
        raise ValueError("max-calls must be between 1 and 84")
    corpus = load_corpus()
    cases = corpus.get("cases")
    if not isinstance(cases, list) or len(cases) != MAX_CASES:
        raise ValueError("quality corpus must contain exactly six cases")
    digest = corpus_sha256(corpus)
    if digest != FROZEN_CORPUS_SHA256:
        raise ValueError("quality corpus hash does not match frozen digest")
    chosen = cases[:args.case_limit]
    rng = random.Random(1729)
    groups = []
    for case in chosen:
        for rep in range(1, args.repetitions + 1):
            order = list(ARMS)
            rng.shuffle(order)
            groups.append({"case_id": case["id"], "repetition": rep, "scheduled_arm_order": order,
                           "visible_packet": visible_packet(case), "planned_prompt_hashes": {name: _planned_prompt_hashes(case["id"], visible_packet(case), name) for name in ARMS},
                           "arms": {name: {"status": "not_started", "turns": [],
                           "decision": None, "score": {},
                           "final_answer_score": None, "calls_started": 0} for name in ARMS}})
    report = {"schema_version": 1, "benchmark": "nova_quality_decision_audit_v1",
              "created_at": datetime.now(timezone.utc).isoformat(), "corpus_sha256": digest,
              "script_sha256": _digest(Path(__file__).read_bytes()), "git_commit": _git_commit(),
              "environment": _environment(), "limits": {"max_cases": MAX_CASES, "repetitions": args.repetitions,
              "max_model_calls": min(args.max_calls, MAX_MODEL_CALLS), "per_call_timeout_seconds": PER_CALL_TIMEOUT_SECONDS,
              "cleanup_reserve_seconds": CLEANUP_RESERVE_SECONDS, "total_timeout_seconds": TOTAL_TIMEOUT_SECONDS,
              "requested_max_tokens_per_turn": MAX_TOKENS, "provider_hard_token_limit_verified": False,
              "reasoning_effort": REASONING_EFFORT},
              "model_calls_enabled": bool(args.enable_model_calls), "model_requested": args.model,
              "model_calls_used": 0, "scope_complete": len(chosen) == MAX_CASES and args.repetitions == MAX_REPETITIONS,
              "scope_note": None if len(chosen) == MAX_CASES else "incomplete case scope requested for tests",
              "groups": groups}
    _aggregate(report)
    path = _report_path(args.output)
    output = _ReportFile(path)
    output.checkpoint(report)
    failed = False
    call_state = {"calls": 0, "max_calls": min(args.max_calls, MAX_MODEL_CALLS)}
    if args.enable_model_calls:
        deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
        try:
            for group in groups:
                case = next(c for c in chosen if c["id"] == group["case_id"])
                for arm_name in group["scheduled_arm_order"]:
                    if call_state["calls"] >= call_state["max_calls"] or time.monotonic() >= deadline:
                        failed = True
                        break
                    await _execute_arm(case, group["visible_packet"], arm_name, args.model,
                                       deadline, call_state, lambda: (report.__setitem__("model_calls_used", call_state["calls"]), _aggregate(report), output.checkpoint(report)),
                                       group)
                    if group["arms"][arm_name]["status"] != "completed":
                        failed = True
                if failed:
                    break
        except Exception as exc:
            failed = True
            report["runner_error"] = _safe_text(exc)
        report["model_calls_used"] = call_state["calls"]
        for group in groups:
            for arm in group["arms"].values():
                if arm["status"] == "not_started":
                    arm["status"] = "not_started"
        _aggregate(report)
        output.checkpoint(report)
    output.close()
    print(json.dumps({"report": str(path), "model_calls_enabled": report["model_calls_enabled"],
                      "model_calls_used": report["model_calls_used"], "groups": len(groups)}, sort_keys=True))
    return 3 if failed else 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        print(f"quality benchmark failed: {_safe_text(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
