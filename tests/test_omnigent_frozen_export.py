from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from scripts.run_omnigent_live import _export_frozen_protocol


def _database(path, *, protocol=True, holdout_spec=True):
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE final_protocols (run_id TEXT, frozen_protocol_id TEXT, "
            "protocol_sha256 TEXT, protocol_json TEXT, holdout_experiment_id TEXT)"
        )
        db.execute("CREATE TABLE specs (experiment_id TEXT PRIMARY KEY, spec_json TEXT)")
        if protocol:
            db.execute(
                "INSERT INTO final_protocols VALUES (?,?,?,?,?)",
                ("run-1", "final-1", "hash-1", json.dumps({"schema_version": 1}), "holdout-1"),
            )
        if holdout_spec:
            db.execute(
                "INSERT INTO specs VALUES (?,?)",
                ("holdout-1", json.dumps({"experiment_id": "holdout-1", "split": "holdout"})),
            )


def _export_dir(path):
    path.mkdir()
    (path / "specs.json").write_text(
        json.dumps([{"experiment_id": "discovery-1"}], indent=2) + "\n", encoding="utf-8"
    )
    (path / "manifest.json").write_text(
        json.dumps({"files": {"specs.json": {"sha256": "old", "count": 1}}}) + "\n",
        encoding="utf-8",
    )


def test_export_frozen_protocol_adds_holdout_and_updates_manifest(tmp_path):
    database = tmp_path / "run.sqlite"
    exported = tmp_path / "evidence"
    _database(database)
    _export_dir(exported)

    record = _export_frozen_protocol(exported, database, "run-1")

    assert record["frozen_protocol_id"] == "final-1"
    assert record["holdout_experiment_id"] == "holdout-1"
    specs_bytes = (exported / "specs.json").read_bytes()
    specs = json.loads(specs_bytes)
    assert [item["experiment_id"] for item in specs] == ["discovery-1", "holdout-1"]
    manifest = json.loads((exported / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["specs.json"] == {
        "sha256": hashlib.sha256(specs_bytes).hexdigest(),
        "count": 2,
    }


def test_export_frozen_protocol_fails_closed_when_holdout_spec_is_missing(tmp_path):
    database = tmp_path / "run.sqlite"
    exported = tmp_path / "evidence"
    _database(database, holdout_spec=False)
    _export_dir(exported)

    with pytest.raises(RuntimeError, match="missing holdout Spec"):
        _export_frozen_protocol(exported, database, "run-1")


def test_export_frozen_protocol_returns_none_without_final_protocol(tmp_path):
    database = tmp_path / "run.sqlite"
    exported = tmp_path / "evidence"
    _database(database, protocol=False)
    _export_dir(exported)

    assert _export_frozen_protocol(exported, database, "run-1") is None
