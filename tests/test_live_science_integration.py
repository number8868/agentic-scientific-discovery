from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re

import pytest

from nova import evidence
from nova import science_adapter
from nova.contracts import ExperimentSpec, Result
from nova.experiments import executor
from nova.storage import Storage
from nova.workflow import PersistentWorkflow


DATASET_SHA = "a" * 64


def _spec(experiment_id: str, template: str) -> dict:
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "hypothesis_id": "H1",
        "dataset_sha256": DATASET_SHA,
        "split": "discovery",
        "template": template,
        "groups": ("oxide", "chalcogenide"),
        "bandgap_method": "opt",
        "gap_window_ev": (1.1, 1.8),
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "timeout_seconds": 120,
        "mode": "live",
    }


def _science_result(minimal: dict) -> dict:
    computation_spec = {key: minimal[key] for key in executor._SCIENCE_FIELDS}
    return {
        "schema_version": 1,
        "template": minimal["template"],
        "execution_status": "success",
        "scientific_status": "data_limited",
        "dataset_sha256": DATASET_SHA,
        "spec_sha256": executor._sha256(
            executor._canonical_json(computation_spec).encode("utf-8")
        ),
        "started_at": "2026-10-03T20:10:00+00:00",
        "finished_at": "2026-10-03T20:10:01+00:00",
        "elapsed_seconds": 1.0,
        "groups_summary": {
            "oxide": {
                "n_total": 2, "n_observed": 1, "n_pass": 0,
                "coverage": 0.5, "observed_rate": 0.0,
                "missing_lower": 0.0, "missing_upper": 0.5,
            },
            "chalcogenide": {
                "n_total": 2, "n_observed": 2, "n_pass": 1,
                "coverage": 1.0, "observed_rate": 0.5,
                "missing_lower": 0.5, "missing_upper": 0.5,
            },
        },
        "delta": None,
        "resampling_interval": None,
        "missingness_interval": {"lower": -0.5, "upper": 1.0},
        "quality_flags": {"minimum_sample_and_coverage_pass": False},
        "bootstrap": None,
        "artifact_ids": [f"nova-manifest:{DATASET_SHA}"],
        "error": None,
    }


