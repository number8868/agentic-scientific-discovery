"""Mock-only tests for the six-role live host; never launch Codex or science."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import types

import pytest

from nova.contracts import ExperimentSpec, GroupSummary, Result, ReviewPacket, Concern, Split, Template
from nova.storage import Storage
from scripts.run_omnigent_live import (
    CODEX_APP_SERVER_OVERRIDES,
    LivePilotHost,
    JsonlAudit,
    MAX_MODEL_TURNS,
    MAX_ROLE_TURNS,
    ROLE_ORDER,
    TOOLS,
    NoToolCallError,
    _consume_role_turn,
    _new_codex_executor,
    _run_role_with_repair,
)


DATASET = "a" * 64


def _spec(experiment_id: str, template: str, parent: str | None = None) -> ExperimentSpec:
    return ExperimentSpec(
        1, experiment_id, "H-001", DATASET, Split.DISCOVERY, Template(template),
        ("oxide", "chalcogenide"), "opt", (1.1, 1.8), 0.05, 2000, 1729, 120,
        parent, parent if parent else None, None,
    )


def _result(spec: ExperimentSpec) -> Result:
    return Result(
        result_id="result-" + spec.experiment_id,
        experiment_id=spec.experiment_id,
        spec_sha256=spec.sha256,
        dataset_sha256=DATASET,
        execution_status="completed",
        scientific_status="inconclusive",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        elapsed_seconds=1,
        groups_summary=(
            GroupSummary("oxide", 20, 18, 8, .9, .44, .2, .6),
            GroupSummary("chalcogenide", 20, 16, 7, .8, .44, .15, .65),
        ),
        delta=0.0,
        resampling_interval=(-.2, .2),
        missingness_interval=(-.4, .4),
        quality_flags=("mock-only",),
    )


class FakeLiveApi:
    def __init__(self, path: Path, run_id: str):
        self.store = Storage(path).initialize()
        self.run_id = run_id
        self.executed: list[str] = []
        self.store.append_event(run_id, "run_created", actor="host", mode="live")
        self.store.append_event(run_id, "objective_registered", actor="host", mode="live")
        self.store.append_event(run_id, "hypothesis_frozen", actor="pi", mode="live")

    def register_initial_plan(self, chosen_template: str, selection_reason: str):
        return {
            "chosen_proposal_id": "proposal-family_screen",
            "selection_reason": selection_reason,
            "candidate_tests": [
                {"proposal_id": "proposal-family_screen", "draft_spec": {"template": "family_screen"}},
                {"proposal_id": "proposal-threshold_sensitivity", "draft_spec": {"template": "threshold_sensitivity"}},
            ],
        }

    def commit_initial_spec(self, chosen_template: str):
        spec = _spec("initial-id", "family_screen")
        self.store.register_spec(spec)
        self.store.append_event(self.run_id, "selection", actor="pi", mode="live", payload_ref=spec.experiment_id)
        return spec.experiment_id

    def execute_live_registered_experiment(self, experiment_id: str):
        self.executed.append(experiment_id)
        spec = self.store.read_spec(experiment_id)
        result = _result(spec)
        self.store.save_result(result)
        self.store.append_event(self.run_id, "result", actor="runner", mode="live", payload_ref=result.result_id)
        return result

    def submit_live_review(self, result_id: str, concern: str, recommended_template: str):
        first = self.store.get_result(result_id)
        review = ReviewPacket(first.experiment_id, result_id,
                              (Concern("protocol_weakness", "medium", (result_id,)),),
                              Template(recommended_template), concern, (result_id,))
        self.store.save_review(review)
        self.store.append_event(self.run_id, "review", actor="skeptic", mode="live", payload_ref=result_id)
        return review.to_dict()

    def commit_next_spec(self, result_id: str, recommended_template: str):
        spec = _spec("threshold-id", "threshold_sensitivity", result_id)
        self.store.register_spec(spec)
        self.store.append_event(self.run_id, "second_selection", actor="pi", mode="live", payload_ref=spec.experiment_id)
        return spec.experiment_id

    def submit_final_review(self, result_id: str, concern: str):
        result = self.store.get_result(result_id)
        review = ReviewPacket(result.experiment_id, result_id,
                              (Concern("final_protocol", "medium", (result_id,)),),
                              None, concern, (result_id,))
        self.store.save_review(review)
        self.store.append_event(self.run_id, "second_review", actor="skeptic", mode="live", payload_ref=result_id)
        return review.to_dict()

    def freeze_final(self, main_result_id: str, followup_result_id: str, explanation: str):
        return {"frozen_protocol_id": "frozen-id", "holdout_experiment_id": "holdout-id",
                "protocol": {"main_result_id": main_result_id, "followup_result_id": followup_result_id,
                              "explanation": explanation}}


def _host(tmp_path: Path) -> tuple[LivePilotHost, FakeLiveApi]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    database = tmp_path / "state.sqlite"
    api = FakeLiveApi(database, "test-run")
    return LivePilotHost(database, "test-run", api=vars_api(api)), api


def vars_api(api: FakeLiveApi):
    return {name: getattr(api, name) for name in (
        "register_initial_plan", "commit_initial_spec", "execute_live_registered_experiment",
        "submit_live_review", "commit_next_spec",
        "submit_final_review", "freeze_final",
    )}


def _call(host: LivePilotHost, role: str, args: dict):
    return asyncio.run(host.handle_tool(role, TOOLS[role]["name"], args))


def _advance_to_first_runner(host: LivePilotHost):
    _call(host, "planner", {"chosen_template": "family_screen", "selection_reason": "Start with the bounded primary comparison."})
    _call(host, "pi_initial", {"chosen_template": "family_screen"})


def _install_fake_executor_sdk(monkeypatch):
    class Event:
        def __init__(self, **values):
            self.__dict__.update(values)

    class FakeConfig:
        def __init__(self, **_values):
            pass

    outer = types.ModuleType("omnigent")
    outer.__path__ = []
    inner = types.ModuleType("omnigent.inner")
    inner.__path__ = []
    sdk_events = types.ModuleType("omnigent.inner.executor")
    sdk_events.ExecutorConfig = FakeConfig
    sdk_events.ExecutorError = type("ExecutorError", (Event,), {})
    sdk_events.ToolCallComplete = type("ToolCallComplete", (Event,), {})
    sdk_events.ToolCallRequest = type("ToolCallRequest", (Event,), {})
    sdk_events.TurnComplete = type("TurnComplete", (Event,), {})
    outer.inner = inner
    inner.executor = sdk_events
    monkeypatch.setitem(sys.modules, "omnigent", outer)
    monkeypatch.setitem(sys.modules, "omnigent.inner", inner)
    monkeypatch.setitem(sys.modules, "omnigent.inner.executor", sdk_events)
    return sdk_events


def test_host_enforces_eight_registered_transitions_and_rejects_reexecution(tmp_path):
    host, api = _host(tmp_path)
    _advance_to_first_runner(host)
    first = _call(host, "runner_first", {"experiment_id": "initial-id"})
    assert first["result_id"] == "result-initial-id"
    _call(host, "skeptic", {"result_id": first["result_id"], "concern": "Coverage and missingness leave the family comparison uncertain.", "recommended_template": "threshold_sensitivity"})
    second = _call(host, "pi_second", {"result_id": first["result_id"], "recommended_template": "threshold_sensitivity"})
    assert second["parent_result_id"] == first["result_id"]
    final = _call(host, "runner_second", {"experiment_id": second["experiment_id"]})
    assert final["result_id"] == "result-threshold-id"
    review = _call(host, "skeptic_final", {"result_id": final["result_id"], "concern": "bounded final concern"})
    assert review["result_id"] == final["result_id"]
    frozen = _call(host, "pi_freeze", {"main_result_id": first["result_id"],
                                        "followup_result_id": final["result_id"], "explanation": "ready"})
    assert frozen["holdout_experiment_id"] == "holdout-id"
    assert host.phase == len(ROLE_ORDER) == 8
    assert host.tool_calls == 8
    assert api.executed == ["initial-id", "threshold-id"]
    with pytest.raises(ValueError, match="tool-call budget exceeded"):
        _call(host, "runner_second", {"experiment_id": "threshold-id"})
    assert api.executed == ["initial-id", "threshold-id"]


def test_host_rejects_unregistered_runner_ids_and_duplicate_arguments(tmp_path):
    host, api = _host(tmp_path)
    _advance_to_first_runner(host)
    with pytest.raises(ValueError, match="selected initial ID"):
        _call(host, "runner_first", {"experiment_id": "attacker-chosen-id"})
    assert host.aborted
    assert api.executed == []

    host2, _ = _host(tmp_path / "second")
    with pytest.raises(ValueError, match="arguments do not match"):
        asyncio.run(host2.handle_tool("planner", "register_initial_plan", {
            "chosen_template": "family_screen",
            "selection_reason": "bounded",
            "extra": "not allowed",
        }))
    assert host2.aborted


def test_final_freeze_requires_second_review(tmp_path):
    host, _api = _host(tmp_path)
    _advance_to_first_runner(host)
    first = _call(host, "runner_first", {"experiment_id": "initial-id"})
    _call(host, "skeptic", {"result_id": first["result_id"], "concern": "bounded", "recommended_template": "threshold_sensitivity"})
    second = _call(host, "pi_second", {"result_id": first["result_id"], "recommended_template": "threshold_sensitivity"})
    followup = _call(host, "runner_second", {"experiment_id": second["experiment_id"]})
    # Simulate the runner having returned control to the final PI step while
    # omitting the required second-review transition.
    host.phase = 7
    with pytest.raises(ValueError, match="final freeze must follow both results and the final review"):
        _call(host, "pi_freeze", {"main_result_id": first["result_id"],
                                   "followup_result_id": followup["result_id"], "explanation": "ready"})
    assert host.frozen is None and host.aborted


def test_initial_result_id_cannot_be_executed_twice(tmp_path):
    host, api = _host(tmp_path)
    _advance_to_first_runner(host)
    _call(host, "runner_first", {"experiment_id": "initial-id"})
    with pytest.raises(ValueError, match="out of role order"):
        _call(host, "runner_first", {"experiment_id": "initial-id"})
    assert host.aborted
    assert api.executed == ["initial-id"]


def test_host_rejects_unregistered_followup_id(tmp_path):
    host, api = _host(tmp_path)
    _advance_to_first_runner(host)
    first = _call(host, "runner_first", {"experiment_id": "initial-id"})
    _call(host, "skeptic", {"result_id": first["result_id"], "concern": "Coverage remains uncertain.", "recommended_template": "threshold_sensitivity"})
    _call(host, "pi_second", {"result_id": first["result_id"], "recommended_template": "threshold_sensitivity"})
    with pytest.raises(ValueError, match="selected follow-up ID"):
        _call(host, "runner_second", {"experiment_id": "invented-threshold-id"})
    assert host.aborted
    assert api.executed == ["initial-id"]


def test_host_rejects_wrong_result_but_accepts_negated_scientific_claim(tmp_path):
    host, _ = _host(tmp_path)
    _advance_to_first_runner(host)
    first = _call(host, "runner_first", {"experiment_id": "initial-id"})
    with pytest.raises(ValueError, match="actual first result"):
        _call(host, "skeptic", {"result_id": "not-the-result", "concern": "The interval crosses zero.", "recommended_template": "threshold_sensitivity"})
    assert host.aborted

    host2, _ = _host(tmp_path / "second")
    _advance_to_first_runner(host2)
    first2 = _call(host2, "runner_first", {"experiment_id": "initial-id"})
    review = _call(host2, "skeptic", {
        "result_id": first2["result_id"],
        "concern": "This result cannot prove a general family effect; threshold sensitivity may clarify robustness.",
        "recommended_template": "threshold_sensitivity",
    })
    assert review["result_id"] == first2["result_id"]
    assert not host2.aborted


@pytest.mark.parametrize("concern", ["   ", "x" * 1001])
def test_host_rejects_empty_or_oversized_review_concerns(tmp_path, concern):
    host, _ = _host(tmp_path)
    _advance_to_first_runner(host)
    first = _call(host, "runner_first", {"experiment_id": "initial-id"})
    with pytest.raises(ValueError, match="bounded and non-empty"):
        _call(host, "skeptic", {
            "result_id": first["result_id"],
            "concern": concern,
            "recommended_template": "threshold_sensitivity",
        })
    assert host.aborted


def test_runner_without_tool_call_records_observation_and_fails_once(tmp_path, monkeypatch):
    sdk_events = _install_fake_executor_sdk(monkeypatch)

    class FakeExecutor:
        def __init__(self):
            self.tool_schema = None

        async def run_turn(self, *, tools, **_kwargs):
            self.tool_schema = tools[0]
            yield sdk_events.TurnComplete(
                response="I finished without invoking the function.",
                usage={"input_tokens": 19, "output_tokens": 7, "total_tokens": 26},
            )

        async def close_session(self, _session_id):
            return None

        async def interrupt_session(self, _session_id):
            return True

    host, api = _host(tmp_path)
    _advance_to_first_runner(host)
    executor = FakeExecutor()
    audit_path = tmp_path / "audit.jsonl"
    audit = JsonlAudit(audit_path)
    try:
        with pytest.raises(NoToolCallError, match="completed without calling"):
            asyncio.run(_consume_role_turn(executor, host, audit, "runner_first", 3, 2))
    finally:
        audit.close()

    assert executor.tool_schema["parameters"]["properties"]["experiment_id"]["enum"] == ["initial-id"]
    assert '"experiment_id": "initial-id"' in host.context_for("runner_first")
    assert api.executed == []
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    observed = next(record for record in records if record["event"] == "ModelTurnObserved")
    assert observed["status"] == "no_tool_call"
    assert observed["request_count"] == 0 and observed["complete_count"] == 0
    assert observed["response_summary"] == "I finished without invoking the function."
    assert observed["usage"]["input_tokens"] == 19
    assert not host.aborted


def test_role_gets_one_repair_after_clean_no_tool_reply(tmp_path, monkeypatch):
    sdk_events = _install_fake_executor_sdk(monkeypatch)

    class FakeExecutor:
        def __init__(self):
            self.calls = []
            self._tool_executor = None

        async def run_turn(self, *, messages, tools, **_kwargs):
            self.calls.append({"messages": messages, "tools": tools})
            if len(self.calls) == 1:
                yield sdk_events.TurnComplete(
                    response="ACK, the bounded plan is ready.",
                    usage={"input_tokens": 11, "output_tokens": 2, "total_tokens": 13},
                )
                return
            tool = tools[0]
            args = {"chosen_template": "family_screen", "selection_reason": "Required bounded initial comparison."}
            yield sdk_events.ToolCallRequest(name=tool["name"], args=args, metadata={"call_id": "call-2"})
            result = await self._tool_executor(tool["name"], args)
            yield sdk_events.ToolCallComplete(name=tool["name"], status="success", result=result,
                                               error=None, metadata={"call_id": "call-2"})
            yield sdk_events.TurnComplete(
                response="Plan registered.",
                usage={"input_tokens": 16, "output_tokens": 3, "total_tokens": 19},
            )

        async def close_session(self, _session_id):
            return None

        async def interrupt_session(self, _session_id):
            return True

    host, _api = _host(tmp_path)
    executor = FakeExecutor()
    audit_path = tmp_path / "repair-audit.jsonl"
    audit = JsonlAudit(audit_path)
    try:
        observed, next_turn = asyncio.run(
            _run_role_with_repair(executor, host, audit, "planner", 1, 1, 2)
        )
    finally:
        audit.close()

    assert len(executor.calls) == 2
    assert next_turn == 3
    assert observed["turn"] == 2 and observed["role_turn"] == 1
    assert observed["role_attempt"] == 2 and observed["repair_attempt"] is True
    assert host.phase == 1 and host.tool_calls == 1 and not host.aborted
    assert MAX_ROLE_TURNS == len(ROLE_ORDER) == 8
    assert MAX_MODEL_TURNS == 16 == 2 * MAX_ROLE_TURNS
    retry_prompt = executor.calls[1]["messages"][0]["content"]
    assert "REPAIR REQUIRED" in retry_prompt
    assert "register_initial_plan" in retry_prompt
    assert '{"chosen_template":"family_screen"' in retry_prompt
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    attempts = [record for record in records if record["event"] == "ModelTurnObserved"]
    assert [record["status"] for record in attempts] == ["no_tool_call", "success"]
    assert [record["usage"]["total_tokens"] for record in attempts] == [13, 19]
    assert any(record["event"] == "NoToolCallRepairScheduled" for record in records)


def test_role_does_not_repair_after_tool_callback_failure(tmp_path, monkeypatch):
    sdk_events = _install_fake_executor_sdk(monkeypatch)

    class FakeExecutor:
        def __init__(self):
            self.call_count = 0
            self._tool_executor = None

        async def run_turn(self, *, tools, **_kwargs):
            self.call_count += 1
            tool = tools[0]
            args = {"chosen_template": "family_screen", "selection_reason": "bounded", "extra": "forbidden"}
            yield sdk_events.ToolCallRequest(name=tool["name"], args=args, metadata={"call_id": "bad-call"})
            await self._tool_executor(tool["name"], args)

        async def close_session(self, _session_id):
            return None

        async def interrupt_session(self, _session_id):
            return True

    host, _api = _host(tmp_path)
    executor = FakeExecutor()
    audit_path = tmp_path / "failure-audit.jsonl"
    audit = JsonlAudit(audit_path)
    try:
        with pytest.raises(ValueError, match="arguments do not match"):
            asyncio.run(_run_role_with_repair(executor, host, audit, "planner", 1, 1, 2))
    finally:
        audit.close()

    assert executor.call_count == 1
    assert host.aborted
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    attempts = [record for record in records if record["event"] == "ModelTurnObserved"]
    assert len(attempts) == 1 and attempts[0]["status"] == "executor_error"
    assert not any(record["event"] == "NoToolCallRepairScheduled" for record in records)


def test_codex_overrides_are_pinned_and_applied_before_startup(tmp_path, monkeypatch):
    class FakeCodexExecutor:
        def __init__(self, **_kwargs):
            self._codex_config_overrides = []
            self._env = {}
            self.started_with = None

        def start_app_server(self):
            self.started_with = tuple(self._codex_config_overrides)

    host_path = tmp_path / "codex-code-mode-host"
    host_path.write_text("mock host", encoding="utf-8")
    host_path.chmod(0o755)
    monkeypatch.setenv("CODEX_CODE_MODE_HOST_PATH", str(host_path))

    executor = _new_codex_executor(FakeCodexExecutor, "/tmp/mock-cwd", "0.16.0")
    assert tuple(executor._codex_config_overrides) == CODEX_APP_SERVER_OVERRIDES
    assert executor._env["CODEX_CODE_MODE_HOST_PATH"] == str(host_path.resolve())
    assert executor.started_with is None
    executor.start_app_server()
    assert executor.started_with == CODEX_APP_SERVER_OVERRIDES
    with pytest.raises(RuntimeError, match="requires omnigent==0.16.0"):
        _new_codex_executor(FakeCodexExecutor, "/tmp/mock-cwd", "0.17.0")


def test_skeptic_prompt_distinguishes_pass_rate_from_missingness():
    host = LivePilotHost(Path("/tmp/mock.sqlite"), "metric-context", api={})
    host.first_result = {"result_id": "first-result"}
    host._stored_result_and_payload = lambda _result_id: (
        {"groups_summary": [
            {"group": "oxide", "coverage": 1.0},
            {"group": "chalcogenide", "coverage": 1.0},
        ]},
        {"delta": 0.1},
    )
    prompt = host.context_for("skeptic")
    assert "joint inclusive bandgap-plus-ehull screen pass rate" in prompt
    assert "not missingness metrics" in prompt
    assert "oxide=100.0%, chalcogenide=100.0%" in prompt
