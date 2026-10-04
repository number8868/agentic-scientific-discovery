from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from nova.data import pipeline
from nova.experiments import method_sensitivity


def _protocol():
    return json.loads(method_sensitivity.METHOD_PROTOCOL_PATH.read_text(encoding="utf-8"))


def _row(
    jid: str,
    *,
    family: str = "oxide",
    formula: str | None = None,
    opt: str | float | None = "1.3",
    mbj: str | float | None = "1.4",
    ehull: str | float | None = "0.01",
    ehull_valid: str | bool = "True",
    split: str = "discovery",
    excluded: str | bool = "False",
    representative: str | bool = "True",
):
    return {
        "jid": jid,
        "reduced_formula": formula or f"X{jid}",
        "family": family,
        "opt_gap_ev": opt,
        "mbj_gap_ev": mbj,
        "ehull_ev_atom": ehull,
        "ehull_valid": ehull_valid,
        "split": split,
        "excluded": excluded,
        "is_representative": representative,
    }


def _reference_interval(values: np.ndarray, replicates: int, rng: np.random.Generator):
    draws = rng.integers(0, values.size, size=(replicates, values.size))
    samples = values[draws].mean(axis=1)
    lower, upper = np.quantile(samples, [0.025, 0.975], method="linear")
    return [float(lower), float(upper)]


def _reference_delta(oxide: np.ndarray, chalc: np.ndarray, replicates: int, seed: int):
    oxide_seed, chalc_seed = np.random.SeedSequence(seed).spawn(2)
    oxide_draws = np.random.default_rng(oxide_seed).integers(
        0, oxide.size, size=(replicates, oxide.size),
    )
    chalc_draws = np.random.default_rng(chalc_seed).integers(
        0, chalc.size, size=(replicates, chalc.size),
    )
    samples = chalc[chalc_draws].mean(axis=1) - oxide[oxide_draws].mean(axis=1)
    lower, upper = np.quantile(samples, [0.025, 0.975], method="linear")
    return [float(lower), float(upper)]


def _independent_method_interval(
    endpoints: dict[str, tuple[np.ndarray, np.ndarray]], replicates: int, seed: int,
):
    streams = iter(np.random.SeedSequence(seed).spawn(4))
    changes = {}
    for family in ("oxide", "chalcogenide"):
        opt, mbj = endpoints[family]
        opt_rng = np.random.default_rng(next(streams))
        mbj_rng = np.random.default_rng(next(streams))
        opt_draws = opt_rng.integers(0, opt.size, size=(replicates, opt.size))
        mbj_draws = mbj_rng.integers(0, mbj.size, size=(replicates, mbj.size))
        changes[family] = mbj[mbj_draws].mean(axis=1) - opt[opt_draws].mean(axis=1)
    samples = changes["chalcogenide"] - changes["oxide"]
    lower, upper = np.quantile(samples, [0.025, 0.975], method="linear")
    return [float(lower), float(upper)]


def test_boundaries_unknowns_and_all_candidate_labels_are_reported():
    rows = [
        _row("00-both", opt=1.1, mbj=1.8, ehull=0.05),
        _row("01-opt", opt=1.8, mbj=2.0),
        _row("02-mbj", opt=2.0, mbj=1.1),
        _row("03-opt-mbj-unknown", opt=1.3, mbj=None),
        _row("04-mbj-opt-unknown", opt=float("nan"), mbj=1.3),
        _row("05-neither", opt=2.1, mbj=2.2),
        _row("06-fail-unknown", opt=2.0, mbj=float("inf")),
        _row("07-insufficient", opt=None, mbj="", ehull="NaN"),
    ]

    analysis, audit = method_sensitivity.analyze_rows(list(reversed(rows)), _protocol())

    by_jid = {row["jid"]: row for row in audit}
    assert by_jid["00-both"]["candidate_label"] == "passes_both_methods"
    assert by_jid["00-both"]["shortlisted"] is True
    assert by_jid["01-opt"]["candidate_label"] == "opt_only"
    assert by_jid["02-mbj"]["candidate_label"] == "mbj_only"
    assert by_jid["03-opt-mbj-unknown"]["candidate_label"] == "opt_pass_mbj_unknown"
    assert by_jid["04-mbj-opt-unknown"]["candidate_label"] == "mbj_pass_opt_unknown"
    assert by_jid["05-neither"]["candidate_label"] == "neither_passes"
    assert by_jid["06-fail-unknown"]["candidate_label"] == "no_current_pass_incomplete_evidence"
    assert by_jid["07-insufficient"]["candidate_label"] == "insufficient_evidence"
    assert by_jid["00-both"]["opt_status"] == "pass"
    assert by_jid["00-both"]["mbj_status"] == "pass"
    assert by_jid["04-mbj-opt-unknown"]["opt_gap_ev"] is None
    assert by_jid["04-mbj-opt-unknown"]["paired"] is False
    assert by_jid["07-insufficient"]["ehull_ev_atom"] is None
    assert by_jid["01-opt"]["reason"].startswith("OPT: gap within inclusive frozen window")
    assert list(analysis["candidate_counts"]) == list(_protocol()["candidate_labels"])
    assert all(label in analysis["candidate_counts"] for label in _protocol()["candidate_labels"])
    assert analysis["candidate_counts"]["passes_both_methods"] == 1
    assert analysis["n_shortlisted"] == 5
    assert [row["jid"] for row in audit] == sorted(row["jid"] for row in audit)
    assert json.dumps(analysis, allow_nan=False)


