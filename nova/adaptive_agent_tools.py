"""Narrow host tools for the native Omnigent adaptive specialist workflow.

The agents never provide run IDs, Result IDs, paths, or science parameters.
Those identities are resolved from the established live context and durable
registry. Planner/Skeptic/PI/Runner calls are recorded in the owning run DB.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sqlite3
import time
from collections.abc import Mapping
from typing import Any

_TABLE = """
CREATE TABLE IF NOT EXISTS native_adaptive_state (
    run_id TEXT PRIMARY KEY,
    parent_result_id TEXT NOT NULL,
    packet_json TEXT NOT NULL,
    review_json TEXT,
    selection_json TEXT,
    selected_id TEXT,
    selected_kind TEXT,
    status TEXT NOT NULL CHECK(status IN ('options_ready','review_ready','committing','committed','running','completed','failed'))
)
"""
ROOT = Path(__file__).resolve().parents[1]
_FIELDS = ("scientific_status", "delta", "resampling_interval",
           "missingness_interval", "groups_summary", "quality_flags")
_REQUIRED_CODEX_OVERRIDES = frozenset({"features.code_mode_host=true", "features.code_mode=false",
                                      'web_search="disabled"'})
_MODEL_PROVIDER_OVERRIDE = re.compile(r'model_provider="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"\Z')


def _valid_codex_config_overrides(value: Any) -> bool:
    """Accept the three required guard flags and at most one provider selector."""
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return False
    if len(value) != len(set(value)) or not _REQUIRED_CODEX_OVERRIDES.issubset(value):
        return False
    extras = set(value) - _REQUIRED_CODEX_OVERRIDES
    return len(extras) <= 1 and all(_MODEL_PROVIDER_OVERRIDE.fullmatch(item) for item in extras)


def record_native_trace(event: str, *, actor: str, tool: str | None = None,
                        call_id: str | None = None, args: Any = None,
                        result: Any = None, model: str | None = None,
                        usage: Any = None, status: str | None = None,
                        pid: int | None = None, role: str | None = None,
                        details: Mapping[str, Any] | None = None,
                        structured_result: Mapping[str, Any] | None = None) -> None:
    """Append a redacted native request/result trace in the run-owned file."""
    path_text = os.environ.get("NOVA_ADAPTIVE_TRACE_PATH")
    if not path_text:
        return
    from datetime import datetime, timezone

    repo_root = ROOT.resolve()
    runs_root = (repo_root / "runs").resolve()
    path = Path(path_text)
    resolved = path.resolve(strict=False)
    if resolved.name != "native-model-audit.jsonl" or not resolved.is_relative_to(runs_root):
        raise ValueError("native trace path is outside the run evidence directory")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("native trace file permissions or type are unsafe")
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                          allow_nan=False, default=str)
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid < 1):
        raise ValueError("native trace pid must be a positive integer")
    if role is not None and (not isinstance(role, str) or len(role) > 120):
        raise ValueError("native trace role is invalid")
    allowed_details = {"agent", "native_tools_disabled", "web_search_disabled", "skills",
                       "config_overrides", "omnigent_version", "harness_module", "host_binary",
                       "error_category", "error_message_sha256", "retryable"}
    safe_details: dict[str, Any] | None = None
    if details is not None:
        if not isinstance(details, Mapping) or set(details) - allowed_details:
            raise ValueError("native trace details contain unsupported fields")
        safe_details = {}
        for key, value in details.items():
            if key in {"native_tools_disabled", "web_search_disabled"}:
                if not isinstance(value, bool):
                    raise ValueError("native trace guard details must be boolean")
            elif key == "retryable":
                if not isinstance(value, bool):
                    raise ValueError("native trace retryable detail must be boolean")
            elif key == "error_message_sha256":
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    raise ValueError("native trace error hash detail is invalid")
            elif key == "error_category":
                if value != "executor_error":
                    raise ValueError("native trace error category is invalid")
            elif key == "config_overrides":
                if (not isinstance(value, list) or len(value) > 8 or
                        any(not isinstance(item, str) or len(item) > 120 for item in value)):
                    raise ValueError("native trace config override details are invalid")
            elif not isinstance(value, str) or len(value) > 1024:
                raise ValueError("native trace detail values must be short strings")
            safe_details[key] = value
    if structured_result is not None and not isinstance(structured_result, Mapping):
        raise ValueError("native trace structured result must be an object")
    record = {"at": datetime.now(timezone.utc).isoformat(), "schema_version": 1,
              "actor": actor, "event": event, "tool": tool, "call_id": call_id,
              "pid": pid or os.getpid(), "role": role or os.environ.get("NOVA_ADAPTIVE_ROLE"),
              "model": model or os.environ.get("NOVA_ADAPTIVE_MODEL"), "status": status,
              "details": safe_details,
              "args_sha256": hashlib.sha256(canonical(args).encode()).hexdigest() if args is not None else None,
              "arg_names": sorted(args) if isinstance(args, Mapping) else None,
              "result_sha256": hashlib.sha256(canonical(result).encode()).hexdigest() if result is not None else None,
              "result_keys": sorted(result) if isinstance(result, Mapping) else None,
              "structured_result_sha256": hashlib.sha256(canonical(structured_result).encode()).hexdigest()
              if structured_result is not None else None,
              "usage": usage}
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
    try:
        try:
            import fcntl
        except ImportError:
            raise RuntimeError("native trace append locking is unavailable on this platform") from None
        fcntl.flock(fd, fcntl.LOCK_EX)
        encoded = (canonical(record) + "\n").encode("utf-8")
        if os.write(fd, encoded) != len(encoded):
            raise OSError("short write while appending native trace")
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except (NameError, OSError):
            pass
        os.close(fd)


def _read_bound_context():
    from nova.live_bridge import _read_context

    db_path, run_id = _read_context()
    expected_run = os.environ.get("NOVA_ADAPTIVE_EXPECTED_RUN_ID")
    expected_database = os.environ.get("NOVA_ADAPTIVE_EXPECTED_DATABASE")
    if (expected_run is None) != (expected_database is None):
        raise ValueError("trusted adaptive context binding is incomplete")
    if expected_run is not None:
        try:
            actual_database = Path(db_path).resolve()
            bound_database = Path(expected_database).resolve()
        except (OSError, TypeError, ValueError):
            raise ValueError("trusted adaptive database binding is invalid") from None
        if not expected_run or not expected_database or run_id != expected_run or actual_database != bound_database:
            raise ValueError("active live context differs from the trusted adaptive run binding")
    return Path(db_path), run_id


def _ctx():
    from nova.contracts import Mode, Template
    from nova.storage import Storage

    db_path, run_id = _read_bound_context()
    store = Storage(db_path).initialize()
    events = store.list_events(run_id)
    if not events or any(event.mode is not Mode.LIVE for event in events):
        raise ValueError("native adaptive workflow requires an authorized live run")
    return db_path, run_id, store


def _state(db_path, run_id: str):
    with sqlite3.connect(str(db_path), timeout=5) as db:
        db.execute(_TABLE)
        row = db.execute(
            "SELECT parent_result_id,packet_json,review_json,selection_json,selected_id,selected_kind,status "
            "FROM native_adaptive_state WHERE run_id=?", (run_id,),
        ).fetchone()
    return row


def _remaining_budget() -> float:
    raw_deadline = os.environ.get("NOVA_ADAPTIVE_BUDGET_DEADLINE")
    if raw_deadline is None:
        raise ValueError("adaptive tools require the trusted parent's absolute deadline")
    try:
        remaining = float(raw_deadline) - time.monotonic()
    except ValueError:
        raise ValueError("configured adaptive deadline is invalid") from None
    if not math.isfinite(remaining) or remaining <= 0:
        raise TimeoutError("native adaptive run deadline has expired")
    return min(remaining, 720.0)


def _parent():
    from scripts.run_adaptive_followup import _load_parent

    db_path, run_id, store = _ctx()
    _same_db, _same_events, result, spec = _load_parent(db_path, run_id)
    if result.execution_status != "completed" or result.error is not None:
        raise ValueError("native adaptive workflow requires the completed host-seeded family Result")
    return db_path, run_id, store, result, spec


def _assert_fresh_followup(db_path, run_id: str, store) -> None:
    if any(event.event_type in {"adaptive_followup_selected", "native_adaptive_choice_committed"}
           for event in store.list_events(run_id)):
        raise ValueError("an adaptive choice already exists for this run")
    with sqlite3.connect(str(db_path), timeout=5) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "native_adaptive_state" in tables and db.execute(
                "SELECT 1 FROM native_adaptive_state WHERE run_id=?", (run_id,)).fetchone():
            raise ValueError("native adaptive workflow already exists for this run")
        if "adaptive_followup_decisions" in tables and db.execute(
                "SELECT 1 FROM adaptive_followup_decisions WHERE run_id=?", (run_id,)).fetchone():
            raise ValueError("a legacy adaptive follow-up already exists for this run")


def _bound_parent():
    """Resolve the packet's original Result after a choice has registered work."""
    from nova.contracts import Mode, Split, Template
    from nova.storage import Storage

    db_path, run_id = _read_bound_context()
    store = Storage(db_path).initialize()
    row = _state(db_path, run_id)
    if not row:
        raise ValueError("native adaptive workflow state is unavailable")
    result = store.get_result(row[0])
    spec = store.get_spec(result.experiment_id) if result is not None else None
    events = store.list_events(run_id)
    if (result is None or result.execution_status != "completed" or result.error is not None or
            spec is None or spec.template is not Template.FAMILY_SCREEN or spec.split is not Split.DISCOVERY or
            result.spec_sha256 != spec.sha256 or result.dataset_sha256 != spec.dataset_sha256 or
            not any(event.actor == "pi" and event.event_type == "selection" and event.payload_ref == spec.experiment_id
                    and event.mode is Mode.LIVE for event in events) or
            not any(event.actor == "runner" and event.event_type == "result" and event.payload_ref == result.result_id
                    and event.mode is Mode.LIVE for event in events)):
        raise ValueError("adaptive parent Result is not a valid run-owned completed discovery family screen")
    return db_path, run_id, store, result, spec


