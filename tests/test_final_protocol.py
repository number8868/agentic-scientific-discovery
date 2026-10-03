import pytest

import nova.decision_tools as tools
from nova.contracts import GroupSummary, Result
from nova.storage import Storage


def setup_run(tmp_path, monkeypatch, run_id="run-final"):
    db = tmp_path / "final.sqlite"
    store = Storage(db).initialize()
    monkeypatch.setattr(tools, "_read_context", lambda: (db, run_id))
    monkeypatch.setattr(tools, "_active_dataset_sha256", lambda: "a" * 64)
    return db, store, run_id


def result(store, spec, result_id, status="completed"):
    r = Result(result_id, spec.experiment_id, spec.sha256, spec.dataset_sha256,
               status, None if status != "completed" else "inconclusive",
               "t0", "t1", 1.0, (), error=None if status == "completed" else {"type": "failed"})
    store.save_result(r)
    return r


def two_rounds(tmp_path, monkeypatch):
    _, store, run_id = setup_run(tmp_path, monkeypatch)
    tools.register_initial_plan("family_screen", "bounded")
    first_id = tools.commit_initial_spec("family_screen")
    first = result(store, store.get_spec(first_id), "first")
    store.append_event(run_id, "result", actor="runner", mode="live", payload_ref=first.result_id)
    tools.submit_live_review(first.result_id, "threshold needs checking", "threshold_sensitivity")
    second_id = tools.commit_next_spec(first.result_id, "threshold_sensitivity")
    second = result(store, store.get_spec(second_id), "second")
    store.append_event(run_id, "result", actor="runner", mode="live", payload_ref=second.result_id)
    return store, first, second


def test_freeze_requires_second_review_and_creates_closed_holdout(tmp_path, monkeypatch):
    store, first, second = two_rounds(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        tools.freeze_final(first.result_id, second.result_id)
    review = tools.submit_final_review(second.result_id, "freeze the preregistered protocol")
    assert review["recommended_template"] is None
    frozen = tools.freeze_final(first.result_id, second.result_id, "bounded final validation")
    holdout = store.get_spec(frozen["holdout_experiment_id"])
    followup = store.get_spec(second.experiment_id)
    assert holdout.split.value == "holdout"
    assert holdout.template.value == "holdout_validation"
    assert holdout.frozen_protocol_id == frozen["frozen_protocol_id"]
    assert holdout.gap_window_ev == followup.gap_window_ev
    assert holdout.ehull_max_ev_atom == followup.ehull_max_ev_atom
    assert holdout.experiment_id not in {r.experiment_id for r in store.list_results()}
    assert store.list_events("run-final")[-1].timestamp_utc


def test_failed_second_result_cannot_freeze(tmp_path, monkeypatch):
    _, store, run_id = setup_run(tmp_path, monkeypatch)
    tools.register_initial_plan("family_screen", "bounded")
    first_id = tools.commit_initial_spec("family_screen")
    first = result(store, store.get_spec(first_id), "first")
    store.append_event(run_id, "result", actor="runner", mode="live", payload_ref="first")
    tools.submit_live_review("first", "follow up", "threshold_sensitivity")
    second_id = tools.commit_next_spec("first", "threshold_sensitivity")
    second = result(store, store.get_spec(second_id), "failed", "failed")
    store.append_event(run_id, "result", actor="runner", mode="live", payload_ref="failed")
    with pytest.raises(ValueError):
        tools.submit_final_review(second.result_id, "not eligible")


def test_cross_run_result_is_rejected(tmp_path, monkeypatch):
    store, first, second = two_rounds(tmp_path, monkeypatch)
    tools.submit_final_review(second.result_id, "ready")
    monkeypatch.setattr(tools, "_read_context", lambda: (store.path, "other-run"))
    with pytest.raises(ValueError):
        tools.freeze_final(first.result_id, second.result_id)


def test_cross_run_final_review_cannot_occupy_review_slot(tmp_path, monkeypatch):
    store, _, second = two_rounds(tmp_path, monkeypatch)
    monkeypatch.setattr(tools, "_read_context", lambda: (store.path, "other-run"))
    with pytest.raises(ValueError):
        tools.submit_final_review(second.result_id, "foreign")
    assert store.get_review(second.result_id) is None
    monkeypatch.setattr(tools, "_read_context", lambda: (store.path, "run-final"))
    review = tools.submit_final_review(second.result_id, "native")
    assert review["result_id"] == second.result_id


def test_freeze_is_immutable_and_repeat_fails(tmp_path, monkeypatch):
    store, first, second = two_rounds(tmp_path, monkeypatch)
    tools.submit_final_review(second.result_id, "ready")
    frozen = tools.freeze_final(first.result_id, second.result_id, "one")
    with pytest.raises(ValueError):
        tools.freeze_final(first.result_id, second.result_id, "changed")
    assert store.get_final_protocol("run-final")["explanation"] == "one"
