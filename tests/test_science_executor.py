from __future__ import annotations

import hashlib
import json

import pytest

from nova.contracts import ExperimentSpec, GroupSummary, Result
from nova.experiments import executor


DATASET_SHA = "a" * 64


def registered_spec(**updates):
    spec = {
        "schema_version": 1,
        "experiment_id": "live-exp-1",
        "hypothesis_id": "H1",
        "dataset_sha256": DATASET_SHA,
        "split": "discovery",
        "template": "family_screen",
        "groups": ["oxide", "chalcogenide"],
        "bandgap_method": "opt",
        "gap_window_ev": [1.1, 1.8],
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "timeout_seconds": 120,
        "mode": "live",
        "run_id": "host-run-1",
    }
    spec.update(updates)
    return spec


def science_payload(minimal, *, started="2026-10-03T20:00:00+00:00"):
    computation_spec = {key: minimal[key] for key in executor._SCIENCE_FIELDS}
    return {
        "schema_version": 1,
        "template": minimal["template"],
        "execution_status": "success",
        "scientific_status": "inconclusive",
        "dataset_sha256": minimal["dataset_sha256"],
        "spec_sha256": executor._sha256(
            executor._canonical_json(computation_spec).encode("utf-8")
        ),
        "started_at": started,
        "finished_at": "2026-10-03T20:00:02+00:00",
        "elapsed_seconds": 2.0,
        "groups_summary": {
            "oxide": {
                "n_total": 50,
                "n_observed": 45,
                "n_pass": 5,
                "coverage": 0.9,
                "observed_rate": 5 / 45,
                "missing_lower": 0.1,
                "missing_upper": 0.2,
            },
            "chalcogenide": {
                "n_total": 40,
                "n_observed": 40,
                "n_pass": 8,
                "coverage": 1.0,
                "observed_rate": 0.2,
                "missing_lower": 0.2,
                "missing_upper": 0.2,
            },
        },
        "delta": 0.0888888888888889,
        "resampling_interval": [0.01, 0.17],
        "missingness_interval": {
            "lower": 0.0,
            "upper": 0.2,
            "oxide_rate_lower": 0.1,
            "oxide_rate_upper": 0.2,
            "chalcogenide_rate_lower": 0.2,
            "chalcogenide_rate_upper": 0.2,
        },
        "quality_flags": {
            "minimum_sample_and_coverage_pass": True,
            "endpoint_non_degenerate": True,
            "families": {"oxide": {"minimum_coverage_pass": True}},
        },
        "bootstrap": {
            "replicates": 2_000,
            "seed": 1_729,
            "resampling_interval": [0.01, 0.17],
        },
        "points": [
            {"ehull_max_ev_atom": 0.025, "delta": 0.01},
            {"ehull_max_ev_atom": 0.05, "delta": 0.0888888888888889},
            {"ehull_max_ev_atom": 0.1, "delta": 0.12},
        ],
        "artifact_ids": [f"nova-manifest:{DATASET_SHA}"],
        "error": None,
    }


def prepare_adapter(monkeypatch, tmp_path, output=None):
    monkeypatch.setattr(executor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        executor,
        "_load_frozen_manifest",
        lambda: {
            "dataset": "dft_3d",
            "original_download_zip_sha256": DATASET_SHA,
        },
    )
    if output is not None:
        monkeypatch.setattr(executor.family_screen, "run_experiment", output)


def test_execute_adapts_contract_and_preserves_full_science_payload(monkeypatch, tmp_path):
    received = {}

    def run_experiment(minimal):
        received.update(minimal)
        return science_payload(minimal)

    prepare_adapter(monkeypatch, tmp_path, run_experiment)
    spec = registered_spec()
    result = executor.execute(spec)

    contract = ExperimentSpec.from_dict({
        key: value for key, value in spec.items()
        if key not in {"mode", "run_id"}
    })
    assert isinstance(result, Result)
    assert result.execution_status == "completed"
    assert result.spec_sha256 == contract.sha256
    assert received["groups"] == ["oxide", "chalcogenide"]
    assert received["gap_window_ev"] == [1.1, 1.8]
    assert "experiment_id" not in received
    assert result.groups_summary == (
        GroupSummary("oxide", 50, 45, 5, 0.9, 5 / 45, 0.1, 0.2),
        GroupSummary("chalcogenide", 40, 40, 8, 1.0, 0.2, 0.2, 0.2),
    )
    assert result.resampling_interval == (0.01, 0.17)
    assert result.missingness_interval == (0.0, 0.2)
    assert result.quality_flags[0].startswith("science-quality-json-v1:")
    assert json.loads(result.quality_flags[0].split(":", 1)[1])["families"]["oxide"]["minimum_coverage_pass"]
    assert f"nova-manifest:{DATASET_SHA}" in result.artifact_ids

    payload_id = next(item for item in result.artifact_ids if item.startswith("nova-result-payload:"))
    path_ref = next(item for item in result.artifact_ids if item.startswith("nova-artifact-path:"))
    relative_path = path_ref.split(":", 1)[1]
    artifact_path = tmp_path / relative_path
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == payload_id.split(":", 1)[1]
    assert artifact["registered_spec_sha256"] == contract.sha256
    assert artifact["computation_spec_sha256"] == executor._computation_spec_sha256(received)
    assert [point["ehull_max_ev_atom"] for point in artifact["science_result"]["points"]] == [
        0.025,
        0.05,
        0.1,
    ]
    assert "started_at" not in artifact["science_result"]


