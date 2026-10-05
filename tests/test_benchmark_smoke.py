import json

import pytest

from scripts import run_benchmark_smoke
from scripts.run_benchmark_smoke import build_report, main


def test_report_measures_fixture_runtime_and_real_guard_rejections():
    report = build_report(1)

    assert report["scope"] == "in_process_fixture_runtime_only"
    assert report["model_usage"] is None
    assert report["billing_cost"] is None
    observation = report["observations"][0]
    path = observation["fixture_runtime_path"]
    assert path["outcome"] == "fixture_steps_completed"
    assert path["state"] == "second_result_ready"
    assert path["modes"] == ["fixture", "fixture"]
    assert len(path["result_ids"]) == 2
    assert path["duration_seconds"] > 0
    assert {control["name"] for control in observation["negative_controls"]} == {
        "unregistered_experiment_id",
        "second_experiment_without_review",
        "review_references_wrong_result_id",
        "second_experiment_reuses_template_under_new_id",
        "second_experiment_disagrees_with_review_next_template",
        "proposal_exceeds_budget",
        "choice_is_not_registered",
    }
    assert report["guard_counts"] == {
        "positive_fixture_paths_passed": 1,
        "positive_fixture_paths_total": 1,
        "negative_controls_rejected": 7,
        "negative_controls_total": 7,
    }
    assert all(control["outcome"] == "rejected_as_expected" for control in observation["negative_controls"])
    assert all(control["duration_seconds"] > 0 for control in observation["negative_controls"])


def test_cli_writes_json_report_and_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(run_benchmark_smoke, "ROOT", tmp_path)
    output = tmp_path / "runs" / "smoke.json"

    assert main(["--repetitions", "1", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report_type"] == "offline_fixture_runtime_smoke"
    with pytest.raises(SystemExit):
        main(["--repetitions", "1", "--output", str(output)])


def test_cli_rejects_path_outside_runs_before_running_benchmark(tmp_path, monkeypatch):
    monkeypatch.setattr(run_benchmark_smoke, "ROOT", tmp_path)
    monkeypatch.setattr(run_benchmark_smoke, "build_report", lambda _: pytest.fail("benchmark must not run"))
    with pytest.raises(SystemExit):
        main(["--repetitions", "1", "--output", str(tmp_path / "outside.json")])


def test_cli_rejects_escaping_runs_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr(run_benchmark_smoke, "ROOT", tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        (tmp_path / "runs").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(SystemExit):
        main(["--repetitions", "1", "--output", str(tmp_path / "runs" / "smoke.json")])


def test_cli_rejects_nested_escape_and_checks_existing_output_before_benchmark(tmp_path, monkeypatch):
    monkeypatch.setattr(run_benchmark_smoke, "ROOT", tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (runs / "escape").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable")
    monkeypatch.setattr(run_benchmark_smoke, "build_report", lambda _: pytest.fail("benchmark must not run"))
    with pytest.raises(SystemExit):
        main(["--repetitions", "1", "--output", str(runs / "escape" / "smoke.json")])
    existing = runs / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--repetitions", "1", "--output", str(existing)])
    assert existing.read_text(encoding="utf-8") == "keep"


def test_repetition_count_is_bounded():
    with pytest.raises(ValueError, match="between 1 and 20"):
        build_report(21)
