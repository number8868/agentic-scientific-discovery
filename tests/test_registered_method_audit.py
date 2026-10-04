import json
import sqlite3

import pytest

from nova import registered_method_audit as audit
from nova.contracts import ExperimentSpec, Result, Split, Template
from nova.storage import Storage
from nova.process_control import WorkerTimeoutError, WorkerResult


DATASET = "f9e0a3309f0000d5de1ec9e49c93963109ea45e63f451103f8f6595d2eabf7f5"
PROTOCOL_HASH = "ef09b94e6eebec20974ae4d05647f718471880e44cecb0bbaee55f2c2d050b03"


class InlineController:
    calls = 0
    output = None

    def __init__(self, registered):
        self.registered = registered

    def run(self, name, args=(), kwargs=None, *, deadline_seconds):
        assert name == "run_frozen_method_audit"
        assert args == ()
        assert deadline_seconds == 120
        type(self).calls += 1
        return WorkerResult(type(self).output, 1)


class TimeoutController:
    def __init__(self, registered):
        pass

    def run(self, name, args=(), kwargs=None, *, deadline_seconds):
        assert deadline_seconds == 120
        raise WorkerTimeoutError("deadline")


class FailingController:
    def __init__(self, registered):
        pass

    def run(self, name, args=(), kwargs=None, *, deadline_seconds):
        raise RuntimeError("worker failed")


def setup(tmp_path, monkeypatch):
    db_path = tmp_path / "live.sqlite"
    store = Storage(db_path).initialize()
    db_path.chmod(0o600)
    spec = ExperimentSpec(1, "E-parent", "H-001", DATASET, Split.DISCOVERY,
                          Template.FAMILY_SCREEN, ("oxide", "chalcogenide"),
                          "opt", (1.1, 1.8), .05, 2000, 1729, 120)
    store.register_spec(spec)
    parent = Result("R-parent", spec.experiment_id, spec.sha256, DATASET,
                    "completed", "inconclusive", "start", "finish", 1.0)
    store.save_result(parent)
    store.append_event("run-1", "run_created", actor="host", mode="live")
    store.append_event("run-1", "selection", actor="pi", mode="live", payload_ref=spec.experiment_id)
    store.append_event("run-1", "result", actor="runner", mode="live", payload_ref=parent.result_id)
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    context.chmod(0o600)
    monkeypatch.setattr(audit.live_bridge, "_read_context", lambda: (db_path, "run-1"))
    from nova.experiments import method_sensitivity

    protocol, actual_protocol_hash = method_sensitivity._read_method_protocol()
    assert actual_protocol_hash == PROTOCOL_HASH
    monkeypatch.setattr(audit, "_protocol", lambda: (protocol, PROTOCOL_HASH))
    rows = [
        {"split": "discovery", "excluded": False, "is_representative": True,
         "family": "oxide", "jid": "JVASP-1", "reduced_formula": "AB",
         "ehull_valid": True, "ehull_ev_atom": .01,
         "opt_gap_ev": 1.4, "mbj_gap_ev": 1.5},
        {"split": "discovery", "excluded": False, "is_representative": True,
         "family": "chalcogenide", "jid": "JVASP-2", "reduced_formula": "CD",
         "ehull_valid": True, "ehull_ev_atom": .01,
         "opt_gap_ev": 1.4, "mbj_gap_ev": 1.5},
    ]
    analysis, audit_rows = method_sensitivity.analyze_rows(rows, protocol)
    InlineController.calls = 0
    InlineController.output = ({
        "execution_status": "success",
        "template": "method_sensitivity",
        "split": "discovery",
        "dataset_sha256": DATASET,
        "protocol_sha256": PROTOCOL_HASH,
        "parent_protocol_sha256": protocol["parent_protocol_sha256"],
        "selection_mode": "human_selected",
        **analysis,
    }, audit_rows)
    monkeypatch.setattr(audit, "_controller_factory", InlineController)
    return store, spec, parent


def test_registration_is_parent_bound_and_duplicate_fails(tmp_path, monkeypatch):
    _, _, parent = setup(tmp_path, monkeypatch)
    registered = audit.register_method_audit(parent.result_id)
    assert registered["status"] == "registered"
    assert registered["dataset_sha256"] == DATASET
    assert registered["protocol_sha256"] == PROTOCOL_HASH
    assert registered["parent_result_id"] == parent.result_id
    with pytest.raises(ValueError, match="already registered"):
        audit.register_method_audit(parent.result_id)


