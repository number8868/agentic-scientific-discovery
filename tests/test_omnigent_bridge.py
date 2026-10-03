import os
import json
import stat
import pytest
from nova.contracts import ExperimentSpec, Template, Split
from nova import omnigent_bridge
from nova.omnigent_bridge import execute_fixture_registered_experiment
from nova.storage import Storage

def test_cross_process_fixture_bridge(tmp_path, monkeypatch):
    db = tmp_path / "run.sqlite"
    store = Storage(db).initialize()
    db.chmod(0o600)
    spec = ExperimentSpec(1, "E1", "H1", "a" * 64, Split.DISCOVERY,
                          Template.FAMILY_SCREEN, ("oxide", "chalcogenide"), "opt",
                          (1.1, 1.8), .05, 20, 1729, 120)
    store.register_spec(spec)
    store.append_event("run-1", "run_created", actor="host", mode="fixture")
    store.append_event("run-1", "selection", actor="pi", mode="fixture", payload_ref="E1")
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"schema_version": 1, "mode": "fixture", "db": str(db), "run_id": "run-1"}))
    context.chmod(0o600); monkeypatch.setattr(omnigent_bridge, "CONTEXT_PATH", context)
    monkeypatch.setenv("NOVA_RUN_DB", "/invalid/env/path"); monkeypatch.setenv("NOVA_RUN_ID", "wrong")
    first = execute_fixture_registered_experiment("E1")
    second = execute_fixture_registered_experiment("E1")
    assert first == second
    assert store.read_result(first.result_id).quality_flags == ("fixture",)

def test_bridge_rejects_cross_run_live_and_unknown(tmp_path, monkeypatch):
    db = tmp_path / "run.sqlite"; store = Storage(db).initialize(); db.chmod(0o600)
    spec = ExperimentSpec(1, "E1", "H1", "a" * 64, Split.DISCOVERY, Template.FAMILY_SCREEN,
                          ("oxide",), "opt", (1.1, 1.8), .05, 2, 1729, 120)
    store.register_spec(spec)
    store.append_event("run-live", "run_created", actor="host", mode="live")
    store.append_event("run-live", "selection", actor="pi", mode="live", payload_ref="E1")
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"schema_version": 1, "mode": "fixture", "db": str(db), "run_id": "run-live"}))
    context.chmod(0o600); monkeypatch.setattr(omnigent_bridge, "CONTEXT_PATH", context)
    with pytest.raises(ValueError): execute_fixture_registered_experiment("E1")
    monkeypatch.setenv("NOVA_RUN_ID", "other")
    with pytest.raises(ValueError): execute_fixture_registered_experiment("missing")