def test_result_id_and_artifact_are_stable_when_only_timing_changes(monkeypatch, tmp_path):
    counter = 0

    def run_experiment(minimal):
        nonlocal counter
        counter += 1
        return science_payload(minimal, started=f"2026-10-03T20:00:0{counter}+00:00")

    prepare_adapter(monkeypatch, tmp_path, run_experiment)
    first = executor.execute(registered_spec())
    second = executor.execute(registered_spec())

    assert first.result_id == second.result_id
    assert first.started_at != second.started_at
    assert first.artifact_ids == second.artifact_ids


def test_threshold_executor_uses_extension_hash_and_keeps_all_points(monkeypatch, tmp_path):
    from nova.experiments import threshold_sensitivity

    spec = registered_spec(
        experiment_id="live-threshold-1",
        template="threshold_sensitivity",
    )
    minimal = executor._minimal_science_spec(
        ExperimentSpec.from_dict({
            key: value for key, value in spec.items()
            if key not in {"mode", "run_id"}
        })
    )
    computation = {key: minimal[key] for key in executor._SCIENCE_FIELDS}
    computation["ehull_grid_ev_atom"] = list(threshold_sensitivity.THRESHOLD_GRID_EV_ATOM)
    computation["extension_protocol_sha256"] = threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256
    raw = science_payload(minimal)
    raw["spec_sha256"] = executor._sha256(
        executor._canonical_json(computation).encode("utf-8")
    )
    raw["main_point"] = {"delta": raw["delta"], "scientific_status": "inconclusive"}
    raw["primary_point_index"] = 1
    raw["points"] = [
        {"threshold_ev_atom": 0.025, "delta": 0.02},
        {"threshold_ev_atom": 0.05, "delta": 0.08},
        {"threshold_ev_atom": 0.1, "delta": 0.12},
    ]

    prepare_adapter(
        monkeypatch,
        tmp_path,
        lambda received: raw,
    )
    monkeypatch.setattr(threshold_sensitivity, "run_experiment", lambda received: raw)
    result = executor.execute(spec)

    artifact_path = tmp_path / next(
        value.split(":", 1)[1]
        for value in result.artifact_ids
        if value.startswith("nova-artifact-path:")
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert result.execution_status == "completed"
    assert artifact["computation_spec_sha256"] == raw["spec_sha256"]
    assert [point["threshold_ev_atom"] for point in artifact["science_result"]["points"]] == [
        0.025,
        0.05,
        0.1,
    ]


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"mode": "fixture"}, "live mode"),
        ({"unknown": "value"}, "unknown live executor fields"),
        ({"dataset_sha256": "b" * 64}, "dataset_sha256"),
        ({"split": "holdout"}, "split"),
        ({"gap_window_ev": [0.9, 1.6]}, "gap_window_ev"),
        ({"ehull_max_ev_atom": 0.1}, "ehull_max_ev_atom"),
        ({"bootstrap_repeats": 100}, "bootstrap_repeats"),
        ({"timeout_seconds": 60}, "timeout_seconds"),
        (
            {"template": "holdout_validation", "frozen_protocol_id": "registered-final-v1"},
            "only discovery",
        ),
        ({"mode": "replay"}, "live mode"),
    ],
)
def test_execute_rejects_unauthorized_or_modified_specs(monkeypatch, tmp_path, updates, match):
    prepare_adapter(monkeypatch, tmp_path)
    with pytest.raises((ValueError, TypeError), match=match):
        executor.execute(registered_spec(**updates))


def test_execute_requires_registered_experiment_id_and_rejects_path_inputs(monkeypatch, tmp_path):
    prepare_adapter(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="experiment_id"):
        executor.execute(registered_spec(experiment_id=""))
    with pytest.raises(ValueError, match="unknown live executor fields"):
        executor.execute(registered_spec(source_path="../../data/holdout.csv"))
