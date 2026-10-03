import json
import hashlib
import sqlite3

import pytest

from scripts.check_live_evidence import EvidenceError, check
from nova.contracts import ExperimentSpec, Result, Split, Template


def _db(path, events):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE events (run_id TEXT, seq INTEGER, event_json TEXT);
            CREATE TABLE specs (experiment_id TEXT, spec_json TEXT, spec_sha256 TEXT);
            CREATE TABLE results (result_id TEXT, experiment_id TEXT, result_json TEXT);
            CREATE TABLE reviews (result_id TEXT, review_json TEXT);
            CREATE TABLE final_protocols (run_id TEXT, frozen_protocol_id TEXT,
                protocol_sha256 TEXT, protocol_json TEXT, holdout_experiment_id TEXT);
        """)
        for seq, event in enumerate(events, 1):
            event = dict(event, run_id="r", seq=seq)
            db.execute("INSERT INTO events VALUES (?,?,?)", ("r", seq, json.dumps(event)))


def test_gate_rejects_fixture_and_human_scripted_provenance(tmp_path):
    db = tmp_path / "evidence.sqlite"
    _db(db, [{"event_type": "run_created", "mode": "fixture"}])
    with pytest.raises(EvidenceError, match="fixture/replay"):
        check(db, "r")

    db2 = tmp_path / "human.sqlite"
    _db(db2, [{"event_type": "run_created", "mode": "live", "note": "HUMAN_SCRIPTED"}])
    with pytest.raises(EvidenceError, match="human-scripted"):
        check(db2, "r")


def test_gate_rejects_missing_final_protocol_and_event_order(tmp_path):
    db = tmp_path / "incomplete.sqlite"
    _db(db, [
        {"event_type": "run_created", "mode": "live"},
        {"event_type": "hypothesis_frozen", "mode": "live"},
    ])
    with pytest.raises(EvidenceError, match="missing or out-of-order"):
        check(db, "r")


def test_gate_accepts_complete_live_decision_tools_record(tmp_path):
    db = tmp_path / "complete.sqlite"
    dataset = "d" * 64
    first = ExperimentSpec(1, "e1", "H1", dataset, Split.DISCOVERY,
                           Template.FAMILY_SCREEN, ("oxide",), "opt", (1.1, 1.8),
                           0.05, 10, 1729, 120)
    second = ExperimentSpec(1, "e2", "H1", dataset, Split.DISCOVERY,
                            Template.THRESHOLD_SENSITIVITY, ("oxide",), "opt", (1.1, 1.8),
                            0.05, 10, 1729, 120, "r1", "r1")
    protocol_id = "NOVA-FINAL-1234"
    holdout = ExperimentSpec(1, "h1", "H1", dataset, Split.HOLDOUT,
                             Template.HOLDOUT_VALIDATION, ("oxide",), "opt", (1.1, 1.8),
                             0.05, 10, 1729, 120, "r2", "r2", protocol_id)
    r1 = Result("r1", "e1", first.sha256, dataset, "completed", "ok", "t1", "t2", 1.0)
    r2 = Result("r2", "e2", second.sha256, dataset, "completed", "ok", "t3", "t4", 1.0)
    protocol = {
        "schema_version": 1, "hypothesis_id": "H1", "dataset_sha256": dataset,
        "main_result_id": "r1", "followup_result_id": "r2",
        "main_spec": first.to_dict(), "followup_spec": second.to_dict(),
        "review_refs": ["r1", "r2"], "explanation": "", "holdout_split": "holdout",
        "holdout_template": "holdout_validation",
    }
    protocol_hash = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    events = [
        {"event_type": "run_created", "mode": "live"},
        {"event_type": "objective_registered", "mode": "live"},
        {"event_type": "hypothesis_frozen", "mode": "live"},
        {"event_type": "plan_registered", "mode": "live"},
        {"event_type": "selection", "mode": "live", "payload_ref": "e1"},
        {"event_type": "running", "mode": "live"},
        {"event_type": "result", "mode": "live", "payload_ref": "r1"},
        {"event_type": "review", "mode": "live", "payload_ref": "r1"},
        {"event_type": "second_selection", "mode": "live", "payload_ref": "e2"},
        {"event_type": "running", "mode": "live"},
        {"event_type": "result", "mode": "live", "payload_ref": "r2"},
        {"event_type": "second_review", "mode": "live", "payload_ref": "r2"},
        {"event_type": "final_protocol_frozen", "mode": "live", "payload_ref": protocol_id},
    ]
    _db(db, events)
    with sqlite3.connect(db) as conn:
        for spec in (first, second, holdout):
            conn.execute("INSERT INTO specs VALUES (?,?,?)", (spec.experiment_id, spec.to_json(), spec.sha256))
        for result in (r1, r2):
            conn.execute("INSERT INTO results VALUES (?,?,?)", (result.result_id, result.experiment_id, result.to_json()))
        conn.execute("INSERT INTO reviews VALUES (?,?)", ("r1", json.dumps({"result_id": "r1", "claim_refs": ["r1"]})))
        conn.execute("INSERT INTO reviews VALUES (?,?)", ("r2", json.dumps({"result_id": "r2", "claim_refs": ["r2"]})))
        conn.execute("INSERT INTO final_protocols VALUES (?,?,?,?,?)", ("r", protocol_id, protocol_hash, json.dumps(protocol), "h1"))
    assert check(db, "r")["ok"] is True
