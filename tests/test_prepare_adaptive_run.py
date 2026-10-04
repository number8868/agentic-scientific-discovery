import json

import pytest

from scripts import prepare_adaptive_run as bootstrap
from scripts import prepare_live_run


def setup(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "runs").mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "ROOT", root)
    context = tmp_path / "context.json"
    monkeypatch.setattr(prepare_live_run, "LIVE_CONTEXT_PATH", context)
    calls = []

    def prepare(database, run_id):
        calls.append(("prepare", database, run_id))
        return {"schema_version": 1, "run_id": run_id, "mode": "live", "db": str(database)}

    def register(template, reason):
        calls.append(("register", template, reason))

    def commit(template):
        calls.append(("commit", template))
        return "E-primary"

    def execute(experiment_id):
        calls.append(("execute", experiment_id))
        return {"result_id": "R-primary", "execution_status": "completed"}

    api = {
        "prepare_live_run": prepare,
        "register_initial_plan": register,
        "commit_initial_spec": commit,
        "execute_live_registered_experiment": execute,
    }
    return root, context, calls, api


def test_bootstrap_seeds_and_executes_primary_with_host_provenance(tmp_path, monkeypatch):
    root, _, calls, api = setup(tmp_path, monkeypatch)
    response = bootstrap.prepare_adaptive_run(root / "runs" / "run.sqlite", "pilot-1", api=api)
    assert [item[0] for item in calls] == ["prepare", "register", "commit", "execute"]
    assert calls[1] == ("register", "family_screen", bootstrap.BASELINE_REASON)
    assert calls[2] == ("commit", "family_screen")
    assert calls[3] == ("execute", "E-primary")
    assert response["result_id"] == "R-primary"
    assert response["primary_role_model_called"] is False
    assert "Omnigent" in response["next_step"]


def test_existing_context_fails_before_preparation(tmp_path, monkeypatch):
    root, context, calls, api = setup(tmp_path, monkeypatch)
    context.write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="context already exists"):
        bootstrap.prepare_adaptive_run(root / "runs" / "run.sqlite", "pilot-1", api=api)
    assert calls == []


def test_existing_context_symlink_fails(tmp_path, monkeypatch):
    root, context, calls, api = setup(tmp_path, monkeypatch)
    target = tmp_path / "somewhere"
    target.write_text("context", encoding="utf-8")
    context.symlink_to(target)
    with pytest.raises(ValueError, match="context already exists"):
        bootstrap.prepare_adaptive_run(root / "runs" / "run.sqlite", "pilot-1", api=api)
    assert calls == []


def test_database_must_be_fresh_under_resolved_runs_root(tmp_path, monkeypatch):
    root, _, calls, api = setup(tmp_path, monkeypatch)
    outside = tmp_path / "outside.sqlite"
    with pytest.raises(ValueError, match="under the repository runs"):
        bootstrap.prepare_adaptive_run(outside, "pilot-1", api=api)
    escaped = root / "runs" / "escape"
    escaped.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="under the repository runs"):
        bootstrap.prepare_adaptive_run(escaped / "run.sqlite", "pilot-1", api=api)
    assert calls == []


def test_existing_database_and_invalid_result_are_rejected(tmp_path, monkeypatch):
    root, _, calls, api = setup(tmp_path, monkeypatch)
    existing = root / "runs" / "old.sqlite"
    existing.touch()
    with pytest.raises(ValueError, match="database already exists"):
        bootstrap.prepare_adaptive_run(existing, "pilot-1", api=api)

    failing_api = dict(api)
    failing_api["execute_live_registered_experiment"] = lambda _experiment_id: {
        "result_id": "R-failed", "execution_status": "failed",
    }
    with pytest.raises(ValueError, match="did not return a completed result"):
        bootstrap.prepare_adaptive_run(root / "runs" / "new.sqlite", "pilot-2", api=failing_api)


def test_cli_prints_result_json(tmp_path, monkeypatch, capsys):
    root, _, _, api = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(bootstrap, "_default_api", lambda: api)
    target = root / "runs" / "cli.sqlite"
    assert bootstrap.main(["--database", str(target), "--run-id", "cli-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["result_id"] == "R-primary"
    assert printed["primary_choice_source"] == "host_seeded_baseline"
