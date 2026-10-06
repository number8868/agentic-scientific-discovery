import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_research_decision_benchmark as runner
from nova.benchmark_parallel_report import ARMS


def _prepare(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"
    def make_run(_requested=None):
        run_dir.mkdir(mode=0o700)
        return run_dir
    monkeypatch.setattr(runner, "create_run_directory", make_run)
    return run_dir


def _success_executor(calls):
    async def fake(*, case, group, arm, model, reasoning_effort, budget,
                   store, report, arm_deadline_at):
        calls.append((case["id"], arm))
        roles = ({"single_self_review": ("draft", "critique", "final"),
                  "parallel_review": ("planner", "skeptic", "pi")})[arm]
        for role in roles:
            await budget.before_dispatch(packet_id=case["id"], repetition=group["repetition"],
                                         arm=arm, role=role)
        group["arms"][arm].update({
            "status": "completed", "runtime_status": "success", "cleanup_ok": True,
            "fatal_audit": False, "delivery_valid": True,
            "observed_delivery_seconds": 2.0, "deadline_penalty_seconds": 2.0,
            "grade": {"semantic_score": 1.0, "strict_schema_pass": True,
                      "citation_pass": True, "scope_pass": True},
        })
    return fake


def test_default_is_offline_manifest_zero_dispatch(monkeypatch, tmp_path):
    run_dir = _prepare(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(runner, "_execute_arm", _success_executor(calls))
    args = runner.build_parser().parse_args([])
    assert asyncio.run(runner._run(args)) == 0
    report = json.loads((run_dir / "report.json").read_text())
    assert report["runner_status"] == "offline_manifest_only"
    assert report["model_calls_enabled"] is False
    assert report["sdk_turns_reserved"] == 0
    assert calls == []


def test_enabled_eight_case_limit_is_hard_48_turn_cap(monkeypatch, tmp_path):
    run_dir = _prepare(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(runner, "_execute_arm", _success_executor(calls))
    args = runner.build_parser().parse_args(["--enable-model-calls", "--limit-cases", "8"])
    assert asyncio.run(runner._run(args)) == 0
    report = json.loads((run_dir / "report.json").read_text())
    assert report["limits"]["sdk_turns"] == 48
    assert report["sdk_turns_reserved"] == 48
    assert len(calls) == 16
    assert report["descriptive_results"]["completed_pairs"] == 8
    assert report["descriptive_results"]["failed_or_incomplete_pairs"] == 0


def test_fatal_cleanup_stops_before_next_arm(monkeypatch, tmp_path):
    run_dir = _prepare(monkeypatch, tmp_path)
    calls = []
    async def fatal(*, case, group, arm, model, reasoning_effort, budget,
                    store, report, arm_deadline_at):
        calls.append((case["id"], arm))
        group["arms"][arm].update({"status": "failed", "cleanup_ok": False,
                                  "fatal_audit": True, "runtime_status": "cleanup_failed"})
    monkeypatch.setattr(runner, "_execute_arm", fatal)
    args = runner.build_parser().parse_args(["--enable-model-calls", "--limit-cases", "4"])
    assert asyncio.run(runner._run(args)) == 3
    report = json.loads((run_dir / "report.json").read_text())
    assert report["runner_status"] == "interrupted_or_failed"
    assert len(calls) == 1
    assert report["sdk_turns_reserved"] == 0