def test_metadata_filters_run_before_any_property_access():
    class PropertyCanary(dict):
        def __getitem__(self, key):
            if key in {"opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom", "ehull_valid"}:
                raise AssertionError(f"property field inspected: {key}")
            return super().__getitem__(key)

        def get(self, key, default=None):
            if key in {"opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom", "ehull_valid"}:
                raise AssertionError(f"property field inspected: {key}")
            return super().get(key, default)

    class HoldoutCanary(dict):
        def __getitem__(self, key):
            if key != "split":
                raise AssertionError(f"holdout field inspected: {key}")
            return super().__getitem__(key)

    class NonRepresentativeCanary(dict):
        def __getitem__(self, key):
            if key in {"family", "jid", "reduced_formula", "opt_gap_ev", "mbj_gap_ev", "ehull_ev_atom"}:
                raise AssertionError(f"nonrepresentative field inspected: {key}")
            return super().__getitem__(key)

    rows = [
        _row("kept", opt="1.3", mbj=None),
        PropertyCanary(_row("excluded", excluded="True")),
        HoldoutCanary({"split": "holdout"}),
        NonRepresentativeCanary(_row("not-representative", representative="False")),
        PropertyCanary(_row("other-family", family="other")),
    ]

    analysis, audit = method_sensitivity.analyze_rows(rows, _protocol())

    assert [row["jid"] for row in audit] == ["kept"]
    assert analysis["n_eligible"] == 1


@pytest.mark.parametrize(
    ("second", "message"),
    [
        (_row("same-jid", formula="LiO2"), "Duplicate eligible JID"),
        (_row("second-jid", formula="LiO"), "Duplicate eligible family/reduced_formula"),
    ],
)
def test_duplicate_jid_or_family_formula_is_rejected(second, message):
    rows = [_row("same-jid", formula="LiO"), second]
    with pytest.raises(ValueError, match=message):
        method_sensitivity.analyze_rows(rows, _protocol())


def test_same_jid_pairing_does_not_coalesce_separate_method_rows():
    rows = [
        _row("opt-record", formula="LiO", opt=1.3, mbj=None),
        _row("mbj-record", formula="NaO", opt=None, mbj=1.3),
    ]

    analysis, audit = method_sensitivity.analyze_rows(rows, _protocol())

    assert all(row["paired"] is False for row in audit)
    assert analysis["arms"]["opt_all"]["groups_summary"]["oxide"]["n_observed"] == 1
    assert analysis["arms"]["opt_paired"]["groups_summary"]["oxide"]["n_observed"] == 0
    assert analysis["arms"]["mbj_paired"]["groups_summary"]["oxide"]["n_observed"] == 0
    assert analysis["paired_method_change"]["groups_summary"]["oxide"]["n_paired"] == 0


def test_opt_all_and_paired_subset_use_distinct_denominators_and_descriptive_shift():
    rows = [
        _row("paired-pass", formula="A", opt=1.3, mbj=1.4),
        _row("paired-fail", formula="B", opt=2.0, mbj=2.1),
        _row("opt-pass-missing-mbj", formula="C", opt=1.4, mbj=None),
    ]

    analysis, _ = method_sensitivity.analyze_rows(rows, _protocol())
    all_opt = analysis["arms"]["opt_all"]["groups_summary"]["oxide"]
    paired_opt = analysis["arms"]["opt_paired"]["groups_summary"]["oxide"]

    assert all_opt["n_total"] == paired_opt["n_total"] == 3
    assert all_opt["n_observed"] == 3
    assert paired_opt["n_observed"] == 2
    assert all_opt["observed_rate"] == pytest.approx(2 / 3)
    assert paired_opt["observed_rate"] == pytest.approx(1 / 2)
    assert analysis["subset_shift"]["oxide"] == pytest.approx(-1 / 6)


