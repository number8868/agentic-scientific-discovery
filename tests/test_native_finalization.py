from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from nova import adaptive_agent_tools as adaptive
from nova import decision_tools
from nova.contracts import Concern, Mode, ReviewPacket, Template
from nova.native_finalization_tools import (
    _canonical,
    _decode_stage_record,
    _has_result_for_experiment,
    freeze_native_final_protocol,
    read_finalization_state,
    submit_native_final_review,
)
from nova.storage import Storage


EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "results" / "adaptive_live_02_with_science"
RUN_ID = "native-finalization-test"
FOLLOWUP_ID = "NOVA-e9d66bd1875e488f"
PAYLOAD_SHA = "0f0af36d9dd4a9325cb3c5943956abd62c22a802e04455750f55ace4051e09c3"


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _trace_append(path, *, event, actor, tool=None, call_id=None, pid=4321, role=None,
                  args=None, result=None, result_hash=None, status=None, details=None):
    row = {"event": event, "actor": actor, "tool": tool, "call_id": call_id, "pid": pid,
           "role": role, "status": status, "details": details,
           "args_sha256": _digest(args) if args is not None else None,
           "result_sha256": _digest(result) if result is not None else None,
           "structured_result_sha256": result_hash}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _guard(path, role):
    binary = path.parent / "codex-code-mode-host"
    if not binary.exists():
        binary.write_text("synthetic test executable", encoding="utf-8")
        binary.chmod(0o700)
    _trace_append(path, event="executor_guard_installed", actor="native-adaptive-runtime", role=role,
                  details={"native_tools_disabled": True, "web_search_disabled": True, "skills": "none",
                           "config_overrides": ["features.code_mode_host=true", "features.code_mode=false",
                                                'web_search="disabled"'], "host_binary": str(binary)})


def _request(path, tool, args, *, role, call_id):
    _guard(path, role)
    _trace_append(path, event="tool_request", actor="codex-model", tool=tool,
                  call_id=call_id, role=role, args=args)


def _complete_turn(path, tool, *, role, call_id, result):
    digest = _digest(result)
    _trace_append(path, event="tool_complete", actor="omnigent-tool-dispatch", tool=tool,
                  call_id=call_id, role=role, result=result, result_hash=digest, status="success")
    _trace_append(path, event="turn_complete", actor="codex-model", role=role)


