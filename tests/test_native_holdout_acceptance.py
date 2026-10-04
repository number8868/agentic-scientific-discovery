"""Synthetic end-to-end compatibility checks for the native A-gate adapter.

Trusted native scope and trace provenance are deliberately stubbed here, and
the holdout worker returns the existing canonical synthetic Result. These
tests exercise the real frozen-run SQLite gate; they do not authorize or prove
any model, real-data, or native provenance execution.
"""

import sqlite3
import time

import pytest

from nova import adaptive_agent_tools, holdout_bridge, native_holdout_tools
from nova.contracts import ExperimentSpec, Result
from nova.process_control import WorkerResult
from test_holdout_bridge import (
    _allow_worker,
    _holdout_id,
    _raw_science,
    _setup_run,
)


def _install_synthetic_scope(monkeypatch, state, *, remaining_seconds=None,
                             deadline_factory=None):
    real_monotonic = time.monotonic
    if deadline_factory is None:
        deadline_factory = lambda: real_monotonic() + remaining_seconds

    def trusted_scope(experiment_id):
        assert experiment_id == _holdout_id(state)
        return (state["db"], state["run_id"], deadline_factory(),
                state["db"].parent / "synthetic-native-trace.jsonl")

    monkeypatch.setattr(native_holdout_tools, "_trusted_scope", trusted_scope)
    monkeypatch.setattr(
        adaptive_agent_tools, "_read_bound_context",
        lambda: (state["db"], state["run_id"]),
    )
    monkeypatch.setattr(adaptive_agent_tools, "record_native_trace", lambda *a, **k: None)
    return real_monotonic


def _gate_hooks():
    return (
        holdout_bridge._claim,
        holdout_bridge._controller_factory,
        holdout_bridge._persist_success,
    )


def _assert_gate_hooks(expected):
    assert _gate_hooks() == expected


def _claim_rows(db_path, run_id, experiment_id):
    with sqlite3.connect(db_path) as db:
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("holdout_bridge_claims",),
        ).fetchone()
        if table is None:
            return []
        return db.execute(
            "SELECT state, result_id FROM holdout_bridge_claims "
            "WHERE run_id=? AND holdout_experiment_id=?",
            (run_id, experiment_id),
        ).fetchall()


@pytest.mark.parametrize(
    "main_elapsed,followup_elapsed,native_remaining,expected_deadline",
    [
        (2.0, 3.0, 300.0, 120.0),  # A's worker cap is tighter than both budgets.
        (2.0, 3.0, 8.0, 8.0),      # B's original deadline is tighter than A's.
        (179.0, 176.0, 8.0, 5.0),  # A's aggregate discovery budget is tighter.
    ],
)
def test_native_adapter_runs_real_a_gate_with_sqlite_claim_and_nested_deadlines(
    monkeypatch, tmp_path, main_elapsed, followup_elapsed,
    native_remaining, expected_deadline,
):
    elapsed_by_template = {
        "family_screen": main_elapsed,
        "threshold_sensitivity": followup_elapsed,
    }

    def synthetic_discovery_result(spec, elapsed, template):
        raw = _raw_science(spec, elapsed, template)
        raw["elapsed_seconds"] = elapsed_by_template[template]
        return raw

    state = _setup_run(tmp_path, monkeypatch, raw_builder=synthetic_discovery_result)
    worker_calls = _allow_worker(monkeypatch)
    _install_synthetic_scope(monkeypatch, state, remaining_seconds=native_remaining)
    observed_deadlines = []

    class RecordingInlineController:
        def __init__(self, registered):
            self.registered = registered

        def run(self, name, args=(), kwargs=None, *, deadline_seconds):
            observed_deadlines.append(deadline_seconds)
            return WorkerResult(self.registered[name](*args, **(kwargs or {})), 1)

    monkeypatch.setattr(holdout_bridge, "_controller_factory", RecordingInlineController)
    original_hooks = _gate_hooks()
    holdout_id = _holdout_id(state)

    result = native_holdout_tools.execute_frozen_native_holdout(holdout_id)

    assert result["experiment_id"] == holdout_id
    assert result["execution_status"] == "completed"
    assert len(worker_calls) == 1
    assert len(observed_deadlines) == 1
    assert observed_deadlines[0] <= expected_deadline
    if expected_deadline == 120.0:
        assert observed_deadlines[0] == 120.0
    else:
        assert observed_deadlines[0] > expected_deadline - 0.5

    rows = _claim_rows(state["db"], state["run_id"], holdout_id)
    assert len(rows) == 1
    assert rows[0] == ("succeeded", result["result_id"])
    stored = next(item for item in state["store"].list_results()
                  if item.experiment_id == holdout_id)
    assert isinstance(stored, Result)
    assert stored.to_dict() == result
    assert [event.event_type for event in state["store"].list_events(state["run_id"])[-2:]] == [
        "holdout_running", "holdout_result",
    ]
    _assert_gate_hooks(original_hooks)


