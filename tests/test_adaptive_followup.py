from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nova.adaptive_policy import propose_followups
from nova.contracts import ExperimentSpec, Mode, Result, Split, Template
from nova.storage import Storage
from scripts import run_adaptive_followup as runner


def _seed(tmp_path, monkeypatch):
    db = tmp_path / "live.sqlite"
    run_id = "live-adaptive-test"
    store = Storage(db).initialize()
    spec = ExperimentSpec(
        1, "NOVA-0123456789abcdef", "H1", "d" * 64, Split.DISCOVERY,
        Template.FAMILY_SCREEN, ("oxide", "chalcogenide"), "opt", (1.1, 1.8),
        0.05, 2000, 1729, 120,
    )
    result = Result(
        "result-parent", spec.experiment_id, spec.sha256, spec.dataset_sha256,
        "completed", "inconclusive", "start", "end", 30.0,
        delta=0.1, resampling_interval=(-0.2, 0.3),
    )
    store.register_spec(spec)
    store.save_result(result)
    store.append_event(run_id, "selection", actor="pi", mode=Mode.LIVE,
                       payload_ref=spec.experiment_id)
    store.append_event(run_id, "result", actor="runner", mode=Mode.LIVE,
                       payload_ref=result.result_id)
    monkeypatch.setattr("nova.live_bridge._read_context", lambda: (db, run_id))
    return db, run_id, store, result


def _packet(result, budget=1000):
    return propose_followups(result, remaining_seconds=budget)


def test_stop_persists_choice_and_does_not_call_science_apis(tmp_path, monkeypatch):
    db, run_id, store, result = _seed(tmp_path, monkeypatch)
    packet = _packet(result)
    calls = []
    api = {name: lambda *a, **k: calls.append((name, a, k)) for name in (
        "submit_live_review", "commit_next_spec", "execute_live_registered_experiment",
        "register_method_audit", "execute_method_audit",
    )}
    outcome = runner._record_selection(db, run_id, packet, "stop", "Stop after review", api)
    assert outcome["outcome"] == "stopped"
    assert calls == []
    assert any(event.event_type == "adaptive_followup_selected" for event in store.list_events(run_id))


def test_threshold_path_uses_only_registered_threshold_apis(tmp_path, monkeypatch):
    db, run_id, store, result = _seed(tmp_path, monkeypatch)
    packet = _packet(result)
    calls = []

    def review(**kwargs):
        calls.append(("review", kwargs))
        return {"result_id": kwargs["result_id"]}

    def commit(**kwargs):
        calls.append(("commit", kwargs))
        followup = ExperimentSpec(
            1, "NOVA-next", "H1", "d" * 64, Split.DISCOVERY,
            Template.THRESHOLD_SENSITIVITY, ("oxide", "chalcogenide"), "opt",
            (1.1, 1.8), 0.05, 2000, 1729, 120, "result-parent", "result-parent",
        )
        store.register_spec(followup)
        return followup.experiment_id

    def execute(**kwargs):
        calls.append(("execute", kwargs))
        return SimpleNamespace(experiment_id="NOVA-next", execution_status="completed", error=None)

    api = {"submit_live_review": review, "commit_next_spec": commit,
           "execute_live_registered_experiment": execute}
    outcome = runner._record_selection(db, run_id, packet, "threshold_sensitivity", "Test threshold stability", api)
    assert outcome["outcome"] == "completed"
    assert [x[0] for x in calls] == ["review", "commit", "execute"]


def test_threshold_execution_failure_is_not_reported_as_completed(tmp_path, monkeypatch):
    db, run_id, store, result = _seed(tmp_path, monkeypatch)
    packet = _packet(result)

    def commit(**kwargs):
        followup = ExperimentSpec(
            1, "NOVA-next", "H1", "d" * 64, Split.DISCOVERY,
            Template.THRESHOLD_SENSITIVITY, ("oxide", "chalcogenide"), "opt",
            (1.1, 1.8), 0.05, 2000, 1729, 120, "result-parent", "result-parent",
        )
        store.register_spec(followup)
        return followup.experiment_id

    with pytest.raises(ValueError, match="completed Result"):
        runner._record_selection(db, run_id, packet, "threshold_sensitivity", "Check stability", {
            "submit_live_review": lambda **kwargs: {},
            "commit_next_spec": commit,
            "execute_live_registered_experiment": lambda **kwargs: SimpleNamespace(
                experiment_id="NOVA-next", execution_status="failed", error={"message": "failed"}),
        })


