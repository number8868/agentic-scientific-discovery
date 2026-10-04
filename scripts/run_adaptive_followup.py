#!/usr/bin/env python3
"""Ask one bounded Codex decision for the next discovery follow-up.

This extension starts from an already completed, live family_screen result.
It never provisions a run or executes a holdout.  The legacy eight-turn pilot
is left untouched.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOTAL_TIMEOUT_SECONDS = 12 * 60
MODEL = "gpt-6-luna"
_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS adaptive_followup_decisions (
    run_id TEXT PRIMARY KEY,
    parent_result_id TEXT NOT NULL,
    choice TEXT NOT NULL,
    reason TEXT NOT NULL,
    packet_json TEXT NOT NULL,
    selection_json TEXT NOT NULL
)
"""
_TOOL_NAME = "select_discovery_followup"


def _load_parent(database: Path, run_id: str):
    from nova.contracts import Split, Template
    from nova.storage import Storage

    store = Storage(database).initialize()
    events = store.list_events(run_id)
    if not events or any(event.mode.value != "live" for event in events):
        raise ValueError("adaptive follow-up requires a live run")
    prior_selection = [e for e in events if e.actor == "pi" and e.event_type == "second_selection"]
    prior_audit = [e for e in events if e.event_type == "method_audit_registered"]
    if prior_selection or prior_audit:
        raise ValueError("this run already has a follow-up experiment or method audit")
    parents = []
    for result in store.list_results():
        spec = store.get_spec(result.experiment_id)
        if (spec is not None and spec.template is Template.FAMILY_SCREEN and spec.split is Split.DISCOVERY
                and result.execution_status == "completed" and result.error is None
                and any(e.actor == "runner" and e.event_type == "result" and e.payload_ref == result.result_id for e in events)
                and any(e.actor == "pi" and e.event_type == "selection" and e.payload_ref == spec.experiment_id for e in events)):
            parents.append((result, spec))
    if len(parents) != 1:
        raise ValueError("adaptive follow-up requires exactly one run-owned completed family_screen result")
    result, spec = parents[0]
    if any(item.experiment_id != spec.experiment_id for item in store.list_specs()):
        raise ValueError("adaptive follow-up requires a run with no prior registered follow-up experiment")
    if result.spec_sha256 != spec.sha256 or result.dataset_sha256 != spec.dataset_sha256:
        raise ValueError("parent result does not match its registered discovery spec")
    return store, events, result, spec


