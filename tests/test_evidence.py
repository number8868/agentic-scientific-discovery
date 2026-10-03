import hashlib
import json
from pathlib import Path
import pytest
from nova.evidence import export_run
from nova.storage import Storage
from nova.contracts import Event, Mode

def make_db(path):
    s = Storage(path).initialize()
    # Minimal raw rows keep this test independent of science/runtime construction.
    with s._db() as db:
        db.execute("INSERT INTO specs VALUES (?,?,?)", ("E1", json.dumps({"experiment_id":"E1", "spec_sha256":"S1"}), "S1"))
        db.execute("INSERT INTO results VALUES (?,?,?)", ("R1", "E1", json.dumps({"result_id":"R1", "experiment_id":"E1"})))
        db.execute("INSERT INTO reviews VALUES (?,?)", ("R1", json.dumps({"result_id":"R1"})))
    s.append_event("RUN-F", "result_ready", mode=Mode.FIXTURE, payload_ref="E1", event_id="ev1", timestamp_utc="2026-01-01T00:00:00Z")
    return s

def test_export_hashes_json_and_mode(tmp_path):
    db = tmp_path / "x.sqlite"; make_db(db)
    out = export_run(db, "RUN-F", tmp_path / "export")
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["mode"] == "fixture"
    for name, info in manifest["files"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == info["sha256"]
        json.loads((out / name).read_text()) if name != "events.jsonl" else [json.loads(x) for x in (out / name).read_text().splitlines()]
    assert "environment" not in manifest and "secret" not in (out / "events.jsonl").read_text().lower()

def test_dangerous_or_nonempty_output_rejected(tmp_path):
    db = tmp_path / "x.sqlite"; make_db(db)
    with pytest.raises(ValueError): export_run(db, "RUN-F", Path.home())
    occupied = tmp_path / "occupied"; occupied.mkdir(); (occupied / "x").write_text("x")
    with pytest.raises(ValueError): export_run(db, "RUN-F", occupied)
    with pytest.raises(ValueError): export_run(db, "RUN-F", tmp_path / ".." / "escape")


def test_unknown_run_does_not_create_output_directory(tmp_path):
    db = tmp_path / "x.sqlite"; make_db(db)
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="no events"):
        export_run(db, "UNKNOWN", output)
    assert not output.exists()
