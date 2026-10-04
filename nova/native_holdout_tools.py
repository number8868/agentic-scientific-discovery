"""Deadline and native-trace adapter for the frozen holdout host gate.

The underlying gate remains the authority for immutable science lineage and
the one-attempt claim. This adapter supplies the parent workflow's original
wall deadline and native model authorization around that unchanged gate.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

_SCOPE_LOCK = threading.RLock()
_TOOL_NAME = "execute_frozen_native_holdout"
_MAX_PARENT_DEADLINE_SECONDS = 720.0


def _verify_trusted_descendant() -> tuple[int, int]:
    """Accept the trusted native child and its SDK descendants in one POSIX process group."""
    if os.name != "posix" or os.environ.get("NOVA_ADAPTIVE_TRUSTED_CHILD") != "1":
        raise PermissionError("native holdout requires a trusted POSIX native child")
    try:
        owner_pid = int(os.environ["NOVA_ADAPTIVE_OWNER_PID"])
        parent_pid = int(os.environ["NOVA_ADAPTIVE_PARENT_PID"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("trusted native owner and parent process bindings are required") from None
    if (owner_pid <= 1 or parent_pid <= 1 or owner_pid == parent_pid or
            os.getpgrp() != owner_pid):
        raise PermissionError("native holdout process is outside the trusted parent's process group")
    try:
        os.kill(owner_pid, 0)
        os.kill(parent_pid, 0)
    except OSError:
        raise PermissionError("trusted native owner or launcher is no longer live") from None
    return owner_pid, parent_pid


def _verify_finalization_proof(finalization, records, frozen, response, experiment_id: str) -> None:
    if (frozen.get("stage") != "frozen_unexecuted" or
            frozen.get("holdout_experiment_id") != experiment_id or
            response.get("role") != "pi"):
        raise ValueError("final PI response does not prove the requested frozen holdout")
    canonical = finalization._canonical(frozen)
    frozen_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    response_result = {"response_sha256": response["response_sha256"],
                       "response_chars": response["response_chars"]}
    response_result_hash = hashlib.sha256(finalization._canonical(response_result).encode("utf-8")).hexdigest()
    freeze_requests = [(index, record) for index, record in enumerate(records)
                       if record.get("event") == "tool_request" and
                       record.get("actor") == "codex-model" and
                       record.get("tool") == "freeze_native_final_protocol" and
                       record.get("role") == "pi" and
                       record.get("args_sha256") == finalization._args_hash(
                           {"explanation": frozen.get("explanation", "")}) and
                       finalization._has_guard(records, record.get("pid", -1), "pi", index)]
    freeze_completions = [item for item in records
                          if item.get("event") == "tool_complete" and
                          item.get("tool") == "freeze_native_final_protocol" and
                          item.get("actor") == "omnigent-tool-dispatch" and
                          item.get("call_id") == response.get("freeze_call_id") and
                          item.get("pid") == response.get("pid") and item.get("role") == "pi" and
                          item.get("structured_result_sha256") == frozen_hash and
                          str(item.get("status", "")).lower() in {"success", "toolcallstatus.success"}]
    if (not any(record.get("call_id") == response.get("freeze_call_id") and
                record.get("pid") == response.get("pid") for _index, record in freeze_requests) or
            not any(any(later.get("event") == "turn_complete" and
                        later.get("actor") == "codex-model" and later.get("role") == "pi" and
                        later.get("pid") == response.get("pid") and
                        later.get("result_sha256") == response_result_hash
                        for later in records[records.index(complete) + 1:])
                    for complete in freeze_completions) or
            not finalization._tool_call(records, tool="freeze_native_final_protocol",
                                        args={"explanation": frozen.get("explanation", "")}, role="pi",
                                        result=frozen, require_turn=True)):
        raise ValueError("frozen protocol lacks a guarded completed native PI freeze turn")


def _trusted_scope(experiment_id: str) -> tuple[Path, str, float, Path]:
    if os.environ.get("NOVA_NATIVE_HOLDOUT_APPROVED") != "1":
        raise PermissionError("native holdout execution is not explicitly approved by the trusted parent")
    _verify_trusted_descendant()
    expected_run = os.environ.get("NOVA_ADAPTIVE_EXPECTED_RUN_ID")
    expected_db = os.environ.get("NOVA_ADAPTIVE_EXPECTED_DATABASE")
    if not expected_run or not expected_db:
        raise ValueError("native holdout requires the trusted expected run/database binding")
    from nova import adaptive_agent_tools as adaptive
    from nova import native_finalization_tools as finalization

    db_path, run_id = adaptive._read_bound_context()
    db_path = Path(db_path).resolve()
    if run_id != expected_run or db_path != Path(expected_db).resolve():
        raise ValueError("native holdout context differs from its trusted binding")
    deadline_text = os.environ.get("NOVA_ADAPTIVE_BUDGET_DEADLINE")
    try:
        deadline = float(deadline_text)
    except (TypeError, ValueError):
        raise ValueError("native holdout requires the original trusted monotonic deadline") from None
    remaining = deadline - time.monotonic()
    if (not math.isfinite(deadline) or not math.isfinite(remaining) or
            not 0 < remaining <= _MAX_PARENT_DEADLINE_SECONDS):
        raise TimeoutError("native adaptive run deadline has expired")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ValueError("invalid holdout experiment id")
    trace_text = os.environ.get("NOVA_ADAPTIVE_TRACE_PATH")
    if not trace_text:
        raise ValueError("native holdout requires the original native model trace")
    trace = Path(trace_text)
    records = finalization._trace_records()
    if not finalization._tool_call(records, tool=_TOOL_NAME,
                                   args={"experiment_id": experiment_id}, role="holdout_runner",
                                   result=None, require_turn=False):
        raise ValueError("holdout requires a guarded native Runner tool request")
    # Require both persisted finalization state and the integrity-checked exact
    # final PI response created by the guarded freeze turn.
    import sqlite3
    with sqlite3.connect(str(db_path), timeout=5) as db:
        row = db.execute("SELECT status,freeze_json,freeze_sha256 FROM native_adaptive_finalization_state WHERE run_id=?",
                         (run_id,)).fetchone()
    if not row or row[0] != "frozen" or not row[1] or not row[2]:
        raise ValueError("native final protocol freeze state is unavailable")
    frozen = finalization._decode_stage_record(row[1], row[2])
    response = __import__("nova.native_adaptive_runtime", fromlist=["read_final_pi_response"]).read_final_pi_response(trace)
    _verify_finalization_proof(finalization, records, frozen, response, experiment_id)
    return db_path, run_id, deadline, trace


def execute_frozen_native_holdout(experiment_id: str) -> dict[str, Any]:
    """Run the approved, registered holdout through A's immutable host gate."""
    from nova import adaptive_agent_tools as adaptive
    from nova import holdout_bridge

    with _SCOPE_LOCK:
        db_path, run_id, deadline, _trace = _trusted_scope(experiment_id)
        original_claim = holdout_bridge._claim
        original_factory = holdout_bridge._controller_factory
        original_persist = holdout_bridge._persist_success

        def assert_binding_and_time() -> float:
            actual_db, actual_run = adaptive._read_bound_context()
            if Path(actual_db).resolve() != db_path or actual_run != run_id:
                raise ValueError("native holdout context changed during execution")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("native adaptive run deadline has expired")
            return remaining

        def bounded_claim(*args, **kwargs):
            assert_binding_and_time()  # immediately before A's atomic claim
            return original_claim(*args, **kwargs)

        class BoundedController:
            def __init__(self, controller):
                self._controller = controller

            def run(self, name, args=(), kwargs=None, *, deadline_seconds):
                left = assert_binding_and_time()
                result = self._controller.run(name, args, kwargs,
                                              deadline_seconds=min(float(deadline_seconds), left))
                assert_binding_and_time()
                return result

        def bounded_factory(registered):
            return BoundedController(original_factory(registered))

        def bounded_persist(*args, **kwargs):
            assert_binding_and_time()  # expiry must not commit a successful Result
            return original_persist(*args, **kwargs)

        holdout_bridge._claim = bounded_claim
        holdout_bridge._controller_factory = bounded_factory
        holdout_bridge._persist_success = bounded_persist
        try:
            assert_binding_and_time()
            from nova.adaptive_agent_tools import record_native_trace
            record_native_trace("native_holdout_gate_started", actor="native-holdout-adapter",
                                tool=_TOOL_NAME, args={"experiment_id": experiment_id})
            result = holdout_bridge.execute_live_registered_holdout(experiment_id)
            assert_binding_and_time()
            result_dict = result.to_dict() if hasattr(result, "to_dict") else result
            if not isinstance(result_dict, dict):
                raise ValueError("holdout gate returned an invalid Result")
            record_native_trace("native_holdout_gate_completed", actor="native-holdout-adapter",
                                tool=_TOOL_NAME, args={"experiment_id": experiment_id}, result=result_dict,
                                status="success")
            return result_dict
        finally:
            holdout_bridge._claim = original_claim
            holdout_bridge._controller_factory = original_factory
            holdout_bridge._persist_success = original_persist


__all__ = ["execute_frozen_native_holdout"]
