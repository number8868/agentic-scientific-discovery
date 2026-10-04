"""Host-owned registration and execution for the frozen discovery method audit.

The audit has a richer result schema than the canonical NOVA ``Result``.  Its
request and output therefore live in dedicated SQLite tables and are never
presented as a canonical experiment result.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from typing import Any

from . import live_bridge
from .contracts import Mode, Split, Template
from .process_control import ProcessController, WorkerTimeoutError
from .storage import Storage

MAX_WORKER_SECONDS = 120
_TABLES = """
CREATE TABLE IF NOT EXISTS registered_method_audits (
    audit_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    parent_result_id TEXT NOT NULL,
    parent_experiment_id TEXT NOT NULL,
    parent_spec_sha256 TEXT NOT NULL,
    dataset_sha256 TEXT NOT NULL,
    protocol_sha256 TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('registered','running','completed','failed')),
    UNIQUE(run_id, parent_result_id)
);
CREATE TABLE IF NOT EXISTS registered_method_audit_results (
    audit_id TEXT PRIMARY KEY,
    result_json TEXT NOT NULL
);
"""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _tables(path) -> None:
    with sqlite3.connect(str(path) if hasattr(path, "__fspath__") else path) as db:
        db.executescript(_TABLES)


def _protocol() -> tuple[dict[str, Any], str]:
    from .experiments import method_sensitivity

    protocol, digest = method_sensitivity._read_method_protocol()
    return protocol, digest


def _context():
    """Resolve ownership only through the established live bridge context."""
    path, run_id = live_bridge._read_context()
    return path, run_id, Storage(path).initialize()


def _owned_parent(store: Storage, run_id: str, parent_result_id: str,
                  protocol: dict[str, Any]):
    expected_dataset = protocol.get("dataset_sha256")
    result = store.get_result(parent_result_id)
    if result is None or result.execution_status != "completed" or result.error is not None:
        raise ValueError("method audit requires a completed parent result")
    spec = store.get_spec(result.experiment_id)
    if (spec is None or spec.template is not Template.FAMILY_SCREEN or
            spec.split is not Split.DISCOVERY or result.dataset_sha256 != expected_dataset or
            spec.dataset_sha256 != expected_dataset or result.spec_sha256 != spec.sha256):
        raise ValueError("parent result does not match the frozen discovery family protocol")
    if (list(spec.groups) != protocol.get("groups") or
            list(spec.gap_window_ev) != protocol.get("gap_window_ev") or
            spec.ehull_max_ev_atom != protocol.get("ehull_max_ev_atom") or
            spec.bootstrap_repeats != protocol.get("bootstrap_repeats") or
            spec.seed != protocol.get("seed") or spec.bandgap_method != "opt"):
        raise ValueError("parent spec does not match the frozen discovery family protocol")
    events = store.list_events(run_id)
    if not events or any(event.mode is not Mode.LIVE for event in events):
        raise ValueError("run is not authorized for a live method audit")
    selected = any(event.actor == "pi" and event.event_type in {"selection", "second_selection"}
                   and event.payload_ref == spec.experiment_id for event in events)
    owned_result = any(event.actor == "runner" and event.event_type == "result"
                       and event.payload_ref == result.result_id for event in events)
    if not selected or not owned_result:
        raise ValueError("parent result is not owned by this live run")
    return result, spec


def register_method_audit(parent_result_id: str) -> dict[str, Any]:
    """Register the one immutable, host-built method-audit request for a parent."""
    if (not isinstance(parent_result_id, str) or not parent_result_id or
            os.path.sep in parent_result_id or (os.path.altsep and os.path.altsep in parent_result_id)):
        raise ValueError("invalid parent result id")
    path, run_id, store = _context()
    protocol, protocol_sha256 = _protocol()
    dataset_sha256 = protocol.get("dataset_sha256")
    if not isinstance(dataset_sha256, str) or len(dataset_sha256) != 64:
        raise ValueError("frozen method protocol has no valid dataset hash")
    result, spec = _owned_parent(store, run_id, parent_result_id, protocol)
    events = store.list_events(run_id)
    if any(event.event_type == "second_selection" for event in events):
        raise ValueError("method audit registration is closed after the second selection")
    audit_id = "NOVA-METHOD-" + hashlib.sha256(
        f"{run_id}:{parent_result_id}:{spec.sha256}:{protocol_sha256}".encode()
    ).hexdigest()[:24]
    request = {
        "schema_version": 1,
        "audit_id": audit_id,
        "run_id": run_id,
        "parent_result_id": result.result_id,
        "parent_experiment_id": spec.experiment_id,
        "parent_spec_sha256": spec.sha256,
        "dataset_sha256": dataset_sha256,
        "protocol_sha256": protocol_sha256,
    }
    _tables(path)
    with sqlite3.connect(str(path), timeout=5) as db:
        if db.execute("SELECT 1 FROM registered_method_audits WHERE run_id=? LIMIT 1",
                      (run_id,)).fetchone():
            raise ValueError("method audit is already registered for this run")
    raw = _canonical(request)
    try:
        with sqlite3.connect(str(path), timeout=5) as db:
            db.execute("INSERT INTO registered_method_audits VALUES (?,?,?,?,?,?,?,?,?)",
                       (audit_id, run_id, result.result_id, spec.experiment_id, spec.sha256,
                        dataset_sha256, protocol_sha256, raw, "registered"))
        store.append_event(run_id, "method_audit_registered", actor="host", mode=Mode.LIVE,
                           payload_ref=audit_id)
    except sqlite3.IntegrityError:
        raise ValueError("method audit is already registered for this parent") from None
    return {**request, "status": "registered"}


def _run_frozen_audit() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The fixed worker callable; it accepts no caller-controlled arguments."""
    from .experiments.method_sensitivity import run_experiment

    return run_experiment()