def _load_live_script():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_live_science.py"
    module_spec = importlib.util.spec_from_file_location("run_live_science_integration", script_path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def test_live_workflow_saves_registered_result_events_and_science_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(executor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        executor,
        "_load_frozen_manifest",
        lambda: {"dataset": "dft_3d", "original_download_zip_sha256": DATASET_SHA},
    )
    monkeypatch.setattr(
        executor.family_screen,
        "run_experiment",
        lambda minimal: _science_result(minimal),
    )

    runs = tmp_path / "runs"
    runs.mkdir()
    store = Storage(runs / "evidence.sqlite")
    workflow = PersistentWorkflow(
        store,
        objective="Compare the frozen discovery family pass rates.",
        mode="live",
        run_id="live-test-1",
        experiment_executor=executor.execute,
    )
    workflow.freeze_hypothesis("H1: chalcogenides have a higher observed pass rate.")
    first_spec = _spec("live-test-1-family-screen", "family_screen")
    second_spec = _spec("live-test-1-threshold-sensitivity", "threshold_sensitivity")
    workflow.register_plan([
        {
            "proposal_id": first_spec["experiment_id"],
            "template": first_spec["template"],
            "spec": first_spec,
            "estimated_seconds": 120,
            "learning_score": 3,
        },
        {
            "proposal_id": second_spec["experiment_id"],
            "template": second_spec["template"],
            "spec": second_spec,
            "estimated_seconds": 120,
            "learning_score": 3,
        },
    ])

    workflow.select(first_spec["experiment_id"])
    result = workflow.run_first()
    registered = store.read_spec(first_spec["experiment_id"])

    assert isinstance(result, Result)
    assert result.execution_status == "completed"
    assert result.spec_sha256 == registered.sha256
    assert store.read_result(result.result_id) == result
    events = store.list_events(workflow.run_id)
    assert [event.mode.value for event in events] == ["live"] * len(events)
    assert any(event.event_type == "result" and event.payload_ref == result.result_id for event in events)

    export_dir = runs / "evidence-export"
    evidence.export_run(store.path, workflow.run_id, export_dir)
    executor.export_science_artifacts(result, export_dir)
    exported_result = json.loads((export_dir / "results.json").read_text(encoding="utf-8"))[0]
    exported_artifact_manifest = json.loads(
        (export_dir / "science-artifacts.json").read_text(encoding="utf-8")
    )
    assert exported_result["spec_sha256"] == registered.sha256
    assert exported_artifact_manifest["results"] == [
        {
            "result_id": result.result_id,
            "experiment_id": result.experiment_id,
            "registered_spec_sha256": registered.sha256,
            "artifact_ids": [
                item for item in result.artifact_ids if item.startswith("nova-result-payload:")
            ],
        }
    ]
    assert (export_dir / exported_artifact_manifest["artifacts"][0]["exported_path"]).is_file()


def test_human_scripted_two_rounds_links_actual_result_and_exports_both_payloads(
    monkeypatch,
    tmp_path,
    capsys,
):
    from nova.experiments import threshold_sensitivity

    runner = _load_live_script()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(executor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        executor,
        "_load_frozen_manifest",
        lambda: {"dataset": "dft_3d", "original_download_zip_sha256": DATASET_SHA},
    )
    monkeypatch.setattr(
        executor.family_screen,
        "run_experiment",
        lambda minimal: _science_result(minimal),
    )

    def threshold_result(minimal):
        result = _science_result(minimal)
        result["spec_sha256"] = executor._computation_spec_sha256(minimal)
        result["main_point"] = {
            "delta": result["delta"],
            "scientific_status": result["scientific_status"],
        }
        result["primary_point_index"] = 1
        result["points"] = [
            {"threshold_ev_atom": 0.025, "delta": 0.0},
            {"threshold_ev_atom": 0.05, "delta": 0.1},
            {"threshold_ev_atom": 0.1, "delta": 0.2},
        ]
        result["artifact_ids"].append(
            "nova-threshold-protocol:" + threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256
        )
        return result

    monkeypatch.setattr(threshold_sensitivity, "run_experiment", threshold_result)

    assert runner.main(["--two-rounds"]) == 0
    output = capsys.readouterr().out
    run_id = re.search(r"^run_id=(\S+)$", output, re.MULTILINE).group(1)
    assert "integration_mode=HUMAN_SCRIPTED_LIVE_SCIENCE" in output
    assert "followup_mode=HUMAN_SCRIPTED" in output

    runs = tmp_path / "runs"
    store = Storage(runs / "live-science.sqlite")
    results = {result.experiment_id: result for result in store.list_results()}
    first_id = f"{run_id}-family-screen"
    second_id = f"{run_id}-threshold-sensitivity"
    first = next(result for result in results.values() if result.experiment_id == first_id)
    second = next(result for result in results.values() if result.experiment_id == second_id)
    second_spec = store.read_spec(second_id)
    review = store.get_review(first.result_id)

    assert second_spec.parent_result_id == first.result_id
    assert second_spec.review_id == first.result_id
    assert review.result_id == first.result_id
    assert f"scientific_status={first.scientific_status}" in review.reason
    assert f"oxide observed passes=0/1 (total=2)" in review.reason
    assert f"chalcogenide observed passes=1/2 (total=2)" in review.reason
    assert "95% resampling interval=unavailable" in review.reason

    events = store.list_events(run_id)
    linked = next(event for event in events if event.event_type == "followup_spec_linked")
    second_selection = next(event for event in events if event.event_type == "second_selection")
    assert linked.payload_ref == first.result_id
    assert linked.seq < second_selection.seq

    export_dir = runs / f"live-evidence-{run_id}"
    exported_results = json.loads((export_dir / "results.json").read_text(encoding="utf-8"))
    assert {item["result_id"] for item in exported_results} == {first.result_id, second.result_id}
    artifact_manifest = json.loads(
        (export_dir / "science-artifacts.json").read_text(encoding="utf-8")
    )
    assert {item["result_id"] for item in artifact_manifest["results"]} == {
        first.result_id,
        second.result_id,
    }
    assert len(artifact_manifest["artifacts"]) == 2
    threshold_artifact = next(
        entry
        for entry in artifact_manifest["artifacts"]
        if second.result_id in {
            item["result_id"]
            for item in artifact_manifest["results"]
            if entry["artifact_id"] in item["artifact_ids"]
        }
    )
    threshold_payload = json.loads(
        (export_dir / threshold_artifact["exported_path"]).read_text(encoding="utf-8")
    )
    assert [point["threshold_ev_atom"] for point in threshold_payload["science_result"]["points"]] == [
        0.025,
        0.05,
        0.1,
    ]


@pytest.mark.parametrize(
    ("arguments", "expected_route"),
    [
        ([], "direct"),
        (["--science-adapter"], "adapter"),
    ],
)
def test_live_script_selects_the_configured_science_adapter_route(
    monkeypatch,
    tmp_path,
    capsys,
    arguments,
    expected_route,
):
    runner = _load_live_script()
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(executor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        executor,
        "_load_frozen_manifest",
        lambda: {"dataset": "dft_3d", "original_download_zip_sha256": DATASET_SHA},
    )
    monkeypatch.setattr(
        executor.family_screen,
        "run_experiment",
        lambda minimal: _science_result(minimal),
    )

    direct_calls = []
    adapter_calls = []
    direct_executor = runner.execute

    def mocked_direct_executor(payload):
        direct_calls.append(dict(payload))
        return direct_executor(payload)

    def mocked_science_backend(payload):
        adapter_calls.append(dict(payload))
        return direct_executor(payload)

    monkeypatch.setattr(runner, "execute", mocked_direct_executor)
    monkeypatch.setattr(science_adapter.science_executor, "execute", mocked_science_backend)

    assert runner.main(arguments) == 0
    output = capsys.readouterr().out

    expected_adapter = expected_route == "adapter"
    assert f"science_adapter={'enabled' if expected_adapter else 'disabled'}" in output
    assert len(adapter_calls) == int(expected_adapter)
    assert len(direct_calls) == int(not expected_adapter)
    selected_payload = adapter_calls[0] if expected_adapter else direct_calls[0]
    assert selected_payload["mode"] == "live"
    assert selected_payload["experiment_id"].endswith("-family-screen")
    run_id = re.search(r"^run_id=(\S+)$", output, re.MULTILINE).group(1)
    store = Storage(tmp_path / "runs" / "live-science.sqlite")
    result = store.read_result(next(
        event.payload_ref
        for event in store.list_events(run_id)
        if event.event_type == "result"
    ))
    assert result.execution_status == "completed"
    assert result.spec_sha256 == store.read_spec(result.experiment_id).sha256
