import json, sqlite3
from scripts import prepare_live_run as prep
def test_prepare_live_run(monkeypatch,tmp_path):
    monkeypatch.setattr(prep,"active_dataset_sha256",lambda:"a"*64)
    context_path=tmp_path/".nova/live_context.json"
    monkeypatch.setattr(prep,"LIVE_CONTEXT_PATH",context_path)
    context=prep.prepare_live_run(tmp_path/"run.sqlite","r1")
    assert context["mode"]=="live"
    assert (tmp_path/"run.sqlite").stat().st_mode&0o777==0o600
    assert (tmp_path/".nova").stat().st_mode&0o777==0o700
    on_disk=json.loads(context_path.read_text())
    assert set(on_disk)=={"schema_version","run_id","mode","db"}
    assert context["dataset_sha256"]=="a"*64
    with sqlite3.connect(str(tmp_path/"run.sqlite")) as db: rows=db.execute("select event_json from events").fetchall()
    events=[json.loads(row[0]) for row in rows]
    assert all(event["mode"]=="live" for event in events)
    assert not any(event["event_type"] in {"selection","result"} for event in events)

def test_prepare_rejects_existing_database(monkeypatch,tmp_path):
    monkeypatch.setattr(prep,"active_dataset_sha256",lambda:"a"*64)
    monkeypatch.setattr(prep,"LIVE_CONTEXT_PATH",tmp_path/".nova/live_context.json")
    db=tmp_path/"run.sqlite"; db.touch()
    import pytest
    with pytest.raises(ValueError): prep.prepare_live_run(db,"r1")
