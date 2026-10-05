import asyncio
import argparse
import json
from pathlib import Path
import sys
import types

import pytest

from nova import benchmark_quality
from scripts import run_quality_benchmark as runner


def test_parser_requires_exact_output_shape_and_scalar_answers():
    good = {"answers": {"q1": 2.0, "q2": None}, "action": "stop", "citations": ["R1"]}
    assert runner._parse_decision(json.dumps(good)) == good
    with pytest.raises(ValueError):
        runner._parse_decision('{"answers":{},"action":"stop","citations":[],"rubric":{}}')
    with pytest.raises(ValueError):
        runner._parse_decision('{"answers":{"q":[]},"action":"stop","citations":[]}')
    with pytest.raises(ValueError):
        runner._parse_decision('{"answers":{"q":NaN},"action":"stop","citations":[]}')


def test_visible_packet_keeps_rubric_out_of_model_input():
    case = benchmark_quality.load_corpus()["cases"][0]
    packet = benchmark_quality.visible_packet(case)
    assert "rubric" not in packet
    assert set(packet) == {"id", "packet"}


def test_turn_schedule_is_three_equal_budget_turns_for_primary_arms():
    for name in ("single_self_review", "multi_role"):
        assert len({"single_self_review": ["single_initial", "single_critique", "single_final"],
                    "multi_role": ["Planner", "Skeptic", "PI"]}[name]) == 3
    assert runner.MAX_TOKENS == 1200
    assert runner.REASONING_EFFORT == "medium"
    assert runner._tools() == []
    assert runner._role_frame("single_self_review", "single_initial") == runner._role_frame("multi_role", "Planner")
    assert runner._role_frame("single_self_review", "single_critique") == runner._role_frame("multi_role", "Skeptic")
    assert runner._role_frame("single_self_review", "single_final") == runner._role_frame("multi_role", "PI")
    for arm, role in [("single_once", "single"), ("single_self_review", "single_initial"),
                      ("single_self_review", "single_critique"), ("single_self_review", "single_final"),
                      ("multi_role", "Planner"), ("multi_role", "Skeptic"), ("multi_role", "PI")]:
        assert isinstance(runner._role_frame(arm, role), str)


def test_fake_sdk_accepts_every_role_and_closes_fresh_session(monkeypatch):
    class TurnComplete:
        continue_turn = False
        usage = None
        response = '{"answers":{},"action":"stop","citations":[]}'
    class ExecutorConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
    class FakeExecutor:
        instances = []
        def __init__(self, **kwargs):
            self.calls = self.closed_sessions = 0
            self.__class__.instances.append(self)
        async def run_turn(self, **kwargs):
            self.calls += 1
            yield TurnComplete()
        async def close_session(self, session_id):
            self.closed_sessions += 1
        async def close(self):
            pass
    class TextChunk: pass
    class ToolCallRequest: pass
    class ExecutorError: pass
    for name, attrs in {
        "omnigent": {}, "omnigent.inner": {},
        "omnigent.inner.codex_executor": {"CodexExecutor": FakeExecutor},
        "omnigent.inner.executor": {"ExecutorConfig": ExecutorConfig, "ExecutorError": ExecutorError,
                                    "TextChunk": TextChunk, "ToolCallRequest": ToolCallRequest,
                                    "TurnComplete": TurnComplete},
    }.items():
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
    from contextlib import nullcontext
    monkeypatch.setattr("scripts.run_omnigent_live._new_codex_executor",
                        lambda executor_type, cwd, sdk_version, model: executor_type())
    monkeypatch.setattr("scripts.run_omnigent_live._minimal_codex_config", nullcontext)
    case = benchmark_quality.load_corpus()["cases"][0]
    turns = [("single_once", "single", None), ("single_self_review", "single_initial", None),
             ("single_self_review", "single_critique", {"draft": {}}),
             ("single_self_review", "single_final", {"draft": {}}),
             ("multi_role", "Planner", None), ("multi_role", "Skeptic", {"draft": {}}),
             ("multi_role", "PI", {"draft": {}})]
    async def exercise():
        for arm, role, prior in turns:
            result = await runner._ask(case, benchmark_quality.visible_packet(case), arm, role, prior,
                                       runner.MODEL, 2)
            assert result["error"] is None
            assert result["decision"]["action"] == "stop"
    asyncio.run(exercise())
    assert len(FakeExecutor.instances) == 7
    assert all(instance.calls == 1 and instance.closed_sessions == 1 for instance in FakeExecutor.instances)


