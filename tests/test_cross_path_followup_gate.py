from __future__ import annotations

import sqlite3

import pytest

import nova.decision_tools as tools
from nova.contracts import GroupSummary, Result
from nova.storage import Storage


def _prepared_run(tmp_path, monkeypatch):
    db = tmp_path / "run.sqlite"
    store = Storage(db).initialize()
    monkeypatch.setattr(tools, "_read_context", lambda: (db, "cross-path-run"))
    monkeypatch.setattr(tools, "_active_dataset_sha256", lambda: "a" * 64)
    tools.register_initial_plan("family_screen", "bounded primary comparison")
    initial_id = tools.commit_initial_spec("family_screen")
    spec = store.get_spec(initial_id)
    result = Result(
        "primary-result", initial_id, spec.sha256, "a" * 64, "completed", "inconclusive",
        "t0", "t1", 1.0,
        (GroupSummary("oxide", 2, 2, 1, 1.0, 0.5, 0.5, 0.5),),
    )
    store.save_result(result)
    store.append_event("cross-path-run", "result", actor="runner", mode="live", payload_ref=result.result_id)
    tools.submit_live_review(result.result_id, "bounded concern", "threshold_sensitivity")
    return db, store, result


@pytest.mark.parametrize("status", ["registered", "running", "completed", "failed"])
def test_registered_method_audit_closes_legacy_threshold_path(tmp_path, monkeypatch, status):
    db, store, result = _prepared_run(tmp_path, monkeypatch)
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE registered_method_audits (run_id TEXT, status TEXT)")
        connection.execute("INSERT INTO registered_method_audits VALUES (?, ?)", ("cross-path-run", status))

    before = store.list_events("cross-path-run")
    with pytest.raises(ValueError, match="closed after method-audit registration"):
        tools.commit_next_spec(result.result_id, "threshold_sensitivity")

    assert len(store.list_specs()) == 1
    after = store.list_events("cross-path-run")
    assert after == before
    assert not any(event.event_type == "second_selection" for event in after)


def test_legacy_threshold_flow_remains_available_without_audit_table(tmp_path, monkeypatch):
    _db, store, result = _prepared_run(tmp_path, monkeypatch)
    second_id = tools.commit_next_spec(result.result_id, "threshold_sensitivity")

    assert store.get_spec(second_id).parent_result_id == result.result_id
    assert any(event.event_type == "second_selection" for event in store.list_events("cross-path-run"))
