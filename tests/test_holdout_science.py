import hashlib
import json
from pathlib import Path

import pytest

from nova.contracts import ExperimentSpec, GroupSummary, Result, Split, Template
from nova.experiments import executor, holdout_validation, threshold_sensitivity


DATASET_SHA = holdout_validation.DATASET_SHA256
RUN_ID = "synthetic-run"


def _groups_and_quality():
    groups = {
        "oxide": {
            "n_total": 50,
            "n_observed": 50,
            "n_pass": 10,
            "coverage": 1.0,
            "observed_rate": 0.2,
            "missing_lower": 0.2,
            "missing_upper": 0.2,
        },
        "chalcogenide": {
            "n_total": 50,
            "n_observed": 50,
            "n_pass": 35,
            "coverage": 1.0,
            "observed_rate": 0.7,
            "missing_lower": 0.7,
            "missing_upper": 0.7,
        },
    }
    quality = {
        "oxide": {
            "minimum_evaluable_count_pass": True,
            "minimum_coverage_pass": True,
            "endpoint_has_pass_and_fail": True,
        },
        "chalcogenide": {
            "minimum_evaluable_count_pass": True,
            "minimum_coverage_pass": True,
            "endpoint_has_pass_and_fail": True,
        },
        "minimum_sample_and_coverage_pass": True,
        "endpoint_non_degenerate": True,
        "missingness_bounds_cross_zero": False,
    }
    return groups, quality


def _canonical_results():
    main = ExperimentSpec(
        1, "main-experiment", "H-001", DATASET_SHA, Split.DISCOVERY,
        Template.FAMILY_SCREEN, ("oxide", "chalcogenide"), "opt", (1.1, 1.8),
        0.05, 2_000, 1_729, 120,
    )
    followup = ExperimentSpec(
        1, "followup-experiment", "H-001", DATASET_SHA, Split.DISCOVERY,
        Template.THRESHOLD_SENSITIVITY, ("oxide", "chalcogenide"), "opt", (1.1, 1.8),
        0.05, 2_000, 1_729, 120, "main-result", "main-result",
    )
    protocol = {
        "schema_version": 1,
        "hypothesis_id": "H-001",
        "dataset_sha256": DATASET_SHA,
        "main_result_id": "main-result",
        "followup_result_id": "followup-result",
        "main_spec": main.to_dict(),
        "followup_spec": followup.to_dict(),
        "review_refs": ["main-result", "followup-result"],
        "explanation": "synthetic fixture",
        "holdout_split": "holdout",
        "holdout_template": "holdout_validation",
    }
    frozen_sha = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    frozen_id = "NOVA-FINAL-" + frozen_sha[:16]
    holdout_id = "NOVA-HOLDOUT-" + hashlib.sha256((RUN_ID + ":" + frozen_id).encode()).hexdigest()[:16]
    holdout = ExperimentSpec(
        1, holdout_id, main.hypothesis_id, DATASET_SHA, Split.HOLDOUT,
        Template.HOLDOUT_VALIDATION, main.groups, main.bandgap_method,
        main.gap_window_ev, main.ehull_max_ev_atom, main.bootstrap_repeats,
        main.seed, main.timeout_seconds, "followup-result", "followup-result", frozen_id,
    )
    payload = {**holdout.to_dict(), "mode": "live", "run_id": RUN_ID}

    groups, quality = _groups_and_quality()
    summaries = (
        GroupSummary.from_dict({"group": "oxide", **groups["oxide"]}),
        GroupSummary.from_dict({"group": "chalcogenide", **groups["chalcogenide"]}),
    )
    delta = 0.5
    interval = [0.32, 0.67]
    missingness = {"lower": 0.5, "upper": 0.5}
    points = [
        {
            "threshold_ev_atom": threshold,
            "groups_summary": groups,
            "delta": delta,
            "resampling_interval": interval,
            "missingness_interval": missingness,
            "quality_flags": quality,
            "scientific_status": "supported_in_snapshot",
        }
        for threshold in threshold_sensitivity.THRESHOLD_GRID_EV_ATOM
    ]
    minimal = {key: followup.to_dict()[key] for key in executor._SCIENCE_FIELDS}
    followup_science = {
        "template": "threshold_sensitivity",
        "execution_status": "success",
        "scientific_status": "supported_in_snapshot",
        "dataset_sha256": DATASET_SHA,
        "protocol_sha256": holdout_validation.PROTOCOL_SHA256,
        "extension_protocol_sha256": threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256,
        "spec_sha256": executor._computation_spec_sha256(minimal),
        "split": "discovery",
        "primary_point_index": threshold_sensitivity.PRIMARY_POINT_INDEX,
        "primary_threshold_ev_atom": 0.05,
        "main_point": points[threshold_sensitivity.PRIMARY_POINT_INDEX],
        "points": points,
    }
    quality_entry = "science-quality-json-v1:" + json.dumps(quality, sort_keys=True, separators=(",", ":"))

    def native_result(experiment_id, result_id, spec, artifact_ids=()):
        return Result(
            result_id=result_id,
            experiment_id=experiment_id,
            spec_sha256=spec.sha256,
            dataset_sha256=DATASET_SHA,
            execution_status="completed",
            scientific_status="supported_in_snapshot",
            started_at="2026-10-03T20:00:00+00:00",
            finished_at="2026-10-03T20:00:01+00:00",
            elapsed_seconds=1.0,
            groups_summary=summaries,
            delta=delta,
            resampling_interval=tuple(interval),
            missingness_interval=(0.5, 0.5),
            quality_flags=(quality_entry,),
            artifact_ids=artifact_ids,
            error=None,
        )

    main_result = native_result("main-experiment", "main-result", main)
    followup_result = native_result(
        "followup-experiment", "followup-result", followup,
        ("nova-result-payload:" + "a" * 64,),
    )
    evidence = {
        "main_result": main_result.to_dict(),
        "followup_result": followup_result.to_dict(),
        "followup_science_result": followup_science,
    }
    return protocol, payload, evidence


