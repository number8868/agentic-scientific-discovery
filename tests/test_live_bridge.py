import json
import pytest
from nova import live_bridge
from nova.contracts import ExperimentSpec, Result, Split, Template
from nova.storage import Storage
from nova.process_control import WorkerTimeoutError, WorkerResult


class InlineController:
    def __init__(self, registered): self.registered = registered
    def run(self, name, args=(), kwargs=None, *, deadline_seconds):
        return WorkerResult(self.registered[name](*args, **(kwargs or {})), 1)

def setup(tmp_path, mode="live", *, split=Split.DISCOVERY, template=Template.FAMILY_SCREEN):
    db=tmp_path/"live.sqlite"; st=Storage(db).initialize(); db.chmod(0o600)
    spec=ExperimentSpec(1,"E1","H1","d"*64,split,template,("oxide","chalcogenide"),"opt",(1.1,1.8),.05,2,1729,120)
    st.register_spec(spec); st.append_event("run", "run_created", actor="host", mode=mode); st.append_event("run", "selection", actor="pi", mode=mode, payload_ref="E1")
    c=tmp_path/"context.json"; c.write_text(json.dumps({"schema_version":1,"mode":"live","db":str(db),"run_id":"run"})); c.chmod(0o600)
    return st,c,spec

def test_live_bridge_rejects_non_discovery_before_worker_start(monkeypatch, tmp_path):
    st, c, _ = setup(tmp_path, split=Split.HOLDOUT)
    monkeypatch.setattr(live_bridge, "LIVE_CONTEXT_PATH", c)

    def should_not_start(_registered):
        raise AssertionError("holdout spec reached worker construction")

    monkeypatch.setattr(live_bridge, "_controller_factory", should_not_start)
    with pytest.raises(ValueError, match="requires a discovery split"):
        live_bridge.execute_live_registered_experiment("E1")
    assert st.list_results() == []
    assert [event.event_type for event in st.list_events("run")] == ["run_created", "selection"]

def test_live_bridge_authorization_idempotency(monkeypatch,tmp_path):
    st,c,s=setup(tmp_path); monkeypatch.setattr(live_bridge,"LIVE_CONTEXT_PATH",c)
    r=Result("R","E1",s.sha256,s.dataset_sha256,"completed","inconclusive","s","f",0)
    monkeypatch.setattr("nova.science_adapter.execute_science_experiment",lambda payload:r)
    monkeypatch.setattr(live_bridge, "_controller_factory", InlineController)
    assert live_bridge.execute_live_registered_experiment("E1") == r
    assert live_bridge.execute_live_registered_experiment("E1") == r
    assert len(st.list_results()) == 1

def test_live_bridge_rejects_cross_mode_and_env(monkeypatch,tmp_path):
    st,c,s=setup(tmp_path,mode="fixture"); monkeypatch.setattr(live_bridge,"LIVE_CONTEXT_PATH",c); monkeypatch.setenv("NOVA_RUN_DB","bad")
    with pytest.raises(ValueError): live_bridge.execute_live_registered_experiment("E1")

def test_live_bridge_failure_event(monkeypatch,tmp_path):
    st,c,s=setup(tmp_path); monkeypatch.setattr(live_bridge,"LIVE_CONTEXT_PATH",c)
    monkeypatch.setattr("nova.science_adapter.execute_science_experiment",lambda payload: (_ for _ in ()).throw(ValueError("bad")))
    monkeypatch.setattr(live_bridge, "_controller_factory", InlineController)
    with pytest.raises(ValueError): live_bridge.execute_live_registered_experiment("E1")
    assert st.list_events("run")[-1].event_type == "tool_failed"


class TimeoutController:
    def __init__(self, registered): pass
    def run(self, name, args=(), kwargs=None, *, deadline_seconds):
        assert deadline_seconds == 120
        raise WorkerTimeoutError("deadline")


def test_live_bridge_timeout_saves_no_result(monkeypatch, tmp_path):
    st, c, _ = setup(tmp_path)
    monkeypatch.setattr(live_bridge, "LIVE_CONTEXT_PATH", c)
    monkeypatch.setattr(live_bridge, "_controller_factory", TimeoutController)
    with pytest.raises(ValueError, match="timed out"):
        live_bridge.execute_live_registered_experiment("E1")
    assert st.list_results() == []
    assert st.list_events("run")[-1].event_type == "tool_failed"

def test_live_bridge_rejects_result_for_wrong_registered_spec(monkeypatch, tmp_path):
    st, c, s = setup(tmp_path)
    monkeypatch.setattr(live_bridge, "LIVE_CONTEXT_PATH", c)
    wrong = Result("R", "other", s.sha256, s.dataset_sha256, "completed", "inconclusive", "s", "f", 0)
    monkeypatch.setattr("nova.science_adapter.execute_science_experiment", lambda payload: wrong)
    monkeypatch.setattr(live_bridge, "_controller_factory", InlineController)
    with pytest.raises(ValueError, match="live execution failed"):
        live_bridge.execute_live_registered_experiment("E1")
    assert st.list_results() == []
    assert st.list_events("run")[-1].event_type == "tool_failed"

def test_live_bridge_does_not_accept_orphan_existing_result(monkeypatch, tmp_path):
    st, c, s = setup(tmp_path)
    orphan = Result("orphan", "E1", s.sha256, s.dataset_sha256, "completed", "inconclusive", "s", "f", 0)
    st.save_result(orphan)
    monkeypatch.setattr(live_bridge, "LIVE_CONTEXT_PATH", c)
    with pytest.raises(ValueError, match="run-owned result"):
        live_bridge.execute_live_registered_experiment("E1")
