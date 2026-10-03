from __future__ import annotations

import pytest

from nova.data.pipeline import _assign_splits, _json_bytes, _normalize_record, _representatives
from nova.experiments import family_screen
from nova.statistics import bootstrap_difference, missingness_difference


def record(jid: str, elements: list[str], ehull, gap, *, mbj=None):
    return {
        "jid": jid,
        "atoms": {"elements": elements},
        "ehull": ehull,
        "optb88vdw_bandgap": gap,
        "mbj_bandgap": mbj,
    }


def normalized(*items):
    return [_normalize_record(item) for item in items]


def test_representative_selection_uses_ehull_before_gap_and_jid_ties():
    rows = normalized(
        record("JVASP-9", ["Li", "O"], 0.04, 1.4),
        record("JVASP-2", ["Li", "O"], 0.02, None),
        record("JVASP-1", ["Li", "O"], 0.02, 1.5),
    )
    _representatives(rows)
    representative = next(row for row in rows if row["is_representative"])
    assert representative["jid"] == "JVASP-1"
    assert representative["opt_gap_ev"] == 1.5

    missing_gap_rows = normalized(
        record("JVASP-8", ["Na", "O"], 0.01, 1.5),
        record("JVASP-3", ["Na", "O"], 0.0, None),
    )
    _representatives(missing_gap_rows)
    assert next(row for row in missing_gap_rows if row["is_representative"])["jid"] == "JVASP-3"


def test_all_invalid_ehull_keeps_lowest_jid_as_unevaluable():
    rows = normalized(
        record("JVASP-7", ["Li", "S"], -0.01, 1.4),
        record("JVASP-2", ["Li", "S"], None, 1.5),
    )
    _representatives(rows)
    representative = next(row for row in rows if row["is_representative"])
    assert representative["jid"] == "JVASP-2"
    assert representative["ehull_valid"] is False
    assert representative["opt_gap_ev"] == 1.5


def test_zero_gap_is_observed_and_small_negative_ehull_rounds_to_zero():
    row = _normalize_record(record("JVASP-10", ["Li", "O"], "-0.0000005", "0"))
    assert row["opt_gap_ev"] == 0.0
    assert row["ehull_ev_atom"] == 0.0
    assert row["ehull_rounded_to_zero"] is True
    csv_row = {key: str(value) if isinstance(value, bool) else value for key, value in row.items()}
    summary, endpoints = family_screen._group([{**csv_row, "split": "discovery"}], "oxide")
    assert summary["n_total"] == 1
    assert summary["n_observed"] == 1
    assert summary["n_pass"] == 0
    assert endpoints == [0]


def test_more_negative_ehull_is_invalid_and_never_a_pass():
    row = _normalize_record(record("JVASP-11", ["Li", "Se"], -0.0000011, 1.4))
    assert row["ehull_valid"] is False
    assert row["ehull_ev_atom"] is None
    assert row["ehull_invalid_reason"] == "below_minus_1e-6_ev_per_atom"


def test_nonfinite_source_values_have_valid_canonical_serialization():
    import json

    serialized = _json_bytes({"NaN": float("nan"), "positive_infinity": float("inf"), "finite": 1.25})
    assert json.loads(serialized) == {"NaN": None, "positive_infinity": None, "finite": 1.25}


@pytest.mark.parametrize(
    ("elements", "expected"),
    [
        (["Li", "O"], "oxide"),
        (["Li", "O", "S"], "other"),
        (["Li", "S"], "chalcogenide"),
        (["Li", "Se", "S"], "chalcogenide"),
        (["Li", "S", "Cl"], "other"),
        (["Li", "N", "O"], "other"),
    ],
)
def test_family_definition_is_mutually_exclusive(elements, expected):
    assert _normalize_record(record("JVASP-20", elements, 0.02, 1.3))["family"] == expected


def test_chemical_exclusions_are_design_rules_and_formula_split_never_leaks():
    rows = normalized(
        record("JVASP-1", ["Li", "O"], 0.02, 1.3),
        record("JVASP-2", ["Li", "O", "Li", "O"], 0.03, 1.4),
        record("JVASP-3", ["Pb", "O"], 0.01, 1.5),
        record("JVASP-4", ["O"], 0.01, 1.5),
    )
    assignments = _assign_splits(rows)
    assert len({row["split"] for row in rows[:2]}) == 1
    assert rows[2]["excluded"] is True
    assert rows[3]["excluded"] is True
    assert len(assignments) == 1


