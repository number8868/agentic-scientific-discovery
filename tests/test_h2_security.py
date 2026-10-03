import json
import os
import pytest
from nova import omnigent_bridge
from nova.omnigent_bridge import execute_fixture_registered_experiment

def context(path, db, **extra):
    value = {"schema_version": 1, "mode": "fixture", "db": str(db), "run_id": "r"}
    value.update(extra); path.write_text(json.dumps(value)); path.chmod(0o600)

def test_context_rejects_unknown_and_env_pollution(tmp_path, monkeypatch):
    db = tmp_path / "db"; db.write_bytes(b""); db.chmod(0o600)
    c = tmp_path / "context"; context(c, db, unexpected=1)
    monkeypatch.setattr(omnigent_bridge, "CONTEXT_PATH", c)
    monkeypatch.setenv("NOVA_RUN_DB", str(db)); monkeypatch.setenv("NOVA_RUN_ID", "r")
    with pytest.raises(ValueError): execute_fixture_registered_experiment("x")

def test_context_rejects_permissions_and_symlink(tmp_path, monkeypatch):
    db = tmp_path / "db"; db.write_bytes(b""); db.chmod(0o666)
    c = tmp_path / "context"; context(c, db); monkeypatch.setattr(omnigent_bridge, "CONTEXT_PATH", c)
    with pytest.raises(ValueError): execute_fixture_registered_experiment("x")
    db.chmod(0o600); target = tmp_path / "target"; target.write_bytes(c.read_bytes()); target.chmod(0o600)
    c.unlink(); c.symlink_to(target)
    with pytest.raises(ValueError): execute_fixture_registered_experiment("x")
