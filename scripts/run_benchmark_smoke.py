"""Offline, fixture-only runtime smoke measurement for NOVA-MAT.

This measures the in-process Run and registered-experiment path. It is not a
scientific, native-host, model, or multi-agent benchmark.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova.fixture_engine import execute as fixture_execute  # noqa: E402
from nova.runtime import Proposal, Run, RunState  # noqa: E402
from nova.tools import execute_registered_experiment  # noqa: E402


def _measure_guard(label: str, callback: Any, expected: type[Exception]) -> dict[str, Any]:
    start = perf_counter()
    try:
        callback()
    except expected as exc:
        elapsed = perf_counter() - start
        return {"name": label, "outcome": "rejected_as_expected", "exception": type(exc).__name__, "duration_seconds": elapsed}
    except Exception as exc:  # unexpected guard behavior is a harness failure
        raise AssertionError(f"{label} raised unexpected {type(exc).__name__}") from exc
    raise AssertionError(f"{label} was not rejected")


def _one_repetition(index: int) -> dict[str, Any]:
    base = {"mode": "fixture", "seed": 1729, "bootstrap_repeats": 25}
    run = Run("Fixture smoke: exercise registered two-step runtime", fixture_execute)
    start = perf_counter()
    run.freeze_hypothesis("Fixture-only smoke hypothesis")
    run.register_plan([
        Proposal(f"smoke-{index}-first", "family_screen", {**base, "template": "family_screen"}),
        Proposal(f"smoke-{index}-second", "threshold_sensitivity", {**base, "template": "threshold_sensitivity"}),
    ])
    run.choose(f"smoke-{index}-first")
    first = run.run_first()
    run.submit_skeptic_review(
        concern="Exercise the fixture threshold follow-up path.",
        next_template="threshold_sensitivity",
        result_id=first.result_id,
    )
    second = run.run_second(f"smoke-{index}-second")
    elapsed = perf_counter() - start
    if run.state is not RunState.SECOND_RESULT_READY:
        raise AssertionError(f"fixture path ended in unexpected state: {run.state.value}")
    if any(result.execution_status != "completed" or result.mode != "fixture" for result in (first, second)):
        raise AssertionError("fixture execution did not return successful fixture Results")

    # Exercise host guards through their real public interfaces. These are
    # runtime negative controls, not alternative workflow or policy arms.
    unknown_id = _measure_guard(
        "unregistered_experiment_id",
        lambda: execute_registered_experiment(f"unknown-{index}"),
        PermissionError,
    )
    def ready_run(suffix: str, *, budget: int = 360, templates: tuple[str, ...] = ("family_screen", "threshold_sensitivity")) -> Run:
        guarded = Run(f"Fixture guard: {suffix}", fixture_execute, budget_seconds=budget)
        guarded.freeze_hypothesis("Fixture-only guard hypothesis")
        guarded.register_plan([
            Proposal(f"guard-{index}-{suffix}-{n}", template, {**base, "template": template})
            for n, template in enumerate(templates)
        ])
        guarded.choose(f"guard-{index}-{suffix}-0")
        guarded.run_first()
        return guarded

    premature_run = ready_run("premature")
    premature = _measure_guard(
        "second_experiment_without_review",
        lambda: premature_run.run_second(f"guard-{index}-premature-1"),
        RuntimeError,
    )
    wrong_result_run = ready_run("wrong-result")
    wrong_result = _measure_guard(
        "review_references_wrong_result_id",
        lambda: wrong_result_run.submit_skeptic_review(concern="test", next_template="threshold_sensitivity", result_id="not-the-result"),
        ValueError,
    )
    same_template_run = ready_run("same-template", templates=("family_screen", "family_screen"))
    same_template_run.submit_skeptic_review(concern="test", next_template="family_screen")
    same_template = _measure_guard(
        "second_experiment_reuses_template_under_new_id",
        lambda: same_template_run.run_second(f"guard-{index}-same-template-1"),
        ValueError,
    )
    wrong_next_run = ready_run("wrong-next")
    wrong_next_run.submit_skeptic_review(concern="test", next_template="gap_window_sensitivity")
    wrong_next = _measure_guard(
        "second_experiment_disagrees_with_review_next_template",
        lambda: wrong_next_run.run_second(f"guard-{index}-wrong-next-1"),
        ValueError,
    )
    budget_run = Run("Fixture guard: budget", fixture_execute, budget_seconds=0)
    budget_run.freeze_hypothesis("Fixture-only budget hypothesis")
    budget_run.register_plan([
        Proposal(f"guard-{index}-budget-{n}", template, {**base, "template": template}, estimated_seconds=1)
        for n, template in enumerate(("family_screen", "threshold_sensitivity"))
    ])
    over_budget = _measure_guard("proposal_exceeds_budget", lambda: budget_run.choose(f"guard-{index}-budget-0"), RuntimeError)
    unknown_choice_run = Run("Fixture guard: choice", fixture_execute)
    unknown_choice_run.freeze_hypothesis("Fixture-only choice hypothesis")
    unknown_choice_run.register_plan([
        Proposal(f"guard-{index}-choice-{n}", template, {**base, "template": template})
        for n, template in enumerate(("family_screen", "threshold_sensitivity"))
    ])
    unknown_choice = _measure_guard("choice_is_not_registered", lambda: unknown_choice_run.choose("not-registered"), KeyError)
    negative_controls = [unknown_id, premature, wrong_result, same_template, wrong_next, over_budget, unknown_choice]

    return {
        "repetition": index,
        "fixture_runtime_path": {
            "outcome": "fixture_steps_completed",
            "state": run.state.value,
            "duration_seconds": elapsed,
            "run_id": run.run_id,
            "result_ids": [first.result_id, second.result_id],
            "templates": [first.template, second.template],
            "modes": [first.mode, second.mode],
            "seed": 1729,
            "bootstrap_repeats": 25,
        },
        "negative_controls": negative_controls,
    }


def build_report(repetitions: int) -> dict[str, Any]:
    if repetitions < 1 or repetitions > 20:
        raise ValueError("repetitions must be between 1 and 20")
    observations = [_one_repetition(i + 1) for i in range(repetitions)]
    durations = [o["fixture_runtime_path"]["duration_seconds"] for o in observations]
    source_commit = None
    try:
        source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    script_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    positive_count = sum(o["fixture_runtime_path"]["outcome"] == "fixture_steps_completed" for o in observations)
    negative_count = sum(c["outcome"] == "rejected_as_expected" for o in observations for c in o["negative_controls"])
    return {
        "report_type": "offline_fixture_runtime_smoke",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "runner_script_sha256": script_sha256,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "scope": "in_process_fixture_runtime_only",
        "limitations": [
            "Fixture data and outputs are non-scientific and do not represent NOVA-MAT scientific performance.",
            "This does not exercise a native host, Omnigent, live models, or a completed scientific workflow.",
            "The runtime path ends at SECOND_RESULT_READY; it is not labeled a completed end-to-end workflow.",
            "Negative controls are actual runtime guard calls, not policy arms or agent comparisons.",
            "No multi-agent speedup or model performance is measured.",
        ],
        "model_usage": None,
        "model_usage_status": "not_applicable_no_model_calls",
        "billing_cost": None,
        "human_time": None,
        "repetitions": repetitions,
        "guard_counts": {
            "positive_fixture_paths_passed": positive_count,
            "positive_fixture_paths_total": len(observations),
            "negative_controls_rejected": negative_count,
            "negative_controls_total": sum(len(o["negative_controls"]) for o in observations),
        },
        "timing": {
            "clock": "time.perf_counter",
            "scope": "Run state transitions and two registered fixture executions, including deterministic fixture bootstrap computation; excludes process startup and JSON writing",
            "durations_seconds": durations,
            "mean_seconds": sum(durations) / len(durations),
            "min_seconds": min(durations),
            "max_seconds": max(durations),
        },
        "observations": observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3, help="1-20 independent in-process fixture repetitions")
    parser.add_argument("--output", type=Path, help="JSON report path (must not already exist); default is a unique file under runs/")
    args = parser.parse_args(argv)
    output = args.output or Path("runs") / f"benchmark-smoke-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    root_runs = (ROOT / "runs").resolve()
    if not root_runs.is_relative_to(ROOT.resolve()):
        parser.error("repository runs/ directory resolves outside the repository")
    output = output if output.is_absolute() else ROOT / output
    resolved_output = output.resolve()
    if not resolved_output.is_relative_to(root_runs):
        parser.error("--output must be under the repository runs/ directory")
    if resolved_output.exists():
        parser.error(f"output already exists: {resolved_output}")
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(args.repetitions)
    # Exclusive creation preserves earlier artifacts if a path is reused.
    with resolved_output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(resolved_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