def _synthetic_rows():
    rows = []
    for family, n_pass in (("oxide", 8), ("chalcogenide", 20)):
        for index in range(40):
            if family == "chalcogenide" and 20 <= index < 28:
                gap, ehull = "1.3", "0.08"
            else:
                gap = "1.3" if index < n_pass else "2.1"
                ehull = "0.02"
            rows.append({
                "family": family,
                "split": "holdout",
                "excluded": "false",
                "opt_gap_ev": gap,
                "ehull_ev_atom": ehull,
                "ehull_valid": "true",
            })
    return rows


def _patch_synthetic_inputs(monkeypatch, tmp_path, protocol, payload, evidence):
    manifest = {
        "dataset": "dft_3d",
        "original_download_zip_sha256": DATASET_SHA,
        "protocol_sha256": holdout_validation.PROTOCOL_SHA256,
        "split_assignment_sha256": holdout_validation.SPLIT_ASSIGNMENT_SHA256,
        "representative_compositions_csv_sha256": holdout_validation.COMPOSITIONS_SHA256,
    }
    parent_protocol = {"protocol_id": "family_screen_v1", "dataset_sha256": DATASET_SHA}
    extension = {
        "dataset_sha256": DATASET_SHA,
        "ehull_grid_ev_atom": list(threshold_sensitivity.THRESHOLD_GRID_EV_ATOM),
    }
    monkeypatch.setattr(
        holdout_validation,
        "_verify_fixed_manifests",
        lambda: (manifest, parent_protocol, extension, threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256),
    )
    monkeypatch.setattr(
        holdout_validation.pipeline,
        "_read_prepared_compositions",
        lambda: (_synthetic_rows(), manifest, parent_protocol),
    )
    monkeypatch.setattr(executor, "PROJECT_ROOT", tmp_path)
    return evidence


def test_holdout_executor_returns_canonical_result_and_all_frozen_points(monkeypatch, tmp_path):
    protocol, payload, evidence = _canonical_results()
    _patch_synthetic_inputs(monkeypatch, tmp_path, protocol, payload, evidence)

    result = executor.execute_holdout(payload, protocol, evidence)

    assert isinstance(result, Result)
    assert result.execution_status == "completed"
    assert result.scientific_status == "replicated_in_snapshot"
    assert result.experiment_id == payload["experiment_id"]
    assert result.spec_sha256 == ExperimentSpec.from_dict({key: value for key, value in payload.items() if key not in {"mode", "run_id"}}).sha256
    assert len(result.groups_summary) == 2
    assert json.loads(result.quality_flags[0].split(":", 1)[1])["threshold_grid"][1]["replication_status"] == "replicated_in_snapshot"

    payload_id = next(item for item in result.artifact_ids if item.startswith("nova-result-payload:"))
    path_ref = next(item for item in result.artifact_ids if item.startswith("nova-artifact-path:"))
    artifact_path = tmp_path / path_ref.split(":", 1)[1]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == payload_id.split(":", 1)[1]
    science = artifact["science_result"]
    assert science["computation_spec"]["ehull_grid_ev_atom"] == [0.025, 0.05, 0.1]
    assert science["computation_spec"]["frozen_protocol_sha256"]
    assert science["computation_spec"]["holdout_implementation_sha256"] == hashlib.sha256(
        Path(holdout_validation.__file__).read_bytes()
    ).hexdigest()
    assert executor._sha256(executor._canonical_json(science["computation_spec"]).encode("utf-8")) == science["spec_sha256"]
    assert [point["threshold_ev_atom"] for point in science["points"]] == [0.025, 0.05, 0.1]
    assert all(point["replication_status"] == "replicated_in_snapshot" for point in science["points"])
    assert science["points"][0]["delta"] == science["points"][1]["delta"]
    assert science["points"][2]["delta"] > science["points"][1]["delta"]
    assert "observed representatives" in science["interpretation_scope"]