def test_signed_paired_change_bootstrap_matches_joint_row_resampling_reference():
    rows = []
    signed_changes = {
        "oxide": [-1, 0, 1, 1],
        "chalcogenide": [1, 1, -1, -1],
    }
    for family in ("oxide", "chalcogenide"):
        for index, change in enumerate(signed_changes[family]):
            opt_pass = change == -1 or (change == 0 and index % 2 == 0)
            mbj_pass = opt_pass if change == 0 else (change == 1)
            rows.append(_row(
                f"{family}-{index}", family=family, formula=f"{family}-{index}",
                opt=1.3 if opt_pass else 2.0,
                mbj=1.3 if mbj_pass else 2.0,
            ))

    analysis, _ = method_sensitivity.analyze_rows(rows, _protocol())
    paired = analysis["paired_method_change"]
    reps = _protocol()["bootstrap_repeats"]
    seed = _protocol()["seed"]
    oxide = np.asarray(signed_changes["oxide"], dtype=np.int8)
    chalc = np.asarray(signed_changes["chalcogenide"], dtype=np.int8)
    endpoint_arrays = {}
    for family in ("oxide", "chalcogenide"):
        family_rows = [row for row in rows if row["family"] == family]
        endpoint_arrays[family] = (
            np.asarray([float(row["opt_gap_ev"]) <= 1.8 for row in family_rows], dtype=np.int8),
            np.asarray([float(row["mbj_gap_ev"]) <= 1.8 for row in family_rows], dtype=np.int8),
        )

    assert paired["groups_summary"]["oxide"]["mean_change"] == pytest.approx(oxide.mean())
    assert paired["groups_summary"]["chalcogenide"]["mean_change"] == pytest.approx(chalc.mean())
    assert paired["groups_summary"]["oxide"]["resampling_interval"] == _reference_interval(
        oxide, reps, np.random.default_rng(np.random.SeedSequence(seed).spawn(2)[0]),
    )
    assert paired["delta"] == pytest.approx(chalc.mean() - oxide.mean())
    assert paired["resampling_interval"] == _reference_delta(oxide, chalc, reps, seed)
    assert paired["resampling_interval"] != _independent_method_interval(endpoint_arrays, reps, seed)
    assert paired["groups_summary"]["oxide"]["n_gained"] == 2
    assert paired["groups_summary"]["oxide"]["n_lost"] == 1
    assert json.dumps(analysis, allow_nan=False)


def test_low_paired_coverage_is_reported_without_gating_conditional_analysis():
    rows = []
    for family in ("oxide", "chalcogenide"):
        for index in range(100):
            passed = index % 2 == 0
            paired = index < 20
            rows.append(_row(
                f"{family}-{index:03d}", family=family, formula=f"{family}-{index}",
                opt=1.3 if passed else 2.0,
                mbj=(1.3 if passed else 2.0) if paired else None,
            ))

    analysis, _ = method_sensitivity.analyze_rows(rows, _protocol())
    paired_opt = analysis["arms"]["opt_paired"]

    assert paired_opt["groups_summary"]["oxide"]["coverage"] == pytest.approx(0.2)
    assert paired_opt["quality_flags"]["oxide"]["minimum_evaluable_count_pass"] is True
    assert paired_opt["quality_flags"]["oxide"]["minimum_coverage_pass"] is None
    assert paired_opt["scientific_status"] == "inconclusive"
    assert analysis["paired_method_change"]["quality_flags"]["minimum_paired_rows_pass"] is True


def test_degenerate_endpoints_and_constant_paired_changes_are_inconclusive():
    rows = []
    for family in ("oxide", "chalcogenide"):
        for index in range(40):
            rows.append(_row(
                f"{family}-{index:03d}", family=family, formula=f"{family}-{index}",
                opt="1.3", mbj="1.4",
            ))

    analysis, _ = method_sensitivity.analyze_rows(rows, _protocol())

    assert analysis["arms"]["opt_all"]["quality_flags"]["minimum_sample_and_coverage_pass"] is True
    assert analysis["arms"]["opt_all"]["quality_flags"]["endpoint_non_degenerate"] is False
    assert analysis["arms"]["opt_all"]["scientific_status"] == "inconclusive"
    paired = analysis["paired_method_change"]
    assert paired["quality_flags"]["minimum_paired_rows_pass"] is True
    assert paired["quality_flags"]["paired_differences_nonconstant"] is False
    assert paired["scientific_status"] == "inconclusive"
    assert paired["delta"] == 0.0
    assert paired["resampling_interval"] == [0.0, 0.0]


