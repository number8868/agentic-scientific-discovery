from __future__ import annotations

from typing import Any

import pytest

from nova.experiments import family_screen, threshold_sensitivity


DATASET_SHA = "f9e0a3309f0000d5de1ec9e49c93963109ea45e63f451103f8f6595d2eabf7f5"
PARENT_PROTOCOL_SHA = "9497988f1f8443f66326fa66a976d7196e5671ad320a1cce8a638780a8fc64ac"
REPRESENTATIVES_SHA = "d7184816ea97e4daa860b1a93a387b56a82280d3758eb2f658fbfa7ab021fb50"
SPLIT_SHA = "96c9c210f77698d47bfdb68f9b3ad65673766a879785a6c7d983d7ee3777a58c"


def _manifest() -> dict[str, Any]:
    return {
        "original_download_zip_sha256": DATASET_SHA,
        "protocol_sha256": PARENT_PROTOCOL_SHA,
        "representative_compositions_csv_sha256": REPRESENTATIVES_SHA,
        "split_assignment_sha256": SPLIT_SHA,
    }


def _parent_protocol() -> dict[str, Any]:
    return {
        "protocol_id": "family_screen_v1",
        "primary_endpoint": {
            "opt_gap_ev_inclusive": [1.1, 1.8],
            "ehull_ev_atom_max_inclusive": 0.05,
        },
    }


def _spec(**overrides: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "template": "threshold_sensitivity",
        "split": "discovery",
        "groups": ["oxide", "chalcogenide"],
        "bandgap_method": "opt",
        "gap_window_ev": [1.1, 1.8],
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "dataset_sha256": DATASET_SHA,
        **overrides,
    }


def _row(family: str, index: int, gap: str | None, ehull: str | None, *, ehull_valid: bool = True):
    return {
        "jid": f"{family}-{index:03d}",
        "formula": f"X{index}",
        "reduced_formula": f"X{index}",
        "elements": "Li,O" if family == "oxide" else "Li,S",
        "n_elements": "2",
        "family": family,
        "opt_gap_ev": gap,
        "mbj_gap_ev": "",
        "ehull_ev_atom": ehull,
        "ehull_valid": str(ehull_valid),
        "ehull_rounded_to_zero": "False",
        "ehull_invalid_reason": "",
        "excluded": "False",
        "exclusion_reason": "",
        "record_quality_issue": "",
        "is_representative": "True",
        "representative_reason": "frozen test representative",
        "split": "discovery",
    }


def _rows(*, oxide_base_passes: int = 19, chalcogenide_base_passes: int = 20):
    rows = []
    for family, base_passes in (
        ("oxide", oxide_base_passes),
        ("chalcogenide", chalcogenide_base_passes),
    ):
        # The first three rows sit exactly on each inclusive ehull boundary.
        rows.extend(
            [
                _row(family, 0, "1.1", "0.025"),
                _row(family, 1, "1.8", "0.05"),
                _row(family, 2, "1.8", "0.1"),
                _row(family, 3, "1.3", "0.100001"),
                _row(family, 4, None, "0.01"),
                _row(family, 5, "1.5", None, ehull_valid=False),
            ]
        )
        for index in range(6, 44):
            gap = "1.3" if index < 6 + base_passes else "2.0"
            rows.append(_row(family, index, gap, "0.05"))
    return rows


def _install_fixture(monkeypatch, rows=None):
    data = _rows() if rows is None else rows
    manifest = _manifest()
    monkeypatch.setattr(
        threshold_sensitivity,
        "_read_prepared_compositions",
        lambda: (data, manifest, _parent_protocol()),
    )
    monkeypatch.setattr(
        family_screen,
        "_read_prepared_compositions",
        lambda: (data, manifest, _parent_protocol()),
    )
    return data, manifest


def _assert_scientific_fields_equal(left, right):
    for key in (
        "scientific_status",
        "groups_summary",
        "delta",
        "resampling_interval",
        "missingness_interval",
        "quality_flags",
        "bootstrap",
    ):
        assert left[key] == right[key]


def test_every_preregistered_threshold_is_reported_with_inclusive_boundaries(monkeypatch):
    rows = []
    for family in ("oxide", "chalcogenide"):
        rows.extend(
            [
                _row(family, 0, "1.1", "0.025"),
                _row(family, 1, "1.8", "0.05"),
                _row(family, 2, "1.8", "0.1"),
                _row(family, 3, "1.3", "0.100001"),
            ]
        )
    _install_fixture(monkeypatch, rows)

    result = threshold_sensitivity.run_experiment(_spec())

    assert [point["threshold_ev_atom"] for point in result["points"]] == [0.025, 0.05, 0.1]
    for family in ("oxide", "chalcogenide"):
        assert [point["groups_summary"][family]["n_pass"] for point in result["points"]] == [1, 2, 3]
        assert [point["groups_summary"][family]["n_observed"] for point in result["points"]] == [4, 4, 4]
    assert result["primary_point_index"] == 1
    assert result["primary_threshold_ev_atom"] == 0.05
    assert "best_point" not in result


