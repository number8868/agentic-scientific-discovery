import inspect
import os
import sqlite3
from pathlib import Path

import pytest

from nova.omnigent_bridge import execute_fixture_registered_experiment
from scripts.prepare_h2_fixture import prepare_h2_fixture


def prepared(tmp_path, run_id="run-a"):
    info = prepare_h2_fixture(tmp_path / (run_id + ".sqlite"), run_id)
    return Path(info["db"]), info["run_id"], info["experiment_id"]


def env(db, run):
    os.environ["NOVA_RUN_DB"] = str(db)
    os.environ["NOVA_RUN_ID"] = run


def test_public_tool_signature_is_experiment_id_only():
    params = list(inspect.signature(execute_fixture_registered_experiment).parameters.values())
    assert [p.name for p in params] == ["experiment_id"]
    assert all(p.default is inspect.Parameter.empty for p in params)


def test_env_cannot_select_executor_or_module(tmp_path, monkeypatch):
    db, run, experiment = prepared(tmp_path)
    env(db, run)
    monkeypatch.setenv("NOVA_EXECUTOR", "os.system")
    monkeypatch.setenv("NOVA_EXECUTOR_MODULE", "attacker")
    result = execute_fixture_registered_experiment(experiment)
    assert "fixture" in result.quality_flags


@pytest.mark.parametrize("mode", ["live", "replay"])
def test_live_and_replay_events_are_rejected(tmp_path, mode):
    db, run, experiment = prepared(tmp_path)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE events SET event_json=replace(event_json, '\"mode\":\"fixture\"', '\"mode\":\"%s\"') WHERE run_id=?" % mode, (run,))
    env(db, run)
    with pytest.raises(ValueError, match="authorized|fixture"):
        execute_fixture_registered_experiment(experiment)


def test_selection_must_belong_to_current_run(tmp_path):
    db, _, experiment = prepared(tmp_path, "run-a")
    env(db, "run-never-selected")
    with pytest.raises(ValueError):
        execute_fixture_registered_experiment(experiment)


def test_other_run_registration_cannot_execute(tmp_path):
    db, run_a, experiment = prepared(tmp_path, "run-a")
    # Same database, but the only selection is associated with run-a.
    env(db, "run-b")
    with pytest.raises(ValueError):
        execute_fixture_registered_experiment(experiment)


def test_missing_context_fails_closed_and_does_not_echo_secret(tmp_path, monkeypatch):
    db, run, experiment = prepared(tmp_path)
    secret = "DATABRICKS_TOKEN=do-not-print"
    monkeypatch.delenv("NOVA_RUN_DB", raising=False)
    monkeypatch.delenv("NOVA_RUN_ID", raising=False)
    monkeypatch.setenv("DATABRICKS_TOKEN", secret)
    with pytest.raises(ValueError) as caught:
        execute_fixture_registered_experiment(experiment)
    assert secret not in str(caught.value)
    monkeypatch.setenv("NOVA_RUN_DB", str(db))
    monkeypatch.delenv("NOVA_RUN_ID", raising=False)
    with pytest.raises(ValueError):
        execute_fixture_registered_experiment(experiment)


def test_fixture_result_cannot_be_live_and_repeat_is_identical(tmp_path):
    db, run, experiment = prepared(tmp_path)
    env(db, run)
    first = execute_fixture_registered_experiment(experiment)
    second = execute_fixture_registered_experiment(experiment)
    assert first.to_dict() == second.to_dict()
    assert "fixture" in first.quality_flags
    assert "live" not in first.quality_flags