def test_bootstrap_repeats_exactly_and_flags_degenerate_endpoints():
    first = bootstrap_difference([0, 1, 0, 1], [1, 1, 0, 1], replicates=2_000, seed=1729)
    second = bootstrap_difference([0, 1, 0, 1], [1, 1, 0, 1], replicates=2_000, seed=1729)
    assert first == second
    assert first["delta"] == pytest.approx(0.25)
    assert first["family_endpoint_degenerate"] == {"oxide": False, "chalcogenide": False}

    degenerate = bootstrap_difference([0, 0], [1, 1], replicates=100, seed=3)
    assert degenerate["bootstrap_degenerate"] is True
    assert degenerate["family_endpoint_degenerate"] == {"oxide": True, "chalcogenide": True}


def test_missingness_interval_uses_all_compositions_and_checks_zero_denominators():
    interval = missingness_difference(
        oxide_total=10, oxide_pass=2, oxide_observed=8,
        chalcogenide_total=20, chalcogenide_pass=4, chalcogenide_observed=15,
    )
    assert interval["oxide_rate_lower"] == pytest.approx(0.2)
    assert interval["oxide_rate_upper"] == pytest.approx(0.4)
    assert interval["chalcogenide_rate_lower"] == pytest.approx(0.2)
    assert interval["chalcogenide_rate_upper"] == pytest.approx(0.45)
    assert interval["lower"] == pytest.approx(-0.2)
    assert interval["upper"] == pytest.approx(0.25)
    assert missingness_difference(
        oxide_total=0, oxide_pass=0, oxide_observed=0,
        chalcogenide_total=20, chalcogenide_pass=4, chalcogenide_observed=15,
    ) is None
    with pytest.raises(ValueError):
        missingness_difference(
            oxide_total=0, oxide_pass=1, oxide_observed=0,
            chalcogenide_total=20, chalcogenide_pass=4, chalcogenide_observed=15,
        )


def test_screen_spec_requires_complete_fixed_discovery_protocol():
    protocol = {
        "protocol_id": "family_screen_v1",
        "primary_endpoint": {
            "opt_gap_ev_inclusive": [1.1, 1.8],
            "ehull_ev_atom_max_inclusive": 0.05,
        },
    }
    manifest = {"original_download_zip_sha256": "a" * 64}
    spec = {
        "schema_version": 1,
        "template": "family_screen",
        "split": "discovery",
        "groups": ["oxide", "chalcogenide"],
        "bandgap_method": "opt",
        "gap_window_ev": [1.1, 1.8],
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "dataset_sha256": "a" * 64,
    }
    assert family_screen._check_spec(spec, protocol, manifest) == spec
    with pytest.raises(ValueError, match="gap_window_ev"):
        family_screen._check_spec({**spec, "gap_window_ev": [0.9, 1.6]}, protocol, manifest)
    with pytest.raises(ValueError, match="discovery"):
        family_screen._check_spec({**spec, "split": "holdout"}, protocol, manifest)
    with pytest.raises(ValueError, match="dataset_sha256"):
        family_screen._check_spec({**spec, "dataset_sha256": "b" * 64}, protocol, manifest)
    with pytest.raises(ValueError, match="integer"):
        family_screen._check_spec({**spec, "schema_version": True}, protocol, manifest)


def test_screen_with_empty_groups_is_data_limited_and_null_not_zero(monkeypatch):
    protocol = {
        "protocol_id": "family_screen_v1",
        "primary_endpoint": {
            "opt_gap_ev_inclusive": [1.1, 1.8],
            "ehull_ev_atom_max_inclusive": 0.05,
        },
    }
    manifest = {
        "original_download_zip_sha256": "a" * 64,
        "protocol_sha256": "c" * 64,
        "representative_compositions_csv_sha256": "d" * 64,
    }
    monkeypatch.setattr(family_screen, "_read_prepared_compositions", lambda: ([], manifest, protocol))
    result = family_screen.run_experiment({
        "schema_version": 1,
        "template": "family_screen",
        "split": "discovery",
        "groups": ["oxide", "chalcogenide"],
        "bandgap_method": "opt",
        "gap_window_ev": [1.1, 1.8],
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "dataset_sha256": "a" * 64,
    })
    assert result["scientific_status"] == "data_limited"
    assert result["groups_summary"]["oxide"]["observed_rate"] is None
    assert result["groups_summary"]["oxide"]["coverage"] is None
    assert result["resampling_interval"] is None
    assert result["error"] is None