def test_unknowns_keep_constant_denominators_and_rows_are_loaded_once(monkeypatch):
    data, manifest = _install_fixture(monkeypatch)
    original_loader = threshold_sensitivity._read_prepared_compositions
    calls = 0

    def count_loader():
        nonlocal calls
        calls += 1
        return original_loader()

    monkeypatch.setattr(threshold_sensitivity, "_read_prepared_compositions", count_loader)
    result = threshold_sensitivity.run_experiment(_spec())

    assert calls == 1
    for point in result["points"]:
        for family in ("oxide", "chalcogenide"):
            group = point["groups_summary"][family]
            assert group["n_total"] == 44
            assert group["n_observed"] == 42
            assert group["coverage"] == pytest.approx(42 / 44)
        assert point["missingness_interval"] is not None
    assert result["dataset_sha256"] == manifest["original_download_zip_sha256"]


def test_primary_point_matches_family_screen_exactly(monkeypatch):
    _install_fixture(monkeypatch)
    sensitivity = threshold_sensitivity.run_experiment(_spec())
    original = family_screen.run_experiment({**_spec(), "template": "family_screen"})

    primary = sensitivity["points"][sensitivity["primary_point_index"]]
    _assert_scientific_fields_equal(primary, original)
    _assert_scientific_fields_equal(sensitivity, original)
    assert sensitivity["delta"] == original["delta"]
    assert sensitivity["resampling_interval"] == original["resampling_interval"]


def test_degenerate_endpoints_remain_inconclusive(monkeypatch):
    rows = [
        _row(family, index, "1.3", "0.01")
        for family in ("oxide", "chalcogenide")
        for index in range(40)
    ]
    _install_fixture(monkeypatch, rows)

    result = threshold_sensitivity.run_experiment(_spec())

    for point in result["points"]:
        assert point["quality_flags"]["minimum_sample_and_coverage_pass"] is True
        assert point["quality_flags"]["endpoint_non_degenerate"] is False
        assert point["scientific_status"] == "inconclusive"
        assert point["delta"] == 0.0
    assert result["scientific_status"] == "inconclusive"
    assert result["delta_direction_comparison"]["classification"] == "all_zero"


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"template": "family_screen"}, "template"),
        ({"split": "holdout"}, "split"),
        ({"gap_window_ev": [0.9, 1.6]}, "gap_window_ev"),
        ({"ehull_max_ev_atom": 0.1}, "ehull_max_ev_atom"),
        ({"dataset_sha256": "0" * 64}, "dataset_sha256"),
        ({"ehull_grid_ev_atom": [0.01, 0.05, 0.1]}, "Unknown family_screen spec fields"),
    ],
)
def test_invalid_spec_overrides_are_rejected(monkeypatch, override, match):
    _install_fixture(monkeypatch)
    with pytest.raises(ValueError, match=match):
        threshold_sensitivity.run_experiment(_spec(**override))


def test_holdout_rows_are_filtered_before_property_access(monkeypatch):
    class HoldoutCanary(dict):
        def __getitem__(self, key):
            if key in {"opt_gap_ev", "ehull_ev_atom", "ehull_valid", "excluded"}:
                raise AssertionError("holdout property was inspected")
            return super().__getitem__(key)

    rows = _rows()
    rows.append(
        HoldoutCanary(
            {
                **_row("oxide", 999, "holdout-secret-gap", "holdout-secret-ehull"),
                "split": "holdout",
            }
        )
    )
    _install_fixture(monkeypatch, rows)

    result = threshold_sensitivity.run_experiment(_spec())

    assert result["split"] == "discovery"
    assert all(point["groups_summary"]["oxide"]["n_total"] == 44 for point in result["points"])
    assert "holdout-secret" not in repr(result)


def test_direction_comparison_is_null_safe():
    points = [{"delta": 0.2}, {"delta": None}, {"delta": -0.1}]

    assert threshold_sensitivity._direction_comparison(points) == {
        "point_directions": ["positive", "unavailable", "negative"],
        "classification": "unavailable",
    }


def test_changed_extension_protocol_bytes_are_rejected(monkeypatch, tmp_path):
    changed_protocol = tmp_path / "THRESHOLD_PROTOCOL.json"
    changed_protocol.write_bytes(threshold_sensitivity.THRESHOLD_PROTOCOL_PATH.read_bytes() + b" ")
    monkeypatch.setattr(threshold_sensitivity, "THRESHOLD_PROTOCOL_PATH", changed_protocol)

    with pytest.raises(ValueError, match="protocol hash mismatch"):
        threshold_sensitivity._read_threshold_protocol()


def test_changed_parent_result_bytes_are_rejected(monkeypatch, tmp_path):
    changed_result = tmp_path / "first_family_screen.json"
    changed_result.write_bytes(b"changed result bytes")
    monkeypatch.setattr(threshold_sensitivity, "PARENT_RESULT_PATH", changed_result)
    protocol = {
        "parent_result_file": "docs/results/first_family_screen.json",
        "parent_result_sha256": threshold_sensitivity.PARENT_RESULT_SHA256,
    }

    with pytest.raises(ValueError, match="parent discovery result hash mismatch"):
        threshold_sensitivity._verify_parent_result(protocol)


def test_extension_protocol_rejects_wrong_manifest_provenance_link():
    protocol, protocol_sha256 = threshold_sensitivity._read_threshold_protocol()
    manifest = _manifest()
    manifest["split_assignment_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="split_assignment_sha256"):
        threshold_sensitivity._check_threshold_protocol(protocol, protocol_sha256, manifest)