def test_invalid_holdout_parameters_fail_before_any_prepared_rows(monkeypatch):
    protocol, payload, _evidence = _canonical_results()
    monkeypatch.setattr(
        holdout_validation,
        "_verify_fixed_manifests",
        lambda: (_ for _ in ()).throw(AssertionError("manifest stage should not run")),
    )
    monkeypatch.setattr(
        holdout_validation.pipeline,
        "_read_prepared_compositions",
        lambda: (_ for _ in ()).throw(AssertionError("prepared rows must not load")),
    )
    payload["ehull_max_ev_atom"] = 0.10

    with pytest.raises(ValueError, match="differs from the parameters derived"):
        executor.execute_holdout(payload, protocol, {})


def test_discovery_grid_mismatch_fails_before_prepared_rows(monkeypatch):
    protocol, payload, evidence = _canonical_results()
    manifest = {
        "original_download_zip_sha256": DATASET_SHA,
        "protocol_sha256": holdout_validation.PROTOCOL_SHA256,
        "split_assignment_sha256": holdout_validation.SPLIT_ASSIGNMENT_SHA256,
        "representative_compositions_csv_sha256": holdout_validation.COMPOSITIONS_SHA256,
    }
    parent_protocol = {"protocol_id": "family_screen_v1", "dataset_sha256": DATASET_SHA}
    extension = {"dataset_sha256": DATASET_SHA}
    monkeypatch.setattr(
        holdout_validation,
        "_verify_fixed_manifests",
        lambda: (manifest, parent_protocol, extension, threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256),
    )
    evidence["followup_science_result"]["points"][0]["threshold_ev_atom"] = 0.03
    monkeypatch.setattr(
        holdout_validation.pipeline,
        "_read_prepared_compositions",
        lambda: (_ for _ in ()).throw(AssertionError("prepared rows must not load")),
    )

    with pytest.raises(ValueError, match="preregistered order"):
        executor.execute_holdout(payload, protocol, evidence)


def test_holdout_sample_floor_and_degeneracy_status_rules():
    too_small = [
        {"family": family, "split": "holdout", "excluded": "false", "opt_gap_ev": "1.3",
         "ehull_ev_atom": "0.02", "ehull_valid": "true"}
        for family in ("oxide", "chalcogenide")
        for _ in range(19)
    ]
    assert holdout_validation._analyze_point(too_small, 0.05)["holdout_scientific_status"] == "data_limited"

    degenerate = []
    for family, passed in (("oxide", True), ("chalcogenide", False)):
        degenerate.extend(
            {"family": family, "split": "holdout", "excluded": "false",
             "opt_gap_ev": "1.3" if passed else "2.1", "ehull_ev_atom": "0.02", "ehull_valid": "true"}
            for _ in range(40)
        )
    point = holdout_validation._analyze_point(degenerate, 0.05)
    assert point["quality_flags"]["minimum_sample_and_coverage_pass"] is True
    assert point["quality_flags"]["endpoint_non_degenerate"] is False
    assert point["holdout_scientific_status"] == "inconclusive"


@pytest.mark.parametrize(
    ("discovery_status", "discovery_delta", "holdout_status", "holdout_delta", "expected"),
    [
        ("supported_in_snapshot", 0.2, "supported_in_snapshot", 0.3, "replicated_in_snapshot"),
        ("reversed_in_snapshot", -0.2, "reversed_in_snapshot", -0.3, "replicated_in_snapshot"),
        ("supported_in_snapshot", 0.2, "reversed_in_snapshot", -0.3, "contradicted"),
        ("inconclusive", 0.2, "inconclusive", 0.1, "direction_consistent_inconclusive"),
        ("inconclusive", 0.2, "supported_in_snapshot", 0.1, "direction_consistent_inconclusive"),
        ("inconclusive", 0.2, "reversed_in_snapshot", -0.1, "inconclusive"),
        ("inconclusive", 0.2, "inconclusive", 0.0, "inconclusive"),
        ("data_limited", None, "supported_in_snapshot", 0.1, "data_limited"),
    ],
)
def test_replication_labels_follow_frozen_truth_table(
    discovery_status, discovery_delta, holdout_status, holdout_delta, expected
):
    _groups, quality = _groups_and_quality()
    holdout_point = {
        "holdout_scientific_status": holdout_status,
        "delta": holdout_delta,
        "quality_flags": quality,
    }
    assert holdout_validation._classify(discovery_status, discovery_delta, quality, holdout_point) == expected


def test_replication_quality_failure_and_missingness_scope():
    _groups, quality = _groups_and_quality()
    point = {
        "holdout_scientific_status": "supported_in_snapshot",
        "delta": 0.2,
        "quality_flags": {**quality, "missingness_bounds_cross_zero": True},
    }
    assert holdout_validation._classify("supported_in_snapshot", 0.2, quality, point) == "replicated_in_snapshot"
    failed_quality = {
        **quality,
        "oxide": {**quality["oxide"], "endpoint_has_pass_and_fail": False},
    }
    point["holdout_scientific_status"] = "inconclusive"
    point["quality_flags"] = failed_quality
    assert holdout_validation._classify("inconclusive", 0.2, quality, point) == "data_limited"