def test_native_deadline_expired_before_real_claim_leaves_sqlite_unclaimed(
    monkeypatch, tmp_path,
):
    state = _setup_run(tmp_path, monkeypatch)
    worker_calls = _allow_worker(monkeypatch)
    _install_synthetic_scope(monkeypatch, state, deadline_factory=lambda: time.monotonic() - 1)
    original_hooks = _gate_hooks()

    with pytest.raises(TimeoutError, match="deadline"):
        native_holdout_tools.execute_frozen_native_holdout(_holdout_id(state))

    assert _claim_rows(state["db"], state["run_id"], _holdout_id(state)) == []
    assert worker_calls == []
    _assert_gate_hooks(original_hooks)


@pytest.mark.parametrize(
    "tamper,expected_error",
    [
        ("frozen", "frozen protocol identity or hash"),
        ("spec", "registered holdout spec differs"),
    ],
)
def test_native_adapter_keeps_a_frozen_and_registered_spec_lineage_checks(
    monkeypatch, tmp_path, tamper, expected_error,
):
    state = _setup_run(tmp_path, monkeypatch)
    holdout_id = _holdout_id(state)
    if tamper == "frozen":
        with sqlite3.connect(state["db"]) as db:
            db.execute(
                "UPDATE final_protocols SET frozen_protocol_id=? WHERE run_id=?",
                ("NOVA-FINAL-" + "f" * 16, state["run_id"]),
            )
    else:
        registered = state["store"].read_spec(holdout_id)
        changed = ExperimentSpec(
            registered.schema_version, registered.experiment_id,
            registered.hypothesis_id, registered.dataset_sha256,
            registered.split, registered.template, registered.groups,
            registered.bandgap_method, registered.gap_window_ev,
            registered.ehull_max_ev_atom, registered.bootstrap_repeats,
            registered.seed, registered.timeout_seconds,
            registered.parent_result_id, registered.review_id,
            "NOVA-FINAL-" + "e" * 16,
        )
        with sqlite3.connect(state["db"]) as db:
            db.execute(
                "UPDATE specs SET spec_json=?, spec_sha256=? WHERE experiment_id=?",
                (changed.to_json(), changed.sha256, holdout_id),
            )

    worker_calls = _allow_worker(monkeypatch)
    _install_synthetic_scope(monkeypatch, state, remaining_seconds=60.0)
    original_hooks = _gate_hooks()

    with pytest.raises(ValueError, match=expected_error):
        native_holdout_tools.execute_frozen_native_holdout(holdout_id)

    assert worker_calls == []
    assert _claim_rows(state["db"], state["run_id"], holdout_id) == []
    _assert_gate_hooks(original_hooks)


def test_expiry_before_real_persist_marks_actual_claim_failed_and_prevents_retry(
    monkeypatch, tmp_path,
):
    state = _setup_run(tmp_path, monkeypatch)
    worker_calls = _allow_worker(monkeypatch)
    holdout_id = _holdout_id(state)
    deadline = 1.0
    _install_synthetic_scope(monkeypatch, state, deadline_factory=lambda: deadline)
    original_hooks = _gate_hooks()

    real_monotonic = time.monotonic
    fake_clock = {"now": 0.0}
    monkeypatch.setattr(native_holdout_tools.time, "monotonic", lambda: fake_clock["now"])
    original_validate = holdout_bridge._validate_holdout_result

    def validate_then_expire(*args, **kwargs):
        result = original_validate(*args, **kwargs)
        fake_clock["now"] = deadline + 0.1
        return result

    # Run A's real canonical validation, then expire before its real persist hook.
    monkeypatch.setattr(holdout_bridge, "_validate_holdout_result", validate_then_expire)
    with pytest.raises(ValueError, match="live holdout execution failed"):
        native_holdout_tools.execute_frozen_native_holdout(holdout_id)
    assert _gate_hooks() == original_hooks
    monkeypatch.setattr(holdout_bridge, "_validate_holdout_result", original_validate)

    rows = _claim_rows(state["db"], state["run_id"], holdout_id)
    assert len(rows) == 1
    assert rows[0] == ("failed", None)
    assert not any(item.experiment_id == holdout_id for item in state["store"].list_results())
    assert len(worker_calls) == 1

    # Restore the real clock and give the adapter a fresh synthetic deadline:
    # A's durable failed claim must still reject another worker attempt.
    monkeypatch.setattr(native_holdout_tools.time, "monotonic", real_monotonic)
    _install_synthetic_scope(monkeypatch, state, remaining_seconds=60.0)
    with pytest.raises(ValueError, match="already attempted"):
        native_holdout_tools.execute_frozen_native_holdout(holdout_id)

    assert len(worker_calls) == 1
    assert _claim_rows(state["db"], state["run_id"], holdout_id) == [("failed", None)]
    _assert_gate_hooks(original_hooks)