def _record_selection(database: Path, run_id: str, packet: dict[str, Any], choice: str,
                      reason: str, api: Mapping[str, Callable[..., Any]],
                      deadline: float | None = None) -> dict[str, Any]:
    from nova.adaptive_policy import validate_choice
    from nova.contracts import Mode
    from nova.live_bridge import _read_context
    from nova.storage import Storage

    context_db, context_run = _read_context()
    if Path(context_db).resolve() != database.resolve() or context_run != run_id:
        raise ValueError("live context does not match adaptive selection owner")
    selection = validate_choice(packet, choice, reason)
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("adaptive follow-up deadline expired before selection registration")
    _store, _events, parent, _spec = _load_parent(database, run_id)
    if parent.result_id != packet["parent_result_id"]:
        raise ValueError("adaptive packet parent changed before selection")
    store = Storage(database).initialize()
    events = store.list_events(run_id)
    if any(e.event_type == "adaptive_followup_selected" for e in events):
        raise ValueError("an adaptive follow-up choice is already recorded")
    with sqlite3.connect(str(database), timeout=5) as db:
        db.execute(_TABLE_SQL)
        db.execute("INSERT INTO adaptive_followup_decisions VALUES (?,?,?,?,?,?)", (
            run_id, packet["parent_result_id"], choice, selection["reason"],
            json.dumps(packet, sort_keys=True, separators=(",", ":"), allow_nan=False),
            json.dumps(selection, sort_keys=True, separators=(",", ":"), allow_nan=False),
        ))
    store.append_event(run_id, "adaptive_followup_selected", actor="pi", mode=Mode.LIVE,
                       payload_ref=packet["parent_result_id"])
    if choice == "stop":
        return {"selection": selection, "outcome": "stopped", "result": None}
    if choice == "threshold_sensitivity":
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("adaptive follow-up deadline expired before threshold registration")
        review = api["submit_live_review"](
            result_id=packet["parent_result_id"], concern=selection["reason"],
            recommended_template="threshold_sensitivity",
        )
        experiment_id = api["commit_next_spec"](
            result_id=packet["parent_result_id"], recommended_template="threshold_sensitivity",
        )
        registered_spec = _store.get_spec(experiment_id)
        if (registered_spec is None or registered_spec.template.value != "threshold_sensitivity" or
                registered_spec.split.value != "discovery" or
                registered_spec.parent_result_id != packet["parent_result_id"]):
            raise ValueError("threshold follow-up ID is not the expected registered discovery spec")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("adaptive follow-up deadline expired before threshold execution")
        result = api["execute_live_registered_experiment"](experiment_id=experiment_id)
        if (getattr(result, "experiment_id", None) != experiment_id or
                getattr(result, "execution_status", None) != "completed" or
                getattr(result, "error", None) is not None):
            raise ValueError("registered threshold follow-up did not return its completed Result")
        return {"selection": selection, "review": review, "experiment_id": experiment_id,
                "outcome": "completed", "result": result}
    if choice == "method_sensitivity":
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("adaptive follow-up deadline expired before method audit registration")
        request = api["register_method_audit"](packet["parent_result_id"])
        if (not isinstance(request, Mapping) or not isinstance(request.get("audit_id"), str) or
                request.get("parent_result_id") != packet["parent_result_id"]):
            raise ValueError("method audit registration does not match its discovery parent")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("adaptive follow-up deadline expired before method audit execution")
        audit = api["execute_method_audit"](request["audit_id"])
        details = audit.get("result", {}) if isinstance(audit, Mapping) else {}
        if (details.get("execution_status") != "success" or details.get("template") != "method_sensitivity"
                or details.get("split") != "discovery"):
            raise ValueError("registered method audit did not return a successful discovery-only result")
        return {"selection": selection, "audit_id": request["audit_id"],
                "outcome": "completed", "result": audit}
    raise ValueError("unsupported adaptive choice")


def _default_api() -> dict[str, Callable[..., Any]]:
    from nova import decision_tools, live_bridge, registered_method_audit

    return {
        "submit_live_review": decision_tools.submit_live_review,
        "commit_next_spec": decision_tools.commit_next_spec,
        "execute_live_registered_experiment": live_bridge.execute_live_registered_experiment,
        "register_method_audit": registered_method_audit.register_method_audit,
        "execute_method_audit": registered_method_audit.execute_registered_method_audit,
    }


def _threshold_commit_available(database: Path, run_id: str) -> bool:
    """The legacy commit API is usable only when its host plan is present."""
    try:
        with sqlite3.connect(str(database)) as db:
            row = db.execute("SELECT plan_json FROM decision_packets WHERE run_id=?", (run_id,)).fetchone()
    except sqlite3.Error:
        return False
    if not row or not row[0]:
        return False
    try:
        plan = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(plan, Mapping) and bool(plan.get("candidate_tests"))


def _tool(packet: dict[str, Any]) -> dict[str, Any]:
    allowed = [choice for choice in packet["allowed_choices"]
               if next(item for item in packet["candidate_tests"] if item["choice"] == choice)["feasibility"]]
    return {
        "name": _TOOL_NAME,
        "description": "Select exactly one feasible, host-proposed discovery follow-up or stop. Give an evidence-grounded reason.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "choice": {"type": "string", "enum": allowed},
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["choice", "reason"],
        },
    }