def _seed_native_run(tmp_path, monkeypatch, *, choice="threshold_sensitivity", status="completed"):
    from nova.contracts import ExperimentSpec, Result

    specs = [ExperimentSpec.from_dict(item) for item in json.loads((EVIDENCE / "specs.json").read_text())]
    results = [Result.from_dict(item) for item in json.loads((EVIDENCE / "results.json").read_text())]
    parent_spec = next(item for item in specs if item.template is Template.FAMILY_SCREEN)
    followup_spec = next(item for item in specs if item.experiment_id == FOLLOWUP_ID)
    parent = next(item for item in results if item.experiment_id == parent_spec.experiment_id)
    followup = next(item for item in results if item.experiment_id == FOLLOWUP_ID)
    run_dir = tmp_path / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    db_path = run_dir / "run.sqlite"
    store = Storage(db_path).initialize()
    store.register_spec(parent_spec)
    store.register_spec(followup_spec)
    store.save_result(parent)
    store.save_result(followup)
    for event_type, actor, payload in (
        ("selection", "pi", parent_spec.experiment_id),
        ("result", "runner", parent.result_id),
        ("review", "skeptic", parent.result_id),
        ("second_selection", "pi", followup_spec.experiment_id),
        ("result", "runner", followup.result_id),
        ("native_adaptive_choice_committed", "pi", followup_spec.experiment_id),
        ("native_adaptive_runner_started", "runner", followup_spec.experiment_id),
        ("native_adaptive_runner_result_returned", "runner", followup.result_id),
        ("native_adaptive_supervisor_returned", "host", parent.result_id),
    ):
        store.append_event(RUN_ID, event_type, actor=actor, mode=Mode.LIVE, payload_ref=payload)
    primary_concern = "Only nine passing observations inform the snapshot contrast."
    primary_review = ReviewPacket(parent_spec.experiment_id, parent.result_id,
                                  (Concern("final_protocol", "medium", (parent.result_id,)),),
                                  Template.THRESHOLD_SENSITIVITY, primary_concern, (parent.result_id,))
    store.save_review(primary_review)
    state_review = {"parent_result_id": parent.result_id, "concern": primary_concern,
                    "evidence": {"groups_summary": parent.to_dict()["groups_summary"]},
                    "evidence_refs": [f"result:{parent.result_id}#groups_summary"]}
    selection = {"choice": choice, "selected_id": followup_spec.experiment_id if choice != "stop" else None}
    with sqlite3.connect(db_path) as db:
        db.executescript(adaptive._TABLE)
        db.execute("UPDATE native_adaptive_state SET parent_result_id=?,packet_json='{}',review_json=?,selection_json=?,"
                   "selected_id=?,selected_kind=?,status=? WHERE run_id=?",
                   (parent.result_id, json.dumps(state_review), json.dumps(selection),
                    followup_spec.experiment_id if choice != "stop" else None,
                    "experiment_id" if choice == "threshold_sensitivity" else "audit_id" if choice == "method_sensitivity" else None,
                    status, RUN_ID))
        # Ensure one durable state row exists even in the synthetic fixture.
        db.execute("INSERT OR IGNORE INTO native_adaptive_state(run_id,parent_result_id,packet_json,review_json,selection_json,selected_id,selected_kind,status) "
                   "VALUES(?,?,?,?,?,?,?,?)", (RUN_ID, parent.result_id, "{}", json.dumps(state_review),
                    json.dumps(selection), followup_spec.experiment_id if choice != "stop" else None,
                    "experiment_id" if choice == "threshold_sensitivity" else "audit_id" if choice == "method_sensitivity" else None,
                    status))
    threshold_artifact = EVIDENCE / "science-artifacts" / f"science-payload-{PAYLOAD_SHA}.json"
    run_root = tmp_path / "runs"
    (run_root / threshold_artifact.name).write_bytes(threshold_artifact.read_bytes())
    monkeypatch.setattr(adaptive, "ROOT", tmp_path)
    context = lambda: (db_path, RUN_ID)
    from nova import live_bridge
    monkeypatch.setattr(live_bridge, "_read_context", context)
    monkeypatch.setattr(decision_tools, "_read_context", context)
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID", RUN_ID)
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_DATABASE", str(db_path))
    monkeypatch.setenv("NOVA_ADAPTIVE_BUDGET_DEADLINE", str(time.monotonic() + 300))

    feedback = {"registered_id": followup_spec.experiment_id, "result": followup.to_dict(),
                "discovery_threshold_sensitivity": {"science_payload_sha256": PAYLOAD_SHA}}
    feedback_text = _canonical(feedback)
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE native_adaptive_runner_returns(run_id TEXT PRIMARY KEY,registered_id TEXT NOT NULL,"
                   "result_ref TEXT NOT NULL,response_json TEXT NOT NULL,response_sha256 TEXT NOT NULL)")
        db.execute("INSERT INTO native_adaptive_runner_returns VALUES(?,?,?,?,?)",
                   (RUN_ID, followup_spec.experiment_id, followup.result_id,
                    feedback_text, _digest(feedback)))
        db.execute("CREATE TABLE native_adaptive_supervisor_results(run_id TEXT PRIMARY KEY,parent_result_id TEXT NOT NULL,"
                   "response_text TEXT NOT NULL,response_sha256 TEXT NOT NULL)")
        supervisor_text = "Planner, Skeptic, PI and Runner returned the actual threshold Result."
        db.execute("INSERT INTO native_adaptive_supervisor_results VALUES(?,?,?,?)",
                   (RUN_ID, parent.result_id, supervisor_text, hashlib.sha256(supervisor_text.encode()).hexdigest()))

    trace_path = run_dir / "native-model-audit.jsonl"
    trace_path.touch(mode=0o600)
    trace_path.chmod(0o600)
    monkeypatch.setenv("NOVA_ADAPTIVE_TRACE_PATH", str(trace_path))
    # Native Runner response chain and the original primary Skeptic submission.
    runner_args = {"registered_id": followup_spec.experiment_id}
    _request(trace_path, "execute_selected_adaptive", runner_args, role="runner", call_id="runner-call")
    _complete_turn(trace_path, "execute_selected_adaptive", role="runner", call_id="runner-call", result=feedback)
    skeptic_args = {"concern": primary_concern, "evidence_fields": ["groups_summary"]}
    _request(trace_path, "record_adaptive_review", skeptic_args, role="skeptic", call_id="primary-review-call")
    _complete_turn(trace_path, "record_adaptive_review", role="skeptic", call_id="primary-review-call", result=state_review)
    return db_path, store, trace_path, parent, followup, followup_spec