def test_execution_persists_rich_output_and_ownership_checked_cache(tmp_path, monkeypatch):
    store, _, parent = setup(tmp_path, monkeypatch)
    request = audit.register_method_audit(parent.result_id)
    value = audit.execute_registered_method_audit(request["audit_id"])
    assert value["result"]["template"] == "method_sensitivity"
    assert len(value["audit_rows"]) == 2
    assert InlineController.calls == 1
    cached = audit.execute_registered_method_audit(request["audit_id"])
    assert cached == value
    assert InlineController.calls == 1
    assert store.get_result(parent.result_id) is not None
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM registered_method_audit_results").fetchone()[0] == 1
    event_types = [event.event_type for event in store.list_events("run-1")]
    assert "method_audit_registered" in event_types
    assert "method_audit_completed" in event_types


def test_foreign_audit_id_and_parent_without_owned_result_fail(tmp_path, monkeypatch):
    store, _, parent = setup(tmp_path, monkeypatch)
    request = audit.register_method_audit(parent.result_id)
    monkeypatch.setattr(audit.live_bridge, "_read_context", lambda: (store.path, "other-run"))
    with pytest.raises(ValueError, match="not registered for this run"):
        audit.execute_registered_method_audit(request["audit_id"])


def test_request_field_tamper_is_rejected(tmp_path, monkeypatch):
    store, _, parent = setup(tmp_path, monkeypatch)
    request = audit.register_method_audit(parent.result_id)
    with sqlite3.connect(store.path) as db:
        row = db.execute("SELECT request_json FROM registered_method_audits WHERE audit_id=?",
                         (request["audit_id"],)).fetchone()
        changed = json.loads(row[0])
        changed["parent_result_id"] = "foreign-result"
        db.execute("UPDATE registered_method_audits SET request_json=? WHERE audit_id=?",
                   (json.dumps(changed, sort_keys=True, separators=(",", ":")), request["audit_id"]))
    with pytest.raises(ValueError, match="ownership binding"):
        audit.execute_registered_method_audit(request["audit_id"])


def test_forged_cached_payload_is_rejected(tmp_path, monkeypatch):
    store, _, parent = setup(tmp_path, monkeypatch)
    request = audit.register_method_audit(parent.result_id)
    forged = {"audit_id": request["audit_id"], "result": {"execution_status": "success"}, "audit_rows": []}
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE registered_method_audits SET status='completed' WHERE audit_id=?",
                   (request["audit_id"],))
        db.execute("INSERT INTO registered_method_audit_results VALUES (?,?)",
                   (request["audit_id"], json.dumps(forged, sort_keys=True, separators=(",", ":"))))
    store.append_event("run-1", "method_audit_completed", actor="host", mode="live",
                       payload_ref=request["audit_id"])
    with pytest.raises(ValueError, match="cached method audit result is invalid"):
        audit.execute_registered_method_audit(request["audit_id"])


def test_registration_rejects_after_threshold_selection(tmp_path, monkeypatch):
    store, _, parent = setup(tmp_path, monkeypatch)
    store.append_event("run-1", "second_selection", actor="pi", mode="live",
                       payload_ref="E-threshold")
    with pytest.raises(ValueError, match="closed after the second selection"):
        audit.register_method_audit(parent.result_id)


def test_timeout_is_failed_and_cannot_be_retried(tmp_path, monkeypatch):
    _, _, parent = setup(tmp_path, monkeypatch)
    request = audit.register_method_audit(parent.result_id)
    monkeypatch.setattr(audit, "_controller_factory", TimeoutController)
    with pytest.raises(ValueError, match="timed out"):
        audit.execute_registered_method_audit(request["audit_id"])
    with pytest.raises(ValueError, match="already been claimed or failed"):
        audit.execute_registered_method_audit(request["audit_id"])


def test_worker_failure_cannot_be_retried(tmp_path, monkeypatch):
    _, _, parent = setup(tmp_path, monkeypatch)
    request = audit.register_method_audit(parent.result_id)
    monkeypatch.setattr(audit, "_controller_factory", FailingController)
    with pytest.raises(ValueError, match="registered method audit failed"):
        audit.execute_registered_method_audit(request["audit_id"])
    with pytest.raises(ValueError, match="already been claimed or failed"):
        audit.execute_registered_method_audit(request["audit_id"])


def test_incomplete_or_fixture_parent_is_rejected(tmp_path, monkeypatch):
    store, _, parent = setup(tmp_path, monkeypatch)
    store.append_event("run-1", "noise", actor="host", mode="fixture")
    with pytest.raises(ValueError, match="live method audit"):
        audit.register_method_audit(parent.result_id)