async def _ask_codex(packet: dict[str, Any], model: str, timeout: int,
                     *, executor_factory: Callable[..., Any] | None = None,
                     record_event: Callable[[str], Any] | None = None) -> tuple[str, str]:
    from omnigent.inner.executor import ExecutorConfig, ExecutorError, ToolCallComplete, ToolCallRequest, TurnComplete
    from omnigent.inner.codex_executor import CodexExecutor
    from importlib.metadata import version
    from scripts.run_omnigent_live import _minimal_codex_config, _new_codex_executor, _safe_text
    import tempfile

    tool = _tool(packet)
    if not tool["parameters"]["properties"]["choice"]["enum"]:
        raise ValueError("there is no feasible decision option")
    chosen: list[tuple[str, str]] = []
    callback_attempts = 0
    completed = False
    request_count = 0
    completion_count = 0
    tool_status = None

    async def run() -> tuple[str, str]:
        with tempfile.TemporaryDirectory(prefix="nova-adaptive-codex-", dir="/tmp") as cwd:
            factory = executor_factory or _new_codex_executor
            executor = (factory(CodexExecutor, cwd, version("omnigent"), model=model)
                        if executor_factory is None else factory(cwd=cwd, model=model))
            session_id = "nova-adaptive-followup"
            async def callback(name: str, args: dict[str, Any]) -> dict[str, str]:
                nonlocal callback_attempts
                callback_attempts += 1
                if callback_attempts != 1 or name != _TOOL_NAME or set(args) != {"choice", "reason"}:
                    raise ValueError("adaptive decision function call is outside its allowlist")
                from nova.adaptive_policy import validate_choice
                validate_choice(packet, args["choice"], args["reason"])
                chosen.append((args["choice"], args["reason"]))
                if record_event is not None:
                    record_event("adaptive_choice_validated")
                return {"status": "accepted"}
            executor._tool_executor = callback
            prompt = (
                "Choose one feasible next action from this host-built packet. The evidence is from the completed "
                "discovery family screen. Method sensitivity is exploratory discovery-only and is not holdout "
                "validation or replication. Do not invent choices. Stop is always acceptable. Return your own "
                "short evidence-grounded reason.\n" + json.dumps(packet, sort_keys=True, allow_nan=False)
            )
            try:
                async def consume():
                    nonlocal completed, request_count, completion_count, tool_status
                    async for event in executor.run_turn(
                        messages=[{"role": "user", "content": prompt, "session_id": session_id}],
                        tools=[tool],
                        system_prompt="You are a bounded decision role. Call the single exposed function exactly once; do not run tools or claim a computation.",
                        config=ExecutorConfig(model=model, max_tokens=500, extra={"reasoning_effort": "low"}),
                    ):
                        if isinstance(event, ToolCallRequest):
                            request_count += 1
                            if event.name != _TOOL_NAME or request_count != 1:
                                raise ValueError("Codex requested an unexposed or repeated function")
                            if record_event is not None:
                                record_event("adaptive_tool_call_requested")
                        if isinstance(event, ToolCallComplete):
                            completion_count += 1
                            tool_status = getattr(event.status, "value", str(event.status))
                        if isinstance(event, ExecutorError):
                            raise RuntimeError(f"Codex decision call failed: {_safe_text(str(event.message))}")
                        if isinstance(event, TurnComplete):
                            completed = True
                with _minimal_codex_config():
                    await asyncio.wait_for(consume(), timeout=timeout)
                if len(chosen) != 1 or not completed or request_count != 1 or completion_count != 1 or tool_status != "success":
                    raise ValueError("Codex did not make exactly one completed adaptive choice")
                if record_event is not None:
                    record_event("adaptive_tool_call_completed")
                return chosen[0]
            except BaseException:
                try:
                    await asyncio.wait_for(executor.interrupt_session(session_id), timeout=2)
                except Exception:
                    pass
                raise
            finally:
                try:
                    await asyncio.wait_for(executor.close_session(session_id), timeout=10)
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(executor.close(), timeout=10)
                except Exception:
                    pass

    return await asyncio.wait_for(run(), timeout=timeout)