def test_threshold_finalization_requires_order_and_freezes_unexecuted_only(tmp_path, monkeypatch):
    db_path, store, trace, _parent, followup, _spec = _seed_native_run(tmp_path, monkeypatch)
    state = read_finalization_state()
    assert state["supported"] is True, state
    assert state["stage"] == "ready"
    assert state["followup_result"]["result"]["result_id"] == followup.result_id
    with pytest.raises(ValueError, match="requires the completed second Skeptic review"):
        freeze_native_final_protocol("Freeze after reviewing the completed threshold grid.")

    concern = "The registered threshold contrast remains discovery-only."
    _request(trace, "submit_native_final_review", {"concern": concern}, role="skeptic", call_id="final-review-call")
    review_response = submit_native_final_review(concern)
    assert review_response["stage"] == "reviewed"
    _complete_turn(trace, "submit_native_final_review", role="skeptic", call_id="final-review-call",
                   result=review_response)
    with pytest.raises(ValueError, match="already submitted"):
        submit_native_final_review("duplicate review")

    explanation = "Freeze the registered discovery protocol; holdout remains unexecuted."
    _request(trace, "freeze_native_final_protocol", {"explanation": explanation}, role="pi", call_id="freeze-call")
    frozen = freeze_native_final_protocol(explanation)
    assert frozen["stage"] == "frozen_unexecuted"
    _complete_turn(trace, "freeze_native_final_protocol", role="pi", call_id="freeze-call", result=frozen)
    accepted = read_finalization_state()
    assert accepted["stage"] == "frozen_unexecuted"
    assert accepted["holdout_experiment_id"] == frozen["holdout_experiment_id"]
    assert accepted["final_review"]["review"]["result_id"] == followup.result_id
    assert not _has_result_for_experiment(store, frozen["holdout_experiment_id"])
    assert not any(event.actor == "runner" and event.payload_ref == frozen["holdout_experiment_id"]
                   for event in store.list_events(RUN_ID))
    with pytest.raises(ValueError, match="requires the completed second Skeptic review"):
        freeze_native_final_protocol("second freeze")


@pytest.mark.parametrize(("choice", "selected_kind", "reason_code"), [
    ("method_sensitivity", "audit_id", "unsupported_method_audit"),
    ("stop", None, "unsupported_stop"),
])
def test_method_and_stop_are_explicitly_unsupported(tmp_path, monkeypatch, choice, selected_kind, reason_code):
    _db, _store, _trace, *_ = _seed_native_run(tmp_path, monkeypatch, choice=choice)
    state = read_finalization_state()
    assert state["supported"] is False
    assert state["reason_code"] == reason_code
    assert "threshold" in state["reason"].lower() or "stopped" in state["reason"].lower()
    with pytest.raises(ValueError, match="threshold|stopped"):
        submit_native_final_review("unsupported path")
    with pytest.raises(ValueError, match="threshold|stopped"):
        freeze_native_final_protocol("unsupported path")


def test_cross_run_binding_and_expired_deadline_fail_before_write(tmp_path, monkeypatch):
    _db, _store, _trace, *_ = _seed_native_run(tmp_path, monkeypatch)
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID", "other-run")
    with pytest.raises(ValueError, match="differs from the trusted adaptive run binding"):
        read_finalization_state()
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID", RUN_ID)
    monkeypatch.setenv("NOVA_ADAPTIVE_BUDGET_DEADLINE", str(time.monotonic() - 1))
    with pytest.raises(TimeoutError, match="deadline"):
        submit_native_final_review("not accepted after deadline")
    with sqlite3.connect(_db) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='native_adaptive_finalization_state'").fetchone() is None


def test_stage_packet_hash_and_executed_holdout_predicate(tmp_path):
    packet = {"stage": "frozen", "holdout_experiment_id": "holdout-id"}
    raw = _canonical(packet)
    assert _decode_stage_record(raw, _digest(packet)) == packet
    with pytest.raises(ValueError, match="hash"):
        _decode_stage_record(raw, "0" * 64)
    store = Storage(tmp_path / "simple.sqlite").initialize()
    assert not _has_result_for_experiment(store, "holdout-id")
