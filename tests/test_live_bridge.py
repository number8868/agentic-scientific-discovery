import json
import pytest
from nova import live_bridge
from nova.contracts import ExperimentSpec, Result, Split, Template
from nova.storage import Storage

def setup(tmp_path, mode="live"):
    db=tmp_path/"live.sqlite"; st=Storage(db).initialize(); db.chmod(0o600)
    spec=ExperimentSpec(1,"E1","H1","d"*64,Split.DISCOVERY,Template.FAMILY_SCREEN,("oxide","chalcogenide"),"opt",(1.1,1.8),.05,2,1729,120)
    st.register_spec(spec); st.append_event("run", "run_created", actor="host", mode=mode); st.append_event("run", "selection", actor="pi", mode=mode, payload_ref="E1")
    c=tmp_path/"context.json"; c.write_text(json.dumps({"schema_version":1,"mode":"live","db":str(db),"run_id":"run"})); c.chmod(0o600)
    return st,c,spec

def test_live_bridge_authorization_idempotency(monkeypatch,tmp_path):
    st,c,s=setup(tmp_path); monkeypatch.setattr(live_bridge,"LIVE_CONTEXT_PATH",c)
    r=Result("R","E1",s.sha256,s.dataset_sha256,"completed","inconclusive","s","f",0)
    monkeypatch.setattr("nova.science_adapter.execute_science_experiment",lambda payload:r)
    assert live_bridge.execute_live_registered_experiment("E1") == r
    assert live_bridge.execute_live_registered_experiment("E1") == r
    assert len(st.list_results()) == 1

def test_live_bridge_rejects_cross_mode_and_env(monkeypatch,tmp_path):
    st,c,s=setup(tmp_path,mode="fixture"); monkeypatch.setattr(live_bridge,"LIVE_CONTEXT_PATH",c); monkeypatch.setenv("NOVA_RUN_DB","bad")
    with pytest.raises(ValueError): live_bridge.execute_live_registered_experiment("E1")

def test_live_bridge_failure_event(monkeypatch,tmp_path):
    st,c,s=setup(tmp_path); monkeypatch.setattr(live_bridge,"LIVE_CONTEXT_PATH",c)
    monkeypatch.setattr("nova.science_adapter.execute_science_experiment",lambda payload: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(ValueError): live_bridge.execute_live_registered_experiment("E1")
    assert st.list_events("run")[-1].event_type == "tool_failed"