def run_adaptive_followup(*, database: Path, run_id: str, remaining_seconds: float,
                          method_audit_available: bool = True, model: str = MODEL,
                          api: Mapping[str, Callable[..., Any]] | None = None,
                          chooser: Callable[[dict[str, Any]], Any] | None = None) -> dict[str, Any]:
    """Resolve one existing run's choice, then execute only that registered option."""
    from nova.adaptive_policy import propose_followups
    from nova.live_bridge import _read_context

    db_context, context_run = _read_context()
    database = Path(database).resolve()
    if Path(db_context).resolve() != database or context_run != run_id:
        raise ValueError("live context does not match requested run")
    store, events, result, _spec = _load_parent(database, run_id)
    if (isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float))
            or not math.isfinite(float(remaining_seconds)) or remaining_seconds <= 0):
        raise ValueError("remaining_seconds must be positive for a bounded adaptive decision")
    remaining_seconds = min(float(remaining_seconds), TOTAL_TIMEOUT_SECONDS)
    packet = propose_followups(result, remaining_seconds=remaining_seconds,
                               method_audit_available=method_audit_available)
    if not _threshold_commit_available(database, run_id):
        for option in packet["candidate_tests"]:
            if option["choice"] == "threshold_sensitivity":
                option["feasibility"] = False
                option["reason"] += " Legacy host plan required to commit this template is unavailable."
                option["learning_reasons"].append("Legacy host plan required to commit this template is unavailable.")
        packet["allowed_choices"] = [item["choice"] for item in packet["candidate_tests"]]

    if chooser is None:
        from importlib.metadata import version as package_version
        harness = "omnigent.inner.codex_executor.CodexExecutor"
        sdk_version = package_version("omnigent")
        selector_kind = "omnigent_codex"
    else:
        harness = None
        sdk_version = None
        selector_kind = "injected_test_chooser"
    packet["selection_provenance"] = {
        "selector_kind": selector_kind,
        "requested_model": model if chooser is None else None,
        "harness": harness,
        "omnigent_version": sdk_version,
        "tool_config": ({"web_search": False, "native_tools": False, "skills": "none",
                         "max_tokens": 500, "reasoning_effort": "low"}
                        if chooser is None else None),
    }

    store.append_event(run_id, "adaptive_followup_decision_started", actor="host", mode="live",
                       payload_ref=result.result_id)
    def record_model_event(event_type: str) -> None:
        store.append_event(run_id, event_type, actor="host", mode="live", payload_ref=result.result_id)

    async def decide():
        if chooser is None:
            return await _ask_codex(packet, model, min(TOTAL_TIMEOUT_SECONDS, remaining_seconds),
                                    record_event=record_model_event)
        value = chooser(packet)
        if hasattr(value, "__await__"):
            return await asyncio.wait_for(value, timeout=TOTAL_TIMEOUT_SECONDS)
        return value

    started = time.monotonic()
    deadline = started + min(TOTAL_TIMEOUT_SECONDS, remaining_seconds)
    async def finish():
        choice, reason = await decide()
        option = next(item for item in packet["candidate_tests"] if item["choice"] == choice)
        if choice != "stop" and deadline - time.monotonic() < option["estimated_seconds"]:
            raise ValueError("insufficient budget remains after the model decision")
        record_model_event("adaptive_model_choice_received")
        return await asyncio.to_thread(
            _record_selection, database, run_id, packet, choice, reason,
            dict(api or _default_api()), deadline,
        )
    # wait_for bounds model selection and synchronous host work together. If it
    # expires during a thread-backed registered science call, cancellation cannot
    # kill that thread; each registered worker remains independently bounded.
    try:
        outcome = asyncio.run(asyncio.wait_for(finish(), timeout=max(0.001, deadline - time.monotonic())))
    except BaseException:
        try:
            store.append_event(run_id, "adaptive_followup_failed", actor="host", mode="live",
                               payload_ref=result.result_id)
        except Exception:
            pass
        raise
    store.append_event(run_id, "adaptive_followup_completed", actor="host", mode="live",
                       payload_ref=result.result_id)
    return {"packet": packet, **outcome}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--remaining-seconds", type=float, required=True)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--no-method-audit", action="store_true")
    args = parser.parse_args(argv)
    result = run_adaptive_followup(database=args.database, run_id=args.run_id,
                                  remaining_seconds=args.remaining_seconds,
                                  method_audit_available=not args.no_method_audit,
                                  model=args.model)
    print(json.dumps({"choice": result["selection"]["choice"], "outcome": result["outcome"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
