from __future__ import annotations

import json

from nova import evidence
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
