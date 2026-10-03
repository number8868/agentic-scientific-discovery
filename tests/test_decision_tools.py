import json

import pytest

from nova.contracts import GroupSummary, Result
from nova.storage import Storage
import nova.decision_tools as tools


def setup_run(tmp_path, monkeypatch):
    db = tmp_path / "run.sqlite"
    store = Storage(db).initialize()
    monkeypatch.setattr(tools, "_read_context", lambda: (db, "live-run-01"))
    monkeypatch.setattr(tools, "_active_dataset_sha256", lambda: "a" * 64)
    return db, store


def add_result(store, experiment_id, spec_sha):
    result = Result("result-1", experiment_id, spec_sha, "a" * 64, "completed", "inconclusive", "t0", "t1", 1.0,
                    (GroupSummary("oxide", 2, 2, 1, 1.0, 0.5, 0.5, 0.5),))
    store.save_result(result)
    return result


def test_plan_pi_review_followup_state_order(tmp_path, monkeypatch):
    db, store = setup_run(tmp_path, monkeypatch)
    packet = tools.register_initial_plan("family_screen", "primary protocol first")
    assert len(packet["candidate_tests"]) == 2
    initial_id = tools.commit_initial_spec("family_screen")
    spec = store.get_spec(initial_id)
    result = add_result(store, initial_id, spec.sha256)
    review = tools.submit_live_review(result.result_id, "threshold may affect ordering", "threshold_sensitivity")
    assert review["recommended_template"] == "threshold_sensitivity"
    second_id = tools.commit_next_spec(result.result_id, "threshold_sensitivity")
    assert store.get_spec(second_id).parent_result_id == result.result_id
    assert [event.actor for event in store.list_events("live-run-01")] == ["planner", "pi", "skeptic", "pi"]


def test_rejects_unbounded_choices_and_bad_references(tmp_path, monkeypatch):
    db, store = setup_run(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        tools.register_initial_plan("gap_window_sensitivity", "no")
    tools.register_initial_plan("family_screen", "ok")
    with pytest.raises(ValueError):
        tools.commit_initial_spec("threshold_sensitivity")
    initial_id = tools.commit_initial_spec("family_screen")
    with pytest.raises(ValueError):
        tools.submit_live_review("not-stored", "concern", "threshold_sensitivity")
    spec = store.get_spec(initial_id)
    result = add_result(store, initial_id, spec.sha256)
    with pytest.raises(ValueError):
        tools.submit_live_review(result.result_id, "same", "family_screen")


def test_actor_and_path_are_host_controlled(tmp_path, monkeypatch):
    db, store = setup_run(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        tools.register_initial_plan("threshold_sensitivity", "bounded sensitivity")
    packet = tools.register_initial_plan("family_screen", "bounded primary")
    assert all("path" not in p["draft_spec"] for p in packet["candidate_tests"])
    tools.commit_initial_spec("family_screen")
    events = store.list_events("live-run-01")
    assert all(event.actor in {"planner", "pi", "skeptic", "host"} for event in events)
    assert all("/" not in (event.payload_ref or "") for event in events)


def test_context_loader_contract_is_the_only_location_source(tmp_path, monkeypatch):
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"schema_version": 1, "mode": "live", "db": str(tmp_path / "x.sqlite"), "run_id": "x"}))
    monkeypatch.setattr(tools, "_read_context", lambda: (tmp_path / "x.sqlite", "x"))
    monkeypatch.setattr(tools, "_active_dataset_sha256", lambda: "b" * 64)
    with pytest.raises(ValueError):
        tools.commit_initial_spec("family_screen")