def _controller_factory(registered):
    return ProcessController(registered)


def _validate_payload(result: Any, rows: Any, audit_id: str, dataset_hash: str,
                      protocol_hash: str, protocol: dict[str, Any]) -> dict[str, Any]:
    if (not isinstance(result, dict) or result.get("execution_status") != "success" or
            result.get("template") != "method_sensitivity" or result.get("split") != "discovery" or
            result.get("dataset_sha256") != dataset_hash or
            result.get("protocol_sha256") != protocol_hash or
            result.get("parent_protocol_sha256") != protocol.get("parent_protocol_sha256") or
            not isinstance(rows, list)):
        raise ValueError("frozen method audit output does not match its registered protocol")
    from .method_audit_report import _validate_result, _validate_row_aggregates, _validate_rows

    parsed_rows = _validate_rows(rows)
    _validate_result(result)
    _validate_row_aggregates(result, parsed_rows)
    return {"audit_id": audit_id, "result": result, "audit_rows": rows}


def execute_registered_method_audit(audit_id: str) -> dict[str, Any]:
    """Atomically claim and execute an owned, discovery-only registered audit."""
    if not isinstance(audit_id, str) or not audit_id or os.path.sep in audit_id:
        raise ValueError("invalid method audit id")
    path, run_id, store = _context()
    protocol, protocol_sha256 = _protocol()
    _tables(path)
    # Ownership and frozen hashes are rechecked before even looking at cached output.
    with sqlite3.connect(str(path), timeout=5) as db:
        row = db.execute("""SELECT parent_result_id,parent_experiment_id,parent_spec_sha256,
                          dataset_sha256,protocol_sha256,request_json,status
                          FROM registered_method_audits WHERE audit_id=? AND run_id=?""",
                         (audit_id, run_id)).fetchone()
    if row is None:
        raise ValueError("method audit is not registered for this run")
    parent_id, experiment_id, spec_hash, dataset_hash, registered_protocol_hash, request_raw, status = row
    if registered_protocol_hash != protocol_sha256 or dataset_hash != protocol.get("dataset_sha256"):
        raise ValueError("registered method audit protocol no longer matches")
    parent, spec = _owned_parent(store, run_id, parent_id, protocol)
    expected_request = {
        "schema_version": 1, "audit_id": audit_id, "run_id": run_id,
        "parent_result_id": parent.result_id,
        "parent_experiment_id": spec.experiment_id,
        "parent_spec_sha256": spec.sha256,
        "dataset_sha256": dataset_hash,
        "protocol_sha256": protocol_sha256,
    }
    expected_audit_id = "NOVA-METHOD-" + hashlib.sha256(
        f"{run_id}:{parent.result_id}:{spec.sha256}:{protocol_sha256}".encode()
    ).hexdigest()[:24]
    try:
        stored_request = json.loads(request_raw)
    except (TypeError, json.JSONDecodeError):
        raise ValueError("registered method audit request is invalid") from None
    if (audit_id != expected_audit_id or parent.experiment_id != experiment_id or spec.sha256 != spec_hash or
            stored_request != expected_request or _canonical(stored_request) != request_raw):
        raise ValueError("registered method audit ownership binding is invalid")
    events = store.list_events(run_id)
    if not any(e.event_type == "method_audit_registered" and e.actor == "host" and
               e.mode is Mode.LIVE and e.payload_ref == audit_id for e in events):
        raise ValueError("method audit registration event is missing")
    if status == "completed":
        with sqlite3.connect(str(path), timeout=5) as db:
            cached = db.execute("SELECT result_json FROM registered_method_audit_results WHERE audit_id=?",
                                (audit_id,)).fetchone()
        if cached is None or not any(e.event_type == "method_audit_completed" and e.actor == "host"
                                     and e.mode is Mode.LIVE and e.payload_ref == audit_id for e in events):
            raise ValueError("completed method audit result is not run-owned")
        try:
            cached_output = json.loads(cached[0])
            cached_result = cached_output["result"]
            validated_cache = _validate_payload(cached_result, cached_output["audit_rows"], audit_id,
                                                 dataset_hash, protocol_sha256, protocol)
            if cached_output != validated_cache or _canonical(cached_output) != cached[0]:
                raise ValueError
        except (TypeError, KeyError, ValueError, json.JSONDecodeError):
            raise ValueError("cached method audit result is invalid") from None
        return cached_output
    if status != "registered":
        raise ValueError("method audit request has already been claimed or failed")
    if any(e.event_type == "second_selection" for e in events):
        raise ValueError("method audit execution is closed after the second selection")
    # BEGIN IMMEDIATE makes the claim exclusive across host processes.
    with sqlite3.connect(str(path), timeout=5, isolation_level=None) as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute("""UPDATE registered_method_audits SET status='running'
                              WHERE audit_id=? AND run_id=? AND status='registered'""",
                             (audit_id, run_id)).rowcount
        db.commit()
    if changed != 1:
        raise ValueError("method audit request has already been claimed")
    store.append_event(run_id, "method_audit_running", actor="host", mode=Mode.LIVE,
                       payload_ref=audit_id)
    try:
        execution = _controller_factory({"run_frozen_method_audit": _run_frozen_audit}).run(
            "run_frozen_method_audit", (), deadline_seconds=MAX_WORKER_SECONDS
        )
        value = execution.value
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            raise ValueError("frozen method audit returned an invalid payload")
        result, rows = value
        output = _validate_payload(result, rows, audit_id, dataset_hash, protocol_sha256, protocol)
        raw = _canonical(output)
        with sqlite3.connect(str(path), timeout=5) as db:
            db.execute("INSERT INTO registered_method_audit_results VALUES (?,?)", (audit_id, raw))
            db.execute("UPDATE registered_method_audits SET status='completed' WHERE audit_id=? AND status='running'",
                       (audit_id,))
        store.append_event(run_id, "method_audit_completed", actor="host", mode=Mode.LIVE,
                           payload_ref=audit_id)
        return output
    except WorkerTimeoutError:
        _mark_failed(path, audit_id)
        store.append_event(run_id, "method_audit_failed", actor="host", mode=Mode.LIVE,
                           payload_ref=audit_id)
        raise ValueError("registered method audit timed out") from None
    except Exception:
        _mark_failed(path, audit_id)
        try:
            store.append_event(run_id, "method_audit_failed", actor="host", mode=Mode.LIVE,
                               payload_ref=audit_id)
        except Exception:
            pass
        raise ValueError("registered method audit failed") from None


def _mark_failed(path, audit_id: str) -> None:
    with sqlite3.connect(str(path), timeout=5) as db:
        db.execute("UPDATE registered_method_audits SET status='failed' WHERE audit_id=? AND status='running'",
                   (audit_id,))