def _screen_rows(oxide_pass: int, chalcogenide_pass: int, n_each: int = 40):
    rows = []
    for family, n_pass in (("oxide", oxide_pass), ("chalcogenide", chalcogenide_pass)):
        for index in range(n_each):
            passed = index < n_pass
            rows.append({
                "jid": f"{family}-{index:03d}",
                "formula": f"X{index}",
                "reduced_formula": f"X{index}",
                "elements": "Li,O" if family == "oxide" else "Li,S",
                "n_elements": "2",
                "family": family,
                "opt_gap_ev": "1.3" if passed else "2.0",
                "mbj_gap_ev": "",
                "ehull_ev_atom": "0.01",
                "ehull_valid": "True",
                "ehull_rounded_to_zero": "False",
                "ehull_invalid_reason": "",
                "excluded": "False",
                "exclusion_reason": "",
                "record_quality_issue": "",
                "is_representative": "True",
                "representative_reason": "test fixture",
                "split": "discovery",
            })
    return rows


def _screen_fixture(monkeypatch, *, oxide_pass: int, chalcogenide_pass: int):
    dataset_sha = "a" * 64
    protocol_sha = "b" * 64
    protocol = {
        "protocol_id": "family_screen_v1",
        "primary_endpoint": {
            "opt_gap_ev_inclusive": [1.1, 1.8],
            "ehull_ev_atom_max_inclusive": 0.05,
        },
    }
    manifest = {
        "original_download_zip_sha256": dataset_sha,
        "protocol_sha256": protocol_sha,
        "representative_compositions_csv_sha256": "c" * 64,
    }
    monkeypatch.setattr(
        family_screen,
        "_read_prepared_compositions",
        lambda: (_screen_rows(oxide_pass, chalcogenide_pass), manifest, protocol),
    )
    spec = {
        "schema_version": 1,
        "template": "family_screen",
        "split": "discovery",
        "groups": ["oxide", "chalcogenide"],
        "bandgap_method": "opt",
        "gap_window_ev": [1.1, 1.8],
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "dataset_sha256": dataset_sha,
    }
    return spec


def test_run_classifies_good_quality_degenerate_endpoints_as_inconclusive(monkeypatch):
    spec = _screen_fixture(monkeypatch, oxide_pass=40, chalcogenide_pass=40)
    result = family_screen.run_experiment(spec)
    assert result["groups_summary"]["oxide"]["coverage"] == 1.0
    assert result["groups_summary"]["oxide"]["n_observed"] == 40
    assert result["groups_summary"]["chalcogenide"]["n_observed"] == 40
    assert result["scientific_status"] == "inconclusive"
    assert result["quality_flags"]["endpoint_non_degenerate"] is False


def test_run_interval_touching_zero_is_inconclusive(monkeypatch):
    spec = _screen_fixture(monkeypatch, oxide_pass=20, chalcogenide_pass=20)
    monkeypatch.setattr(
        family_screen,
        "bootstrap_difference",
        lambda *args, **kwargs: {
            "delta": 0.0,
            "resampling_interval": [0.0, 0.1],
            "replicates": 2_000,
            "seed": 1_729,
            "interval_method": "test boundary",
            "bootstrap_degenerate": False,
            "family_endpoint_degenerate": {"oxide": False, "chalcogenide": False},
        },
    )
    result = family_screen.run_experiment(spec)
    assert result["quality_flags"]["minimum_sample_and_coverage_pass"] is True
    assert result["quality_flags"]["endpoint_non_degenerate"] is True
    assert result["resampling_interval"] == [0.0, 0.1]
    assert result["scientific_status"] == "inconclusive"


@pytest.mark.parametrize(
    ("oxide_pass", "chalcogenide_pass", "expected"),
    [(10, 30, "supported_in_snapshot"), (30, 10, "reversed_in_snapshot")],
)
def test_run_classifies_clear_non_degenerate_direction(monkeypatch, oxide_pass, chalcogenide_pass, expected):
    spec = _screen_fixture(monkeypatch, oxide_pass=oxide_pass, chalcogenide_pass=chalcogenide_pass)
    result = family_screen.run_experiment(spec)
    assert result["quality_flags"]["minimum_sample_and_coverage_pass"] is True
    assert result["quality_flags"]["endpoint_non_degenerate"] is True
    assert result["resampling_interval"][0] != 0.0
    assert result["scientific_status"] == expected