def _load_registered_science_payload(result, spec) -> tuple[dict[str, Any], str]:
    """Read only the unique hash-addressed payload named by this Result."""
    import re

    ids = list(result.artifact_ids)
    payload_ids = [value.partition(":")[2] for value in ids if value.startswith("nova-result-payload:")]
    path_refs = [value.partition(":")[2] for value in ids if value.startswith("nova-artifact-path:")]
    if len(payload_ids) != 1 or len(path_refs) != 1 or not re.fullmatch(r"[0-9a-f]{64}", payload_ids[0]):
        raise ValueError("registered Result does not name one hash-addressed science payload")
    runs_root = (ROOT / "runs").resolve()
    expected = runs_root / f"science-payload-{payload_ids[0]}.json"
    raw_path = ROOT / path_refs[0]
    if raw_path.is_symlink():
        raise ValueError("registered science payload path is a symlink")
    path = raw_path.resolve()
    if path != expected or not path.is_file():
        raise ValueError("registered science payload path is outside its host-owned artifact location")
    body = path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    if digest != payload_ids[0]:
        raise ValueError("registered science payload hash does not match its Result artifact ID")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("registered science payload is invalid JSON") from None
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1 or
            payload.get("artifact_type") != "nova.science_payload.v1" or
            payload.get("experiment_id") != spec.experiment_id or
            payload.get("registered_spec_sha256") != spec.sha256):
        raise ValueError("science payload does not match the registered Result Spec")
    from nova.experiments import executor

    science = payload.get("science_result")
    expected_computation_sha256 = executor._computation_spec_sha256(
        executor._minimal_science_spec(spec)
    )
    if (not isinstance(science, dict) or
            payload.get("computation_spec_sha256") != expected_computation_sha256 or
            science.get("spec_sha256") != expected_computation_sha256 or
            science.get("template") != spec.template.value or
            science.get("dataset_sha256") != spec.dataset_sha256 or
            result.spec_sha256 != spec.sha256 or result.dataset_sha256 != spec.dataset_sha256):
        raise ValueError("science payload computation identity does not match its registered Result Spec")
    expected_result_id = "nova-result-" + hashlib.sha256(executor._canonical_json({
        "experiment_id": spec.experiment_id,
        "spec_sha256": spec.sha256,
        "payload_sha256": digest,
    }).encode("utf-8")).hexdigest()
    if result.result_id != expected_result_id:
        raise ValueError("registered Result identity does not match its immutable science payload")
    return payload, digest


