import asyncio
import json
from pathlib import Path

from scripts import run_decision_benchmark as runner
from nova import benchmark_decisions


def test_parser_disables_model_calls_by_default():
    args = runner.build_parser().parse_args([])
    assert args.enable_model_calls is False
    assert args.model == "gpt-6-luna"
    assert runner.MAX_CASES == runner.MAX_REPETITIONS == 1
    assert runner.MAX_MODEL_CALLS == 4


def test_parse_decision_and_reject_extra_fields():
    assert runner._parse_decision('{"action":"stop","citations":[],"claim_tags":[]}') == {
        "action": "stop", "citations": [], "claim_tags": []
    }
    try:
        runner._parse_decision('{"action":"stop","citations":[],"claim_tags":[],"reason":"x"}')
    except ValueError:
        pass
    else:
        raise AssertionError("extra model fields must be rejected")


def test_report_path_is_runs_contained_and_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "RUNS", tmp_path / "runs")
    report = runner._report_path("runs/out.json")
    runner._ReportFile(report).close()
    try:
        runner._report_path("runs/out.json")
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing reports must not be overwritten")
    try:
        runner._report_path("elsewhere/out.json")
    except ValueError:
        pass
    else:
        raise AssertionError("report must be under runs")


def test_fixed_only_cli_writes_offline_six_case_report(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "RUNS", tmp_path / "runs")
    args = runner.build_parser().parse_args(["--output", "runs/offline.json"])
    assert asyncio.run(runner._run(args)) == 0
    report = json.loads((tmp_path / "runs/offline.json").read_text())
    assert report["model_calls_enabled"] is False
    assert report["model_calls_used"] == 0
    assert len(report["arms"]) == 6
    assert all(item["kind"] == "fixed_rule" for item in report["arms"])


def test_mocked_live_arm_chains_three_roles_and_checkpoints_all_calls(monkeypatch):
    case = benchmark_decisions.load_corpus()["cases"][0]
    case["evidence"] = benchmark_decisions.load_corpus()["evidence"]
    fixed = benchmark_decisions.fixed_decision(case)
    invocations = []

    async def fake_ask(case_arg, role, model, timeout, prior=None):
        assert case_arg["evidence"]["reference"] == "native09-main"
        assert timeout <= runner.PER_CALL_TIMEOUT_SECONDS
        if role == "single":
            assert prior is None
        if role == "planner":
            assert prior == {}
        if role == "skeptic":
            assert "planner" in prior
        if role == "pi":
            assert {"planner", "skeptic"} <= set(prior)
        invocations.append(role)
        return {"role": role, "raw_response": json.dumps(fixed), "usage": None,
                "elapsed_seconds": 0.01, "error": None, "decision": fixed}

    monkeypatch.setattr(runner, "_ask_role", fake_ask)
    report = {"roles": [], "status": "running"}
    checkpoints = []
    calls = asyncio.run(runner._run_live(case, "gpt-6-luna", 10**12, report,
                                        lambda count: checkpoints.append((count, len(report["roles"])))) )
    assert calls == 4
    assert invocations == ["single", "planner", "skeptic", "pi"]
    assert checkpoints == [(1, 1), (2, 2), (3, 3), (4, 4)]
    assert report["status"] == "completed"
    assert report["score"]["structural_pass"] is True
    assert all(item["usage"] is None for item in report["roles"])


def test_omnigent_factory_turns_off_native_capabilities(monkeypatch):
    import scripts.run_omnigent_live as existing_runner

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self._codex_config_overrides = []
            self._env = {}

    executor = existing_runner._new_codex_executor(FakeExecutor, "/tmp", "0.16.0")
    assert executor.kwargs["disable_native_tools"] is True
    assert executor.kwargs["enable_web_search"] is False
    assert executor.kwargs["skills_filter"] == "none"
    assert "features.code_mode=false" in executor._codex_config_overrides

