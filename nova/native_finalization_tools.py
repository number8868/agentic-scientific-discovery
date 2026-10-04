"""Bounded host tools for the final Skeptic review and PI protocol freeze.

This module deliberately has no holdout execution callable. It may only freeze
the one completed native threshold-sensitivity follow-up in the bound live run.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from collections.abc import Mapping
from typing import Any

from nova import adaptive_agent_tools as adaptive

_TABLE = """
CREATE TABLE IF NOT EXISTS native_adaptive_finalization_state (
    run_id TEXT PRIMARY KEY,
    parent_result_id TEXT NOT NULL,
    followup_result_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('review_claimed','reviewed','freeze_claimed','frozen','review_failed','freeze_failed')),
    review_json TEXT,
    review_sha256 TEXT,
    freeze_json TEXT,
    freeze_sha256 TEXT
)
"""
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=str)


def _decode_stage_record(raw_json: str, expected_sha256: str) -> dict[str, Any]:
    """Decode a persisted finalization packet only when its canonical hash matches."""
    if not isinstance(raw_json, str) or not isinstance(expected_sha256, str) or not _HEX.fullmatch(expected_sha256):
        raise ValueError("finalization stage packet or hash is invalid")
    try:
        value = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        raise ValueError("finalization stage packet is invalid JSON") from None
    if not isinstance(value, dict) or hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest() != expected_sha256:
        raise ValueError("finalization stage packet hash is invalid")
    return value


def _has_result_for_experiment(store, experiment_id: str) -> bool:
    return any(item.experiment_id == experiment_id for item in store.list_results())


def _context(*, write: bool = False):
    expected_run = os.environ.get("NOVA_ADAPTIVE_EXPECTED_RUN_ID")
    expected_db = os.environ.get("NOVA_ADAPTIVE_EXPECTED_DATABASE")
    if not expected_run or not expected_db:
        raise ValueError("native finalization requires the trusted expected run/database binding")
    db_path, run_id = adaptive._read_bound_context()
    if run_id != expected_run or Path(db_path).resolve() != Path(expected_db).resolve():
        raise ValueError("native finalization context differs from its trusted binding")
    if write:
        adaptive._remaining_budget()
    from nova.storage import Storage

    store = Storage(db_path).initialize()
    return Path(db_path), run_id, store


def _state_row(db_path: Path, run_id: str):
    with sqlite3.connect(str(db_path), timeout=5) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_adaptive_state'").fetchone()
        if not table:
            return None
        return db.execute("""SELECT parent_result_id,selection_json,selected_id,selected_kind,status
                             FROM native_adaptive_state WHERE run_id=?""", (run_id,)).fetchone()


def _events_ok(store, run_id: str, *, event_type: str, actor: str, payload_ref: str) -> bool:
    from nova.contracts import Mode

    return any(event.event_type == event_type and event.actor == actor and
               event.payload_ref == payload_ref and event.mode is Mode.LIVE
               for event in store.list_events(run_id))


def _unsupported(reason_code: str, reason: str, *, stage: str = "unsupported") -> dict[str, Any]:
    return {"supported": False, "stage": stage, "reason_code": reason_code, "reason": reason}


def _trace_records() -> list[dict[str, Any]]:
    trace_text = os.environ.get("NOVA_ADAPTIVE_TRACE_PATH")
    if not trace_text:
        raise ValueError("native finalization requires the original native model audit trace")
    trace = Path(trace_text)
    root = (adaptive.ROOT / "runs").resolve()
    if trace.resolve(strict=False).name != "native-model-audit.jsonl" or not trace.resolve(strict=False).is_relative_to(root):
        raise ValueError("native finalization trace is outside the owning run evidence tree")
    info = trace.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("native finalization trace is not a private regular file")
    try:
        records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("native finalization trace is invalid") from None
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("native finalization trace contains an invalid record")
    return records


def _has_guard(records: list[dict[str, Any]], pid: int, role: str, before: int) -> bool:
    from nova.adaptive_agent_tools import _valid_codex_config_overrides

    for record in records[:before]:
        if (record.get("event") != "executor_guard_installed" or record.get("pid") != pid or
                record.get("role") != role or not isinstance(record.get("details"), Mapping)):
            continue
        details = record["details"]
        binary = details.get("host_binary")
        try:
            path = Path(binary) if isinstance(binary, str) else None
            valid_binary = bool(path and path.name == "codex-code-mode-host" and not path.is_symlink()
                                and path.is_file() and os.access(path, os.X_OK))
        except (OSError, ValueError):
            valid_binary = False
        if (details.get("native_tools_disabled") is True and details.get("web_search_disabled") is True and
                details.get("skills") == "none" and
                _valid_codex_config_overrides(details.get("config_overrides")) and valid_binary):
            return True
    return False


def _args_hash(args: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(args).encode("utf-8")).hexdigest()


def _tool_call(records: list[dict[str, Any]], *, tool: str, args: Mapping[str, Any], role: str,
               result: Mapping[str, Any] | None = None, require_turn: bool = True) -> bool:
    expected_args = _args_hash(args)
    for index, request in enumerate(records):
        pid, call_id = request.get("pid"), request.get("call_id")
        if (request.get("event") != "tool_request" or request.get("actor") != "codex-model" or
                request.get("tool") != tool or request.get("role") != role or
                not isinstance(pid, int) or isinstance(pid, bool) or not call_id or
                request.get("args_sha256") != expected_args or
                not _has_guard(records, pid, role, index)):
            continue
        if result is None:
            return True
        expected_result_hash = hashlib.sha256(_canonical(result).encode("utf-8")).hexdigest()
        for complete_index in range(index + 1, len(records)):
            complete = records[complete_index]
            if (complete.get("event") != "tool_complete" or complete.get("actor") != "omnigent-tool-dispatch" or
                    complete.get("tool") != tool or complete.get("call_id") != call_id or
                    complete.get("pid") != pid or complete.get("role") != role or
                    str(complete.get("status", "")).lower() not in {"success", "toolcallstatus.success"}):
                continue
            matched_hash = complete.get("structured_result_sha256") == expected_result_hash
            if not matched_hash:
                matched_hash = any(
                    witness.get("event") == "tool_result_decoded_retrospectively" and
                    witness.get("actor") == "host-transport-verifier" and witness.get("tool") == tool and
                    witness.get("call_id") == call_id and witness.get("pid") == pid and
                    witness.get("role") == role and witness.get("result_sha256") == complete.get("result_sha256") and
                    witness.get("structured_result_sha256") == expected_result_hash
                    for witness in records[complete_index + 1:])
            if not matched_hash:
                continue
            if not require_turn or any(
                    later.get("event") == "turn_complete" and later.get("actor") == "codex-model" and
                    later.get("pid") == pid and later.get("role") == role
                    for later in records[complete_index + 1:]):
                return True
    return False


def _resolve_followup(*, write: bool = False) -> dict[str, Any]:
    from nova.contracts import Mode, Split, Template

    db_path, run_id, store = _context(write=write)
    state = _state_row(db_path, run_id)
    if not state:
        return {"supported": False, "stage": "unavailable", "reason_code": "adaptive_state_missing",
                "reason": "No native adaptive choice exists in this run."}
    parent_id, selection_json, selected_id, selected_kind, status = state
    try:
        selection = json.loads(selection_json) if selection_json else {}
    except (TypeError, json.JSONDecodeError):
        raise ValueError("native adaptive selection packet is invalid") from None
    choice = selection.get("choice")
    if choice == "stop":
        return {"supported": False, "stage": status, "reason_code": "unsupported_stop",
                "reason": "A stopped adaptive run has no threshold follow-up to finalize."}
    if choice == "method_sensitivity" or selected_kind == "audit_id":
        return {"supported": False, "stage": status, "reason_code": "unsupported_method_audit",
                "reason": "Method-audit results cannot enter the frozen family-threshold protocol."}
    if choice != "threshold_sensitivity" or selected_kind != "experiment_id" or not selected_id:
        return {"supported": False, "stage": status, "reason_code": "unsupported_selection",
                "reason": "Finalization supports only the registered threshold-sensitivity discovery follow-up."}
    if status != "completed":
        return {"supported": False, "stage": status, "reason_code": "runner_not_completed",
                "reason": "The threshold Runner must complete and return its Result before finalization."}

    db_path, run_id, store, parent, parent_spec = adaptive._bound_parent()
    if parent.result_id != parent_id or parent_spec.template is not Template.FAMILY_SCREEN:
        raise ValueError("native finalization parent Result changed")
    primary_review = store.get_review(parent_id)
    if (primary_review is None or primary_review.result_id != parent_id or
            primary_review.experiment_id != parent_spec.experiment_id or
            primary_review.recommended_template is not Template.THRESHOLD_SENSITIVITY or
            not _events_ok(store, run_id, event_type="review", actor="skeptic", payload_ref=parent_id)):
        return {"supported": False, "stage": status, "reason_code": "primary_review_missing",
                "reason": "Finalization requires the canonical Skeptic review that recommended threshold sensitivity."}
    followup_spec = store.get_spec(selected_id)
    if (followup_spec is None or followup_spec.template is not Template.THRESHOLD_SENSITIVITY or
            followup_spec.split is not Split.DISCOVERY or followup_spec.parent_result_id != parent_id or
            followup_spec.review_id != parent_id or followup_spec.frozen_protocol_id is not None or
            not _events_ok(store, run_id, event_type="second_selection", actor="pi", payload_ref=selected_id)):
        raise ValueError("selected follow-up is not the immutable registered discovery threshold Spec")
    results = [item for item in store.list_results() if item.experiment_id == selected_id]
    if len(results) != 1:
        return {"supported": False, "stage": status, "reason_code": "followup_result_missing",
                "reason": "The registered threshold follow-up has no unique completed Result."}
    followup = results[0]
    if (followup.execution_status != "completed" or followup.error is not None or
            followup.spec_sha256 != followup_spec.sha256 or followup.dataset_sha256 != followup_spec.dataset_sha256 or
            not _events_ok(store, run_id, event_type="result", actor="runner", payload_ref=followup.result_id)):
        return {"supported": False, "stage": status, "reason_code": "followup_result_invalid",
                "reason": "The registered threshold Result is not a successful run-owned Runner result."}
    payload, payload_sha = adaptive._load_registered_science_payload(followup, followup_spec)
    science = payload.get("science_result")
    from nova.experiments.threshold_sensitivity import PRIMARY_POINT_INDEX, THRESHOLD_GRID_EV_ATOM
    points = science.get("points") if isinstance(science, Mapping) else None
    if (not isinstance(science, Mapping) or science.get("execution_status") != "success" or
            science.get("template") != Template.THRESHOLD_SENSITIVITY.value or
            science.get("split") != Split.DISCOVERY.value or
            science.get("primary_point_index") != PRIMARY_POINT_INDEX or
            science.get("primary_threshold_ev_atom") != THRESHOLD_GRID_EV_ATOM[PRIMARY_POINT_INDEX] or
            not isinstance(points, list) or len(points) != len(THRESHOLD_GRID_EV_ATOM) or
            tuple(point.get("threshold_ev_atom") for point in points if isinstance(point, Mapping)) != THRESHOLD_GRID_EV_ATOM):
        raise ValueError("selected threshold payload does not contain the complete frozen discovery grid")
    if (not _events_ok(store, run_id, event_type="native_adaptive_runner_started", actor="runner", payload_ref=selected_id) or
            not _events_ok(store, run_id, event_type="native_adaptive_runner_result_returned", actor="runner", payload_ref=followup.result_id)):
        return {"supported": False, "stage": status, "reason_code": "runner_feedback_missing",
                "reason": "A successful Runner Result handoff event is required before finalization."}
    with sqlite3.connect(str(db_path), timeout=5) as db:
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_adaptive_runner_returns'").fetchone()
        runner_return = db.execute("""SELECT registered_id,result_ref,response_json,response_sha256
                                      FROM native_adaptive_runner_returns WHERE run_id=?""", (run_id,)).fetchone() if table else None
    if not runner_return or runner_return[0] != selected_id or runner_return[1] != followup.result_id:
        return {"supported": False, "stage": status, "reason_code": "runner_feedback_missing",
                "reason": "Persisted native Runner feedback is missing or does not match the selected Result."}
    try:
        response_data = json.loads(runner_return[2])
    except (TypeError, json.JSONDecodeError):
        raise ValueError("persisted native Runner feedback is invalid") from None
    if (hashlib.sha256(_canonical(response_data).encode("utf-8")).hexdigest() != runner_return[3] or
            response_data.get("registered_id") != selected_id or
            response_data.get("result", {}).get("result_id") != followup.result_id or
            response_data.get("discovery_threshold_sensitivity", {}).get("science_payload_sha256") != payload_sha):
        raise ValueError("persisted native Runner feedback hash or Result linkage is invalid")
    if not adaptive._has_runner_dispatch_trace(registered_id=selected_id, response_sha256=runner_return[3]):
        return {"supported": False, "stage": status, "reason_code": "runner_model_feedback_unverified",
                "reason": "The guarded Runner tool request, result completion, and model turn are not verified."}
    parent_review_data = primary_review.to_dict()
    adaptive_state_row = adaptive._state(db_path, run_id)
    adaptive_review = json.loads(adaptive_state_row[2]) if adaptive_state_row and adaptive_state_row[2] else None
    if not isinstance(adaptive_review, Mapping):
        raise ValueError("native Planner/Skeptic primary review packet is unavailable")
    primary_args = {"concern": parent_review_data["reason"],
                    "evidence_fields": [ref.partition("#")[2]
                                        for ref in adaptive_review.get("evidence_refs", [])]}
    if (not primary_args["evidence_fields"] or
            not _tool_call(_trace_records(), tool="record_adaptive_review", args=primary_args,
                           role="skeptic", result=dict(adaptive_review), require_turn=True)):
        return {"supported": False, "stage": status, "reason_code": "primary_review_model_feedback_unverified",
                "reason": "The primary Skeptic review lacks a matching guarded native tool completion and model turn."}
    with sqlite3.connect(str(db_path), timeout=5) as db:
        supervisor_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_adaptive_supervisor_results'").fetchone()
        supervisor = db.execute("SELECT parent_result_id,response_text,response_sha256 FROM native_adaptive_supervisor_results WHERE run_id=?",
                                (run_id,)).fetchone() if supervisor_table else None
    if (not supervisor or supervisor[0] != parent_id or not isinstance(supervisor[1], str) or
            hashlib.sha256(supervisor[1].encode("utf-8")).hexdigest() != supervisor[2] or
            not _events_ok(store, run_id, event_type="native_adaptive_supervisor_returned", actor="host", payload_ref=parent_id)):
        return {"supported": False, "stage": status, "reason_code": "adaptive_supervisor_return_missing",
                "reason": "The adaptive PI must first return its Runner-informed supervisor response."}
    with sqlite3.connect(str(db_path), timeout=5) as db:
        final_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_adaptive_finalization_state'").fetchone()
        final_row = db.execute("SELECT parent_result_id,followup_result_id,status,review_json,review_sha256,freeze_json,freeze_sha256 "
                               "FROM native_adaptive_finalization_state WHERE run_id=?", (run_id,)).fetchone() if final_table else None
    if final_row and (final_row[0] != parent_id or final_row[1] != followup.result_id):
        raise ValueError("native finalization state is bound to different Results")
    stage = final_row[2] if final_row else "ready"
    review_packet = _decode_stage_record(final_row[3], final_row[4]) if final_row and final_row[3] else None
    freeze_packet = _decode_stage_record(final_row[5], final_row[6]) if final_row and final_row[5] else None
    if final_row and final_row[3]:
        final_concern = review_packet.get("review", {}).get("reason")
        if (not isinstance(final_concern, str) or not _tool_call(
                _trace_records(), tool="submit_native_final_review", args={"concern": final_concern},
                role="skeptic", result=review_packet, require_turn=True)):
            return _unsupported("final_review_model_feedback_unverified",
                                 "The final Skeptic review lacks a matching guarded tool completion and model turn.",
                                 stage=stage)
    if final_row and final_row[2] == "frozen":
        if not freeze_packet:
            raise ValueError("stored final protocol response is unavailable")
        holdout_id = freeze_packet.get("holdout_experiment_id")
        holdout_spec = store.get_spec(holdout_id) if isinstance(holdout_id, str) else None
        protocol = store.get_final_protocol(run_id)
        protocol_hash = hashlib.sha256(json.dumps(
            protocol, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if (not isinstance(protocol, dict) or protocol_hash != freeze_packet.get("protocol_sha256") or
                protocol.get("main_result_id") != parent_id or
                protocol.get("followup_result_id") != followup.result_id or
                holdout_spec is None or holdout_spec.split is not Split.HOLDOUT or
                holdout_spec.template is not Template.HOLDOUT_VALIDATION or
                holdout_spec.frozen_protocol_id != freeze_packet.get("frozen_protocol_id") or
                _has_result_for_experiment(store, holdout_id) or
                any(event.actor == "runner" and event.payload_ref == holdout_id
                    for event in store.list_events(run_id))):
            raise ValueError("frozen protocol or unexecuted holdout identity is invalid")
        explanation = freeze_packet.get("explanation")
        if (not isinstance(explanation, str) or not _tool_call(
                _trace_records(), tool="freeze_native_final_protocol", args={"explanation": explanation},
                role="pi", result=freeze_packet, require_turn=True)):
            return _unsupported("pi_freeze_model_feedback_unverified",
                                 "The PI freeze lacks a matching guarded tool completion and model turn.",
                                 stage="frozen_unverified")
        stage = "frozen_unexecuted"
    protocol_top = {"holdout_experiment_id": freeze_packet.get("holdout_experiment_id"),
                    "protocol_sha256": freeze_packet.get("protocol_sha256"),
                    "frozen_protocol_id": freeze_packet.get("frozen_protocol_id")} if freeze_packet else None
    return {"supported": True, "stage": stage,
            "run_id": run_id,
            "parent_result": {"spec": parent_spec.to_dict(), "result": parent.to_dict()},
            "followup_result": {"spec": followup_spec.to_dict(), "result": followup.to_dict()},
            "threshold_sensitivity": {"science_payload_sha256": payload_sha, "points": points,
                                      "primary_point_index": PRIMARY_POINT_INDEX,
                                      "primary_threshold_ev_atom": THRESHOLD_GRID_EV_ATOM[PRIMARY_POINT_INDEX],
                                      "quality_flags": science.get("quality_flags"),
                                      "scientific_status": science.get("scientific_status"),
                                      "scope": "discovery_only_not_holdout_validation_or_replication"},
            "primary_review": primary_review.to_dict(),
            "runner_feedback": {"response": response_data, "response_sha256": runner_return[3]},
            "final_review": review_packet,
            "final_review_sha256": final_row[4] if final_row else None,
            "final_protocol": protocol_top,
            "protocol_sha256": protocol_top.get("protocol_sha256") if protocol_top else None,
            "holdout_experiment_id": protocol_top.get("holdout_experiment_id") if protocol_top else None,
            "final_protocol_sha256": final_row[6] if final_row else None}


def read_finalization_state() -> dict[str, Any]:
    """Inspect finalization without creating or changing any finalization state."""
    return _resolve_followup(write=False)


def submit_native_final_review(concern: str) -> dict[str, Any]:
    """Submit the actual second-round Skeptic review for the bound threshold Result."""
    from nova import decision_tools
    from nova.contracts import Mode

    if not isinstance(concern, str) or not concern.strip() or len(concern.strip()) > 500:
        raise ValueError("final Skeptic concern must contain 1-500 characters")
    concern = concern.strip()
    state = _resolve_followup(write=True)
    if not state.get("supported"):
        raise ValueError(state.get("reason", "native threshold finalization is unsupported"))
    if state["stage"] != "ready":
        raise ValueError("final Skeptic review is out of order or already submitted")
    run_id = state["run_id"]
    followup_id = state["followup_result"]["result"]["result_id"]
    review_args = {"concern": concern}
    trace = _trace_records()
    if not _tool_call(trace, tool="submit_native_final_review", args=review_args,
                      role="skeptic", result=None, require_turn=False):
        raise ValueError("final review requires a guarded native Skeptic tool request")
    db_path, run_id, store = _context(write=True)
    with sqlite3.connect(str(db_path), timeout=5) as db:
        db.execute(_TABLE)
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT status FROM native_adaptive_finalization_state WHERE run_id=?", (run_id,)).fetchone()
        if existing:
            db.rollback()
            raise ValueError("native finalization review was already claimed")
        db.execute("INSERT INTO native_adaptive_finalization_state(run_id,parent_result_id,followup_result_id,status) "
                   "VALUES(?,?,?,'review_claimed')",
                   (run_id, state["parent_result"]["result"]["result_id"], followup_id))
    try:
        actual_db, actual_run = decision_tools._read_context()
        if Path(actual_db).resolve() != db_path.resolve() or actual_run != run_id:
            raise ValueError("decision tool context changed before final review")
        review = decision_tools.submit_final_review(followup_id, concern)
        actual_db, actual_run = decision_tools._read_context()
        if Path(actual_db).resolve() != db_path.resolve() or actual_run != run_id:
            raise ValueError("decision tool context changed during final review")
        saved = store.get_review(followup_id)
        if (saved is None or saved.experiment_id != state["followup_result"]["spec"]["experiment_id"] or
                saved.result_id != followup_id or saved.recommended_template is not None or
                not _events_ok(store, run_id, event_type="second_review", actor="skeptic", payload_ref=followup_id)):
            raise ValueError("existing final review tool did not persist the bound Skeptic review")
        response = {"review": saved.to_dict(), "stage": "reviewed", "followup_result_id": followup_id}
        encoded = _canonical(response)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with sqlite3.connect(str(db_path), timeout=5) as db:
            cursor = db.execute("UPDATE native_adaptive_finalization_state SET status='reviewed',review_json=?,review_sha256=? "
                                "WHERE run_id=? AND followup_result_id=? AND status='review_claimed'",
                                (encoded, digest, run_id, followup_id))
            if cursor.rowcount != 1:
                raise ValueError("final review stage changed before persistence")
        store.append_event(run_id, "native_adaptive_final_review_submitted", actor="host", mode=Mode.LIVE,
                           payload_ref=followup_id)
        return response
    except Exception:
        with sqlite3.connect(str(db_path), timeout=5) as db:
            db.execute("UPDATE native_adaptive_finalization_state SET status='review_failed' WHERE run_id=? AND status='review_claimed'",
                       (run_id,))
        store.append_event(run_id, "native_adaptive_final_review_failed", actor="host", mode=Mode.LIVE,
                           payload_ref=followup_id)
        raise


def freeze_native_final_protocol(explanation: str) -> dict[str, Any]:
    """Freeze the supported discovery protocol and register—but never execute—holdout."""
    from nova import decision_tools
    from nova.contracts import Mode, Split, Template

    if not isinstance(explanation, str) or len(explanation) > 500 or any(
            ord(char) < 32 and char not in "\t" for char in explanation):
        raise ValueError("PI final explanation must be at most 500 safe characters")
    explanation = explanation.strip()
    state = _resolve_followup(write=True)
    if not state.get("supported"):
        raise ValueError(state.get("reason", "native threshold finalization is unsupported"))
    if state["stage"] != "reviewed" or not state.get("final_review"):
        raise ValueError("PI freeze requires the completed second Skeptic review")
    db_path, run_id, store = _context(write=True)
    row = _state_row(db_path, run_id)
    selected_id = row[2]
    final_args = {"explanation": explanation}
    trace = _trace_records()
    if not _tool_call(trace, tool="freeze_native_final_protocol", args=final_args,
                      role="pi", result=None, require_turn=False):
        raise ValueError("PI freeze requires a guarded native PI tool request")
    review_digest = state["final_review_sha256"]
    final_review_packet = state["final_review"]
    final_concern = final_review_packet.get("review", {}).get("reason") if isinstance(final_review_packet, Mapping) else None
    if not review_digest or not isinstance(final_concern, str) or not _tool_call(trace, tool="submit_native_final_review",
                                           args={"concern": final_concern},
                                           role="skeptic", result=final_review_packet,
                                           require_turn=True):
        raise ValueError("PI freeze requires matched guarded final Skeptic request, returned review, and model turn")
    with sqlite3.connect(str(db_path), timeout=5) as db:
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute("UPDATE native_adaptive_finalization_state SET status='freeze_claimed' "
                            "WHERE run_id=? AND followup_result_id=? AND status='reviewed'",
                            (run_id, state["followup_result"]["result"]["result_id"]))
        if cursor.rowcount != 1:
            db.rollback()
            raise ValueError("PI freeze stage changed or was already claimed")
    try:
        actual_db, actual_run = decision_tools._read_context()
        if Path(actual_db).resolve() != db_path.resolve() or actual_run != run_id:
            raise ValueError("decision tool context changed before protocol freeze")
        outcome = decision_tools.freeze_final(state["parent_result"]["result"]["result_id"],
                                              state["followup_result"]["result"]["result_id"],
                                              explanation)
        actual_db, actual_run = decision_tools._read_context()
        if Path(actual_db).resolve() != db_path.resolve() or actual_run != run_id:
            raise ValueError("decision tool context changed during protocol freeze")
        holdout_id = outcome.get("holdout_experiment_id")
        protocol = store.get_final_protocol(run_id)
        holdout = store.get_spec(holdout_id) if isinstance(holdout_id, str) else None
        if (not isinstance(outcome.get("frozen_protocol_id"), str) or
                not isinstance(outcome.get("protocol_sha256"), str) or
                holdout is None or holdout.template is not Template.HOLDOUT_VALIDATION or
                holdout.split is not Split.HOLDOUT or holdout.frozen_protocol_id != outcome["frozen_protocol_id"] or
                _has_result_for_experiment(store, holdout_id) or
                any(event.actor == "runner" and event.payload_ref == holdout_id for event in store.list_events(run_id))):
            raise ValueError("existing freeze tool did not produce an unexecuted registered holdout Spec")
        response = {"frozen_protocol_id": outcome["frozen_protocol_id"],
                    "protocol_sha256": outcome["protocol_sha256"],
                    "holdout_experiment_id": holdout_id, "stage": "frozen_unexecuted",
                    "explanation": explanation}
        encoded = _canonical(response)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with sqlite3.connect(str(db_path), timeout=5) as db:
            cursor = db.execute("UPDATE native_adaptive_finalization_state SET status='frozen',freeze_json=?,freeze_sha256=? "
                                "WHERE run_id=? AND status='freeze_claimed'",
                                (encoded, digest, run_id))
            if cursor.rowcount != 1:
                raise ValueError("final protocol stage changed before persistence")
        store.append_event(run_id, "native_adaptive_final_protocol_frozen", actor="host", mode=Mode.LIVE,
                           payload_ref=response["frozen_protocol_id"])
        return response
    except Exception:
        with sqlite3.connect(str(db_path), timeout=5) as db:
            db.execute("UPDATE native_adaptive_finalization_state SET status='freeze_failed' WHERE run_id=? AND status='freeze_claimed'",
                       (run_id,))
        store.append_event(run_id, "native_adaptive_final_protocol_freeze_failed", actor="host", mode=Mode.LIVE,
                           payload_ref=selected_id)
        raise
