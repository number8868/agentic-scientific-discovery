import json
import os
from pathlib import Path

import pytest

from nova.storage import Storage
import scripts.prepare_h2_fixture as preparer


def test_prepare_creates_canonical_fixture_spec_and_events(tmp_path):
    preparer.CONTEXT_PATH = tmp_path / ".nova" / "context.json"
    db = tmp_path / "h2.sqlite"
    output = preparer.prepare_h2_fixture(db, "run-fixture-01")
    store = Storage(db).initialize()
    spec = store.get_spec(output["experiment_id"])
    events = store.list_events("run-fixture-01")
    assert spec.template.value == "family_screen"
    assert spec.split.value == "discovery"
    assert output["mode"] == "fixture"
    assert [event.event_type for event in events] == ["run_created", "hypothesis_frozen", "selection"]
    assert all(event.mode.value == "fixture" for event in events)
    assert [event.actor for event in events] == ["host", "pi", "pi"]
    context = json.loads(preparer.CONTEXT_PATH.read_text())
    assert set(context) == {"schema_version", "mode", "db", "run_id"}
    assert context == {"schema_version": 1, "mode": "fixture", "db": str(db.resolve()), "run_id": "run-fixture-01"}
    assert os.stat(preparer.CONTEXT_PATH).st_mode & 0o777 == 0o600
    assert os.stat(preparer.CONTEXT_PATH.parent).st_mode & 0o777 == 0o700
    assert os.stat(db).st_mode & 0o077 == 0


def test_rejects_dangerous_and_non_sqlite_targets(tmp_path):
    preparer.CONTEXT_PATH = tmp_path / ".nova" / "context.json"
    with pytest.raises(ValueError):
        preparer.prepare_h2_fixture(Path.home())
    non_sqlite = tmp_path / "not.sqlite"
    non_sqlite.write_text("not sqlite")
    with pytest.raises(ValueError):
        preparer.prepare_h2_fixture(non_sqlite)
    with pytest.raises(ValueError):
        preparer.prepare_h2_fixture(tmp_path / "bad id", "../unsafe")


def test_output_has_no_secret_or_host_and_no_external_process(tmp_path):
    preparer.CONTEXT_PATH = tmp_path / ".nova" / "context.json"
    output = preparer.prepare_h2_fixture(tmp_path / "safe.sqlite", "safe-run")
    text = json.dumps(output)
    assert "token" not in text.lower()
    assert "authorization" not in text.lower()
    assert "https://" not in text.lower()
    assert "databricks_host" not in text.lower()
    assert output["next_command"] == "PATH=.venv-tmux/bin:$PATH .venv-omnigent/bin/omnigent run agents/opensource.yaml"
    assert "next_environment" not in output


def test_context_atomic_overwrite_points_only_to_new_run(tmp_path):
    preparer.CONTEXT_PATH = tmp_path / ".nova" / "context.json"
    first = preparer.prepare_h2_fixture(tmp_path / "one.sqlite", "first-run")
    first_context = preparer.CONTEXT_PATH.read_text()
    second = preparer.prepare_h2_fixture(tmp_path / "two.sqlite", "second-run")
    context = json.loads(preparer.CONTEXT_PATH.read_text())
    assert first_context != preparer.CONTEXT_PATH.read_text()
    assert context["run_id"] == second["run_id"] == "second-run"
    assert context["db"] == str((tmp_path / "two.sqlite").resolve())
    assert "first-run" not in preparer.CONTEXT_PATH.read_text()


def test_context_symlink_is_rejected(tmp_path):
    target = tmp_path / "real-context.json"
    target.write_text("{}")
    directory = tmp_path / ".nova"
    directory.mkdir()
    (directory / "context.json").symlink_to(target)
    preparer.CONTEXT_PATH = directory / "context.json"
    with pytest.raises(ValueError):
        preparer.prepare_h2_fixture(tmp_path / "safe.sqlite", "safe-run")