@pytest.mark.parametrize(
    ("direction", "expected_status"),
    [(1, "direction_positive"), (-1, "direction_negative")],
)
def test_paired_method_change_preserves_signed_scale_beyond_one(direction, expected_status):
    rows = []
    for family, change in (("oxide", -direction), ("chalcogenide", direction)):
        for index in range(20):
            row_change = change if index < 18 else 0
            if row_change == -1:
                opt_pass, mbj_pass = True, False
            elif row_change == 1:
                opt_pass, mbj_pass = False, True
            else:
                opt_pass = index == 18
                mbj_pass = opt_pass
            rows.append(_row(
                f"{family}-{index:03d}", family=family, formula=f"{family}-{index}",
                opt="1.3" if opt_pass else "2.0",
                mbj="1.3" if mbj_pass else "2.0",
            ))

    analysis, _ = method_sensitivity.analyze_rows(rows, _protocol())
    paired = analysis["paired_method_change"]

    assert paired["delta"] == pytest.approx(1.8 * direction)
    assert paired["scientific_status"] == expected_status
    assert paired["quality_flags"]["paired_differences_nonconstant"] is True
    if direction > 0:
        assert paired["resampling_interval"][0] > 0
    else:
        assert paired["resampling_interval"][1] < 0


def test_protocol_tamper_is_rejected_before_prepared_loader(monkeypatch):
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp_dir:
        changed = Path(temp_dir) / "tampered.json"
        changed.write_bytes(method_sensitivity.METHOD_PROTOCOL_PATH.read_bytes() + b" ")
        monkeypatch.setattr(method_sensitivity, "METHOD_PROTOCOL_PATH", changed)
        monkeypatch.setattr(
            pipeline,
            "_read_prepared_compositions",
            lambda: pytest.fail("prepared loader ran before frozen protocol hash validation"),
        )

        with pytest.raises(ValueError, match="protocol hash mismatch"):
            method_sensitivity.run_experiment()


def test_manifest_link_mismatch_is_rejected_before_analysis(monkeypatch):
    protocol = _protocol()
    manifest = {
        "original_download_zip_sha256": protocol["dataset_sha256"],
        "protocol_sha256": protocol["parent_protocol_sha256"],
        "representative_compositions_csv_sha256": protocol["representative_compositions_csv_sha256"],
        "split_assignment_sha256": "0" * 64,
    }
    monkeypatch.setattr(pipeline, "_read_prepared_compositions", lambda: ([], manifest, {}))
    monkeypatch.setattr(
        method_sensitivity,
        "analyze_rows",
        lambda *_args: pytest.fail("analysis ran before frozen input links were checked"),
    )

    with pytest.raises(ValueError, match="split_assignment_sha256"):
        method_sensitivity.run_experiment()


def test_run_wrapper_uses_only_synthetic_empty_rows_and_reports_provenance(monkeypatch):
    protocol = _protocol()
    manifest = {
        "original_download_zip_sha256": protocol["dataset_sha256"],
        "protocol_sha256": protocol["parent_protocol_sha256"],
        "representative_compositions_csv_sha256": protocol["representative_compositions_csv_sha256"],
        "split_assignment_sha256": protocol["split_assignment_sha256"],
    }
    monkeypatch.setattr(pipeline, "_read_prepared_compositions", lambda: ([], manifest, {}))

    result, audit = method_sensitivity.run_experiment()

    assert audit == []
    assert result["execution_status"] == "success"
    assert result["selection_mode"] == "human_selected"
    assert result["no_new_model_calls"] is True
    assert result["protocol_sha256"] == hashlib.sha256(
        method_sensitivity.METHOD_PROTOCOL_PATH.read_bytes(),
    ).hexdigest()
    assert set(result["source_hashes"]) == {
        "nova/experiments/method_sensitivity.py",
        "nova/statistics.py",
        "nova/data/pipeline.py",
    }
    assert result["timing_seconds"]["total"] == result["elapsed_seconds"]