def test_method_path_uses_registered_discovery_audit_api(tmp_path, monkeypatch):
    db, run_id, store, result = _seed(tmp_path, monkeypatch)
    packet = _packet(result)
    calls = []

    def register(parent_result_id):
        calls.append(("register", parent_result_id))
        return {"audit_id": "audit-1", "parent_result_id": parent_result_id}

    def execute(audit_id):
        calls.append(("execute", audit_id))
        return {"result": {"execution_status": "success", "template": "method_sensitivity", "split": "discovery"}}

    outcome = runner._record_selection(db, run_id, packet, "method_sensitivity", "Explore method sensitivity", {
        "register_method_audit": register, "execute_method_audit": execute,
    })
    assert outcome["outcome"] == "completed"
    assert calls == [("register", "result-parent"), ("execute", "audit-1")]


def test_infeasible_or_unoffered_choice_is_rejected_before_persistence(tmp_path, monkeypatch):
    db, run_id, store, result = _seed(tmp_path, monkeypatch)
    packet = _packet(result, budget=0)
    with pytest.raises(ValueError, match="infeasible"):
        runner._record_selection(db, run_id, packet, "threshold_sensitivity", "Try it anyway", {})
    assert not any(event.event_type == "adaptive_followup_selected" for event in store.list_events(run_id))


def test_prior_adaptive_choice_cannot_be_replaced(tmp_path, monkeypatch):
    db, run_id, store, result = _seed(tmp_path, monkeypatch)
    packet = _packet(result)
    runner._record_selection(db, run_id, packet, "stop", "Stop", {})
    with pytest.raises(ValueError, match="already recorded"):
        runner._record_selection(db, run_id, packet, "stop", "Replace", {})


def test_full_orchestration_accepts_fake_choice_and_runs_stop_only(tmp_path, monkeypatch):
    db, run_id, store, result = _seed(tmp_path, monkeypatch)
    outcome = runner.run_adaptive_followup(
        database=db, run_id=run_id, remaining_seconds=100,
        api={}, chooser=lambda packet: ("stop", "Stop after reviewing the uncertainty"),
    )
    assert outcome["selection"]["choice"] == "stop"
    assert outcome["outcome"] == "stopped"
    event_types = [event.event_type for event in store.list_events(run_id)]
    assert "adaptive_followup_decision_started" in event_types
    assert "adaptive_model_choice_received" in event_types
    assert event_types[-1] == "adaptive_followup_completed"
    assert outcome["packet"]["selection_provenance"] == {
        "selector_kind": "injected_test_chooser", "requested_model": None,
        "harness": None, "omnigent_version": None, "tool_config": None,
    }


def test_budget_is_clamped_to_total_timeout_before_feasibility(tmp_path, monkeypatch):
    db, run_id, store, result = _seed(tmp_path, monkeypatch)
    observed = {}

    def chooser(packet):
        observed.update(packet)
        return "stop", "Stop after reviewing the evidence"

    outcome = runner.run_adaptive_followup(
        database=db, run_id=run_id, remaining_seconds=3600,
        api={}, chooser=chooser,
    )
    assert outcome["packet"]["remaining_seconds"] == runner.TOTAL_TIMEOUT_SECONDS == 720
    assert observed["remaining_seconds"] == 720


def test_codex_executor_error_is_reported_safely():
    from omnigent.inner.executor import ExecutorError

    class FailedExecutor:
        async def run_turn(self, **kwargs):
            yield ExecutorError(message="provider denied sk-abcdefghijklmnopqrstuv", retryable=False)

        async def interrupt_session(self, _session_id):
            pass

        async def close_session(self, _session_id):
            pass

        async def close(self):
            pass

    async def invoke():
        with pytest.raises(RuntimeError, match=r"Codex decision call failed: provider denied \[redacted\]") as error:
            await runner._ask_codex(
                {"allowed_choices": ["stop"], "candidate_tests": [{"choice": "stop", "feasibility": True}],
                 "parent_result_id": "result-parent"},
                "gpt-6-luna", 5,
                executor_factory=lambda **_kwargs: FailedExecutor(),
            )
        assert "sk-abcdefghijklmnopqrstuv" not in str(error.value)

    asyncio.run(invoke())