def test_failed_required_turn_scores_arm_zero_and_stops_calls(monkeypatch):
    calls = []

    async def fake_ask(case, packet, arm, role, prior, model, timeout):
        calls.append(role)
        if role == "single_critique":
            return {"error": "synthetic failure", "decision": None, "turn_seconds": .1}
        return {"error": None, "decision": {"answers": {}, "action": "stop", "citations": []}, "turn_seconds": .1}

    monkeypatch.setattr(runner, "_ask", fake_ask)
    case = benchmark_quality.load_corpus()["cases"][0]
    group = {"arms": {"single_self_review": {"status": "not_started", "turns": [], "score": {}}}}
    checkpoints = []
    asyncio.run(runner._execute_arm(case, benchmark_quality.visible_packet(case), "single_self_review",
                                    runner.MODEL, __import__("time").monotonic() + 30,
                                    {"calls": 0}, lambda: checkpoints.append(True), group))
    arm = group["arms"]["single_self_review"]
    assert calls == ["single_initial", "single_critique"]
    assert arm["status"] == "failed"
    assert arm["score"]["quality_score"] == 0
    assert arm["final_answer_score"]["quality_score"] == 0
    assert len(checkpoints) == 5  # before each call, after each call, and final arm score


def test_custom_call_cap_is_enforced_between_turns(monkeypatch):
    calls = []
    async def fake_ask(case, packet, arm, role, prior, model, timeout):
        calls.append(role)
        return {"error": None, "decision": {"answers": {}, "action": "stop", "citations": []}, "turn_seconds": .01}
    monkeypatch.setattr(runner, "_ask", fake_ask)
    case = benchmark_quality.load_corpus()["cases"][0]
    group = {"arms": {"multi_role": {"status": "not_started", "turns": [], "score": {}}}}
    asyncio.run(runner._execute_arm(case, benchmark_quality.visible_packet(case), "multi_role", runner.MODEL,
                                    __import__("time").monotonic() + 30, {"calls": 0, "max_calls": 1},
                                    lambda: None, group))
    arm = group["arms"]["multi_role"]
    assert calls == ["Planner"]
    assert arm["calls_started"] == 1
    assert arm["status"] == "failed"
    assert arm["score"]["quality_score"] == 0


def test_not_started_planned_group_is_retained_as_zero_in_aggregation():
    group = {"case_id": "case-x", "repetition": 1,
             "arms": {arm: {"status": "not_started", "score": {},
                            "elapsed_seconds": None, "turn_seconds_sum": None}
                      for arm in runner.ARMS}}
    report = {"groups": [group]}
    runner._aggregate(report)
    for arm in runner.ARMS:
        assert report["summary"][arm]["raw"][0]["score"] is None
        assert report["summary"][arm]["n_not_started"] == 1
        assert report["summary"][arm]["mean_quality_score"] is None
    comparison = report["paired_multi_role_minus_self_review"]
    assert comparison["raw_group_deltas"] == [None]
    assert comparison["casewise_sign_test"] is None
    assert comparison["bootstrap_95_percentile_ci"]["not_computed_incomplete"]


def test_report_path_rejects_existing_file(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    dest = runs / "existing.json"
    dest.write_text("{}")
    monkeypatch.setattr(runner, "RUNS", runs)
    with pytest.raises(FileExistsError):
        runner._report_path(str(dest))


def test_existing_output_fails_before_any_model_call(tmp_path, monkeypatch):
    import time
    runs = tmp_path / "runs"
    runs.mkdir()
    output = runs / "already-there.json"
    output.write_text("preserve")
    monkeypatch.setattr(runner, "RUNS", runs)
    case = benchmark_quality.load_corpus()["cases"]
    digest = benchmark_quality.corpus_sha256()
    monkeypatch.setattr(benchmark_quality, "load_corpus", lambda: {"cases": case})
    monkeypatch.setattr(benchmark_quality, "corpus_sha256", lambda corpus: digest)
    monkeypatch.setattr(benchmark_quality, "FROZEN_CORPUS_SHA256", digest)
    async def forbidden(*args, **kwargs):
        raise AssertionError("no calls are allowed when output path exists")
    monkeypatch.setattr(runner, "_ask", forbidden)
    args = argparse.Namespace(repetitions=1, case_limit=1, max_calls=84, enable_model_calls=True,
                              output=str(output), model=runner.MODEL)
    with pytest.raises(FileExistsError):
        asyncio.run(runner._run(args))
    assert output.read_text() == "preserve"