def _canonical_trace_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=str)


def _decode_native_runner_tool_result(value: Any, registered_id: str) -> dict[str, Any] | None:
    """Decode only structured result envelopes observed in the pinned SDK path."""
    candidate: Any = value
    if isinstance(candidate, Mapping) and set(candidate) == {"result"}:
        candidate = candidate["result"]
    if isinstance(candidate, str):
        # Omnigent 0.16's runner dispatch stringifies Python dict returns with
        # str(result), so this path must parse a bounded literal, never execute it.
        if len(candidate.encode("utf-8")) > 256_000:
            return None
        try:
            import ast

            parsed = ast.parse(candidate, mode="eval")
            stack = [(parsed, 0)]
            node_count = 0
            while stack:
                node, depth = stack.pop()
                node_count += 1
                if node_count > 20_000 or depth > 80:
                    return None
                stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
            candidate = ast.literal_eval(parsed)
        except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
            return None
    if isinstance(candidate, Mapping) and set(candidate) <= {"content", "isError"} and "content" in candidate:
        if candidate.get("isError", False) is not False:
            return None
        content = candidate.get("content")
        if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], Mapping):
            return None
        block = content[0]
        if set(block) != {"type", "text"} or block.get("type") != "text" or not isinstance(block.get("text"), str):
            return None
        try:
            candidate = json.loads(block["text"])
        except json.JSONDecodeError:
            return None
    if not isinstance(candidate, Mapping):
        return None
    decoded = dict(candidate)
    body = decoded.get("result")
    if decoded.get("registered_id") != registered_id or not isinstance(body, Mapping):
        return None
    if body.get("experiment_id") == registered_id:
        grid = decoded.get("discovery_threshold_sensitivity")
        if (set(decoded) != {"registered_id", "result", "discovery_threshold_sensitivity"} or
                body.get("execution_status") != "completed" or body.get("error") or
                not isinstance(body.get("result_id"), str) or not isinstance(grid, Mapping) or
                grid.get("scope") != "discovery_only_not_holdout_validation_or_replication"):
            return None
    else:
        if (set(decoded) != {"registered_id", "result", "audit_rows_count", "full_result_sha256"} or
                body.get("execution_status") != "success" or body.get("template") != "method_sensitivity" or
                body.get("split") != "discovery" or isinstance(decoded.get("audit_rows_count"), bool) or
                not isinstance(decoded.get("audit_rows_count"), int) or
                not isinstance(decoded.get("full_result_sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", decoded["full_result_sha256"])):
            return None
    return decoded


def _has_runner_dispatch_trace(*, registered_id: str, response_sha256: str) -> bool:
    """Require a successful native tool completion and subsequent model turn."""
    trace_text = os.environ.get("NOVA_ADAPTIVE_TRACE_PATH")
    if not trace_text:
        return False
    path = Path(trace_text)
    runs_root = (ROOT / "runs").resolve()
    resolved = path.resolve(strict=False)
    if resolved.name != "native-model-audit.jsonl" or not resolved.is_relative_to(runs_root):
        return False
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            return False
        records = [record for line in path.read_text(encoding="utf-8").splitlines() if line
                   for record in [json.loads(line)] if isinstance(record, dict)]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    request_sha = hashlib.sha256(_canonical_trace_json({"registered_id": registered_id}).encode()).hexdigest()

    def has_guard(pid: int, role: Any, before_index: int) -> bool:
        for guard in records[:before_index]:
            if (guard.get("event") != "executor_guard_installed" or guard.get("pid") != pid or
                    guard.get("role") != role or not isinstance(guard.get("details"), Mapping)):
                continue
            details = guard["details"]
            binary = details.get("host_binary")
            overrides = details.get("config_overrides")
            if (details.get("native_tools_disabled") is not True or
                    details.get("web_search_disabled") is not True or details.get("skills") != "none" or
                    not _valid_codex_config_overrides(overrides) or
                    not isinstance(binary, str)):
                continue
            try:
                host_path = Path(binary)
                if (host_path.name == "codex-code-mode-host" and not host_path.is_symlink() and
                        host_path.is_file() and os.access(host_path, os.X_OK)):
                    return True
            except (OSError, ValueError):
                continue
        return False

    # Every process that issued a model tool request must have emitted its
    # own verified guard record before it is accepted as execution evidence.
    requester_pids = {item.get("pid") for index, item in enumerate(records)
                      if item.get("event") == "tool_request" and item.get("actor") == "codex-model" and
                      isinstance(item.get("pid"), int) and not isinstance(item.get("pid"), bool) and
                      has_guard(item["pid"], item.get("role"), index)}
    all_requester_pids = {item.get("pid") for item in records
                          if item.get("event") == "tool_request" and item.get("actor") == "codex-model"}
    if not requester_pids or requester_pids != all_requester_pids:
        return False

    for complete_index, complete in enumerate(records):
        process_id = complete.get("pid")
        if (complete.get("event") != "tool_complete" or
                complete.get("actor") != "omnigent-tool-dispatch" or
                complete.get("tool") != "execute_selected_adaptive" or
                str(complete.get("status", "")).lower() not in {"success", "toolcallstatus.success"} or
                not isinstance(process_id, int) or isinstance(process_id, bool) or
                not isinstance(complete.get("result_sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", complete["result_sha256"]) or
                (complete.get("structured_result_sha256") != response_sha256 and not any(
                    witness.get("event") == "tool_result_decoded_retrospectively" and
                    witness.get("actor") == "host-transport-verifier" and
                    witness.get("tool") == "execute_selected_adaptive" and
                    witness.get("call_id") == complete.get("call_id") and
                    witness.get("pid") == process_id and witness.get("role") == complete.get("role") and
                    witness.get("result_sha256") == complete.get("result_sha256") and
                    witness.get("structured_result_sha256") == response_sha256
                    for witness in records[complete_index + 1:]))):
            continue
        call_id = complete.get("call_id")
        if not call_id or not any(
                request.get("event") == "tool_request" and request.get("actor") == "codex-model" and
                request.get("tool") == "execute_selected_adaptive" and request.get("call_id") == call_id and
                request.get("args_sha256") == request_sha and request.get("pid") == process_id and
                request.get("role") == complete.get("role") and
                has_guard(process_id, request.get("role"), records.index(request))
                for request in records[:complete_index]):
            continue
        if any(record.get("event") == "turn_complete" and record.get("actor") == "codex-model" and
               record.get("pid") == process_id and record.get("role") == complete.get("role")
               for record in records[complete_index + 1:]):
            return True
    return False


def get_adaptive_options() -> dict[str, Any]:
    """Planner function: persist and return host-built feasible options."""
    from nova.adaptive_policy import propose_followups
    from scripts.run_adaptive_followup import _threshold_commit_available

    db_path, run_id, store, result, _spec = _parent()
    _assert_fresh_followup(db_path, run_id, store)
    if _state(db_path, run_id):
        raise ValueError("native adaptive options are already registered for this run")
    budget = _remaining_budget()
    packet = propose_followups(result, remaining_seconds=budget, method_audit_available=True)
    if not _threshold_commit_available(db_path, run_id):
        option = next(item for item in packet["candidate_tests"] if item["choice"] == "threshold_sensitivity")
        option["feasibility"] = False
        option["reason"] += " The registered threshold commit plan is unavailable."
        option["learning_reasons"].append("The registered threshold commit plan is unavailable.")
    # Method availability is established by the host's registered-method gate.
    try:
        from nova.registered_method_audit import _protocol
        _protocol()
    except Exception:
        option = next(item for item in packet["candidate_tests"] if item["choice"] == "method_sensitivity")
        option["feasibility"] = False
        option["reason"] += " The frozen method-audit protocol is unavailable."
        option["learning_reasons"].append("The frozen method-audit protocol is unavailable.")
    packet["allowed_choices"] = [item["choice"] for item in packet["candidate_tests"]]
    packet["selection"] = None
    with sqlite3.connect(str(db_path), timeout=5) as db:
        db.execute(_TABLE)
        db.execute("INSERT INTO native_adaptive_state(run_id,parent_result_id,packet_json,status) VALUES(?,?,?,'options_ready')",
                   (run_id, result.result_id, json.dumps(packet, sort_keys=True, separators=(",", ":"), allow_nan=False)))
    store.append_event(run_id, "native_adaptive_options_registered", actor="planner", mode="live",
                       payload_ref=result.result_id)
    record_native_trace("function_complete", actor="planner", tool="get_adaptive_options", result=packet,
                        status="success")
    return packet


def read_adaptive_evidence() -> dict[str, Any]:
    """Skeptic read-only tool; IDs and all values are loaded by the host."""
    db_path, run_id, _store, result, spec = _bound_parent()
    row = _state(db_path, run_id)
    if not row or row[0] != result.result_id:
        raise ValueError("Planner options are not registered for this parent Result")
    response = {"result": result.to_dict(), "spec": spec.to_dict(), "adaptive_options": json.loads(row[1])}
    record_native_trace("function_complete", actor="skeptic", tool="read_adaptive_evidence",
                        result=response, status="success")
    return response


def record_adaptive_review(concern: str, evidence_fields: list[str]) -> dict[str, Any]:
    """Persist a concise Skeptic review tied to actual parent fields."""
    from nova.contracts import Mode

    if not isinstance(concern, str) or not concern.strip() or len(concern.strip()) > 500:
        raise ValueError("review concern must be 1-500 characters")
    if (not isinstance(evidence_fields, list) or not evidence_fields or len(evidence_fields) > len(_FIELDS)
            or any(field not in _FIELDS for field in evidence_fields) or len(set(evidence_fields)) != len(evidence_fields)):
        raise ValueError("review evidence_fields must name unique registered Result fields")
    db_path, run_id, store, result, _spec = _parent()
    row = _state(db_path, run_id)
    if not row or row[0] != result.result_id or row[6] != "options_ready":
        raise ValueError("adaptive options are missing or review stage is closed")
    result_data = result.to_dict()
    evidence = {key: result_data[key] for key in evidence_fields}
    review = {"parent_result_id": result.result_id, "concern": concern.strip(),
              "evidence": evidence, "evidence_refs": [f"result:{result.result_id}#{key}" for key in evidence_fields]}
    with sqlite3.connect(str(db_path), timeout=5) as db:
        cursor = db.execute("UPDATE native_adaptive_state SET review_json=?,status='review_ready' WHERE run_id=? AND status='options_ready'",
                            (json.dumps(review, sort_keys=True, separators=(",", ":"), allow_nan=False), run_id))
        if cursor.rowcount != 1:
            raise ValueError("adaptive review stage changed before commit")
    store.append_event(run_id, "native_adaptive_review_submitted", actor="skeptic", mode=Mode.LIVE,
                       payload_ref=result.result_id)
    record_native_trace("function_complete", actor="skeptic", tool="record_adaptive_review",
                        args={"concern": concern.strip(), "evidence_fields": evidence_fields},
                        result=review, status="success")
    return review


def commit_adaptive_choice(choice: str, reason: str) -> dict[str, Any]:
    """PI function: commit one feasible host option and return its registry ID."""
    from nova.adaptive_policy import validate_choice
    from nova.contracts import Mode

    db_path, run_id, store, result, _spec = _parent()
    row = _state(db_path, run_id)
    if not row or row[0] != result.result_id or row[6] != "review_ready" or not row[2]:
        raise ValueError("PI choice requires the completed Planner and Skeptic stages")
    packet, review = json.loads(row[1]), json.loads(row[2])
    selection = validate_choice(packet, choice, reason)
    option = next(item for item in packet["candidate_tests"] if item["choice"] == choice)
    if option["estimated_seconds"] > _remaining_budget():
        raise ValueError("insufficient run budget remains for the committed adaptive option")
    # Claim before invoking legacy registration APIs: partial failures remain
    # durable and cannot be replayed into duplicate experiment registrations.
    with sqlite3.connect(str(db_path), timeout=5) as db:
        cursor = db.execute("UPDATE native_adaptive_state SET status='committing' WHERE run_id=? AND status='review_ready'", (run_id,))
        if cursor.rowcount != 1:
            raise ValueError("adaptive choice stage changed before commit")
    try:
        selected_id = None
        kind = None
        if choice == "threshold_sensitivity":
            from nova.decision_tools import commit_next_spec, submit_live_review
            submit_live_review(result.result_id, review["concern"], "threshold_sensitivity")
            selected_id = commit_next_spec(result.result_id, "threshold_sensitivity")
            kind = "experiment_id"
        elif choice == "method_sensitivity":
            from nova.registered_method_audit import register_method_audit
            request = register_method_audit(result.result_id)
            selected_id = request["audit_id"]
            kind = "audit_id"
        selection.update({"parent_result_id": result.result_id, "selected_id": selected_id, "selected_kind": kind})
        with sqlite3.connect(str(db_path), timeout=5) as db:
            db.execute("UPDATE native_adaptive_state SET selection_json=?,selected_id=?,selected_kind=?,status='committed' WHERE run_id=? AND status='committing'",
                       (json.dumps(selection, sort_keys=True, separators=(",", ":"), allow_nan=False), selected_id, kind, run_id))
        store.append_event(run_id, "native_adaptive_choice_committed", actor="pi", mode=Mode.LIVE,
                           payload_ref=selected_id or result.result_id)
        response = {"selection": selection, "outcome": "stopped" if choice == "stop" else "registered",
                    "registered_id": selected_id, "registered_id_kind": kind}
        record_native_trace("function_complete", actor="pi", tool="commit_adaptive_choice",
                            args={"choice": choice, "reason": reason}, result=response, status="success")
        return response
    except Exception:
        with sqlite3.connect(str(db_path), timeout=5) as db:
            db.execute("UPDATE native_adaptive_state SET status='failed' WHERE run_id=? AND status='committing'", (run_id,))
        store.append_event(run_id, "native_adaptive_choice_failed", actor="host", mode=Mode.LIVE,
                           payload_ref=result.result_id)
        raise


def execute_selected_adaptive(registered_id: str) -> dict[str, Any]:
    """Runner function: execute only the exact ID returned by PI commit."""
    from nova.contracts import Mode, Template

    if not isinstance(registered_id, str) or not registered_id or len(registered_id) > 120 or "/" in registered_id or "\\" in registered_id:
        raise ValueError("invalid registered adaptive ID")
    _remaining_budget()
    db_path, run_id, store, result, _spec = _bound_parent()
    with sqlite3.connect(str(db_path), timeout=5) as db:
        db.execute(_TABLE)
        row = db.execute("SELECT selected_id,selected_kind,status FROM native_adaptive_state WHERE run_id=?", (run_id,)).fetchone()
        if not row or row[0] != registered_id or row[2] != "committed" or row[1] not in {"experiment_id", "audit_id"}:
            raise ValueError("Runner may execute only the PI-committed registered adaptive ID")
        cursor = db.execute("UPDATE native_adaptive_state SET status='running' WHERE run_id=? AND selected_id=? AND status='committed'",
                            (run_id, registered_id))
        if cursor.rowcount != 1:
            raise ValueError("Runner adaptive ID was already claimed")
    store.append_event(run_id, "native_adaptive_runner_started", actor="runner", mode=Mode.LIVE,
                       payload_ref=registered_id)
    try:
        if row[1] == "experiment_id":
            from nova.live_bridge import execute_live_registered_experiment
            value = execute_live_registered_experiment(registered_id)
            payload = value.to_dict()
            if payload.get("experiment_id") != registered_id or payload.get("execution_status") != "completed" or payload.get("error"):
                raise ValueError("registered adaptive Result did not complete successfully")
            response = {"registered_id": registered_id, "result": payload}
            registered_spec = store.get_spec(registered_id)
            if registered_spec is None:
                raise ValueError("Runner adaptive Spec disappeared before Result return")
            science_payload, payload_sha256 = _load_registered_science_payload(value, registered_spec)
            science = science_payload.get("science_result")
            if registered_spec.template is Template.THRESHOLD_SENSITIVITY:
                from nova.experiments.threshold_sensitivity import PRIMARY_POINT_INDEX, THRESHOLD_GRID_EV_ATOM

                points = science.get("points") if isinstance(science, Mapping) else None
                if (not isinstance(science, Mapping) or science.get("execution_status") != "success" or
                        science.get("template") != "threshold_sensitivity" or science.get("split") != "discovery" or
                        science.get("primary_point_index") != PRIMARY_POINT_INDEX or
                        science.get("primary_threshold_ev_atom") != THRESHOLD_GRID_EV_ATOM[PRIMARY_POINT_INDEX] or
                        not isinstance(points, list) or len(points) != len(THRESHOLD_GRID_EV_ATOM) or
                        tuple(point.get("threshold_ev_atom") for point in points if isinstance(point, Mapping)) != THRESHOLD_GRID_EV_ATOM):
                    raise ValueError("hash-verified threshold payload does not contain the complete frozen discovery grid")
                primary = points[PRIMARY_POINT_INDEX]
                if primary.get("delta") != value.delta or tuple(primary.get("resampling_interval", ())) != tuple(value.resampling_interval or ()):
                    raise ValueError("threshold payload primary point differs from the canonical Result")
                response["discovery_threshold_sensitivity"] = {
                    "science_payload_sha256": payload_sha256,
                    "points": points,
                    "primary_point_index": PRIMARY_POINT_INDEX,
                    "primary_threshold_ev_atom": THRESHOLD_GRID_EV_ATOM[PRIMARY_POINT_INDEX],
                    "quality_flags": science.get("quality_flags"),
                    "scientific_status": science.get("scientific_status"),
                    "interpretation_scope": science.get("interpretation_scope"),
                    "scope": "discovery_only_not_holdout_validation_or_replication",
                }
            result_ref = payload["result_id"]
        else:
            from nova.registered_method_audit import execute_registered_method_audit
            value = execute_registered_method_audit(registered_id)
            full = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
            body = value.get("result") if isinstance(value, Mapping) else None
            if not isinstance(body, Mapping) or body.get("execution_status") != "success" or body.get("template") != "method_sensitivity" or body.get("split") != "discovery":
                raise ValueError("registered method Result did not complete successfully")
            response = {"registered_id": registered_id, "result": dict(body),
                        "audit_rows_count": len(value.get("audit_rows", [])),
                        "full_result_sha256": hashlib.sha256(full.encode()).hexdigest()}
            result_ref = registered_id
        store.append_event(run_id, "native_adaptive_runner_result_returned", actor="runner", mode=Mode.LIVE,
                           payload_ref=result_ref)
        record_native_trace("function_complete", actor="runner", tool="execute_selected_adaptive",
                            args={"registered_id": registered_id}, result=response, status="success")
        encoded_response = _canonical_trace_json(response)
        response_sha256 = hashlib.sha256(encoded_response.encode("utf-8")).hexdigest()
        with sqlite3.connect(str(db_path), timeout=5) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS native_adaptive_runner_returns (
                         run_id TEXT PRIMARY KEY, registered_id TEXT NOT NULL,
                         result_ref TEXT NOT NULL, response_json TEXT NOT NULL,
                         response_sha256 TEXT NOT NULL)""")
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE native_adaptive_state SET status='completed' WHERE run_id=? AND status='running'",
                (run_id,))
            if cursor.rowcount != 1:
                raise ValueError("Runner completion state changed before return was recorded")
            db.execute("INSERT INTO native_adaptive_runner_returns VALUES(?,?,?,?,?)",
                       (run_id, registered_id, result_ref, encoded_response, response_sha256))
        return response
    except Exception:
        with sqlite3.connect(str(db_path), timeout=5) as db:
            db.execute("UPDATE native_adaptive_state SET status='failed' WHERE run_id=? AND status='running'", (run_id,))
        store.append_event(run_id, "native_adaptive_runner_failed", actor="host", mode=Mode.LIVE,
                           payload_ref=registered_id)
        raise


def record_supervisor_response(response_text: str) -> dict[str, str]:
    """Persist the actual native CLI supervisor response after tool dispatch."""
    from nova.contracts import Mode

    if not isinstance(response_text, str) or not response_text.strip() or len(response_text) > 20_000:
        raise ValueError("native supervisor response must contain 1-20000 characters")
    db_path, run_id, store, result, _spec = _bound_parent()
    row = _state(db_path, run_id)
    if not row or row[0] != result.result_id or not row[3]:
        raise ValueError("native supervisor has no committed PI choice")
    selection = json.loads(row[3])
    if selection.get("choice") == "stop":
        if row[6] != "committed" or row[4] is not None:
            raise ValueError("stop response does not match committed stop state")
    else:
        returned = [event for event in store.list_events(run_id)
                    if event.event_type == "native_adaptive_runner_result_returned" and
                    event.actor == "runner" and event.mode is Mode.LIVE]
        if row[6] != "completed" or len(returned) != 1:
            raise ValueError("supervisor response requires a completed Runner Result return")
        with sqlite3.connect(str(db_path), timeout=5) as db:
            runner_return = db.execute(
                "SELECT registered_id,result_ref,response_json,response_sha256 "
                "FROM native_adaptive_runner_returns WHERE run_id=?", (run_id,)
            ).fetchone()
        if not runner_return or runner_return[0] != row[4] or runner_return[1] != returned[0].payload_ref:
            raise ValueError("Runner feedback does not match the PI-committed adaptive ID")
        try:
            returned_json = json.loads(runner_return[2])
        except (TypeError, json.JSONDecodeError):
            raise ValueError("stored Runner feedback is invalid") from None
        if hashlib.sha256(_canonical_trace_json(returned_json).encode("utf-8")).hexdigest() != runner_return[3]:
            raise ValueError("stored Runner feedback hash is invalid")
        if not _has_runner_dispatch_trace(registered_id=row[4], response_sha256=runner_return[3]):
            raise ValueError("supervisor response requires successful Runner tool and model-turn feedback")
        if row[5] == "experiment_id":
            runner_result = store.get_result(returned[0].payload_ref)
            if runner_result is None or runner_result.experiment_id != row[4] or \
                    runner_result.execution_status != "completed" or runner_result.error is not None:
                raise ValueError("Runner feedback does not contain the committed experiment's completed Result")
        elif row[5] != "audit_id" or returned[0].payload_ref != row[4]:
            raise ValueError("Runner feedback does not match the committed method audit")
    with sqlite3.connect(str(db_path), timeout=5) as db:
        existing = db.execute(
            "SELECT 1 FROM native_adaptive_supervisor_results WHERE run_id=?", (run_id,)
        ).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                   ("native_adaptive_supervisor_results",)).fetchone() else None
    if existing or any(event.event_type == "native_adaptive_supervisor_returned" and event.actor == "host"
                       for event in store.list_events(run_id)):
        raise ValueError("native supervisor response was already recorded for this run")
    response_text = response_text.strip()
    digest = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
    with sqlite3.connect(str(db_path), timeout=5) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS native_adaptive_supervisor_results (
                     run_id TEXT PRIMARY KEY, parent_result_id TEXT NOT NULL,
                     response_text TEXT NOT NULL, response_sha256 TEXT NOT NULL)""")
        db.execute("INSERT INTO native_adaptive_supervisor_results VALUES(?,?,?,?)",
                   (run_id, result.result_id, response_text, digest))
    store.append_event(run_id, "native_adaptive_supervisor_returned", actor="host", mode=Mode.LIVE,
                       payload_ref=result.result_id)
    record_native_trace("supervisor_response_persisted", actor="host", tool="omnigent-root",
                        result={"parent_result_id": result.result_id, "response_sha256": digest}, status="success")
    return {"parent_result_id": result.result_id, "response_sha256": digest}
