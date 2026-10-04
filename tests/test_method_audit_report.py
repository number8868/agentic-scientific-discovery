from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from nova.method_audit_report import AUDIT_FIELDS, write_report
from nova.experiments import method_sensitivity
from scripts import run_method_audit


def _result() -> dict:
    arms = {
        "opt_all": {
            "groups_summary": {
                "oxide": {"n_total": 2, "n_observed": 2, "n_pass": 2, "coverage": 1.0, "observed_rate": 1.0},
                "chalcogenide": {"n_total": 1, "n_observed": 1, "n_pass": 0, "coverage": 1.0, "observed_rate": 0.0},
            },
            "delta": -1.0,
            "resampling_interval": [-1.0, -1.0],
            "scientific_status": "data_limited",
            "quality_flags": {"minimum_observed_per_family": 40, "sample_gate_failed": True},
        },
        "opt_paired": {
            "groups_summary": {
                "oxide": {"n_total": 2, "n_observed": 1, "n_pass": 1, "coverage": 0.5, "observed_rate": 1.0},
                "chalcogenide": {"n_total": 1, "n_observed": 0, "n_pass": 0, "coverage": 0.0, "observed_rate": None},
            },
            "delta": None,
            "resampling_interval": None,
            "scientific_status": "data_limited",
            "quality_flags": {"paired_coverage_generalizable": False},
        },
        "mbj_paired": {
            "groups_summary": {
                "oxide": {"n_total": 2, "n_observed": 1, "n_pass": 1, "coverage": 0.5, "observed_rate": 1.0},
                "chalcogenide": {"n_total": 1, "n_observed": 0, "n_pass": 0, "coverage": 0.0, "observed_rate": None},
            },
            "delta": None,
            "resampling_interval": None,
            "scientific_status": "data_limited",
            "quality_flags": {"paired_coverage_generalizable": False},
        },
    }
    labels = (
        "passes_both_methods", "opt_only", "mbj_only", "opt_pass_mbj_unknown",
        "mbj_pass_opt_unknown", "neither_passes", "no_current_pass_incomplete_evidence",
        "insufficient_evidence",
    )
    return {
        "schema_version": 1,
        "template": "method_sensitivity",
        "execution_status": "completed",
        "split": "discovery",
        "dataset_sha256": "d" * 64,
        "parent_protocol_sha256": "p" * 64,
        "protocol_sha256": "x" * 64,
        "representative_compositions_csv_sha256": "r" * 64,
        "split_assignment_sha256": "s" * 64,
        "started_at": "2026-10-03T12:00:00Z",
        "finished_at": "2026-10-03T12:00:05Z",
        "elapsed_seconds": 5.125,
        "timing_seconds": {"load": 0.125, "compute": 5.0},
        "source_sha256": {"method_sensitivity.py": "a" * 64},
        "source_hashes": {"method_audit_report.py": "b" * 64},
        "interpretation_scope": "exploratory discovery-only; existing methods",
        "selection_mode": "human_selected",
        "no_new_model_calls": True,
        "arms": arms,
        "subset_shift": {"oxide": 0.0, "chalcogenide": None},
        "paired_method_change": {
            "groups_summary": {
                "oxide": {
                    "n_paired": 1,
                    "n_opt_pass": 1,
                    "n_mbj_pass": 1,
                    "n_gained": 0,
                    "n_lost": 0,
                    "mean_change": 0.0,
                    "resampling_interval": [0.0, 0.0],
                },
                "chalcogenide": {
                    "n_paired": 0,
                    "n_opt_pass": 0,
                    "n_mbj_pass": 0,
                    "n_gained": 0,
                    "n_lost": 0,
                    "mean_change": None,
                    "resampling_interval": None,
                },
            },
            "delta": None,
            "resampling_interval": None,
            "scientific_status": "data_limited",
            "quality_flags": [],
        },
        "transitions": {
            "oxide": {"pass_to_pass": 1, "pass_to_fail": 0, "fail_to_pass": 0, "fail_to_fail": 0},
            "chalcogenide": {"pass_to_pass": 0, "pass_to_fail": 0, "fail_to_pass": 0, "fail_to_fail": 0},
        },
        "candidate_counts": {
            label: int(label == "passes_both_methods") + int(label == "opt_pass_mbj_unknown") + int(label == "no_current_pass_incomplete_evidence")
            for label in labels
        },
        "candidate_counts_by_family": {
            "oxide": {label: int(label == "passes_both_methods") + int(label == "opt_pass_mbj_unknown") for label in labels},
            "chalcogenide": {label: int(label == "no_current_pass_incomplete_evidence") for label in labels},
        },
        "n_eligible": 3,
        "n_shortlisted": 2,
    }


def _row(
    jid: str,
    family: str,
    label: str,
    opt_status: str,
    mbj_status: str,
    *,
    shortlisted: bool,
    opt_gap: float | None,
    mbj_gap: float | None,
    paired: bool,
    reason: str = "Routine evidence",
    next_validation: str = "Check on the same representative",
) -> dict:
    return {
        "jid": jid,
        "reduced_formula": f"X{jid}",
        "family": family,
        "opt_gap_ev": opt_gap,
        "mbj_gap_ev": mbj_gap,
        "ehull_ev_atom": 0.04,
        "ehull_valid": True,
        "paired": paired,
        "opt_status": opt_status,
        "mbj_status": mbj_status,
        "candidate_label": label,
        "shortlisted": shortlisted,
        "reason": reason,
        "next_validation": next_validation,
    }


def _rows() -> list[dict]:
    return [
        _row("O-001", "oxide", "passes_both_methods", "pass", "pass", shortlisted=True, opt_gap=1.3, mbj_gap=1.4, paired=True),
        _row(
            "O-002", "oxide", "opt_pass_mbj_unknown", "pass", "unknown", shortlisted=True,
            opt_gap=1.5, mbj_gap=None, paired=False,
            reason="<script>alert(1)</script><style>body{display:none}</style>",
            next_validation="Obtain MBJ for <b>the same JID</b>",
        ),
        _row("C-001", "chalcogenide", "no_current_pass_incomplete_evidence", "fail", "unknown", shortlisted=False, opt_gap=2.0, mbj_gap=None, paired=False),
    ]


def test_full_audit_csv_keeps_unknowns_blank_and_shortlist_is_subset(tmp_path: Path):
    result = write_report(_result(), _rows(), tmp_path / "audit")

    with (result["output_dir"] / "audit_rows.csv").open(encoding="utf-8", newline="") as stream:
        all_rows = list(csv.DictReader(stream))
    with (result["output_dir"] / "candidates.csv").open(encoding="utf-8", newline="") as stream:
        candidates = list(csv.DictReader(stream))

    assert tuple(all_rows[0]) == AUDIT_FIELDS
    assert [row["jid"] for row in all_rows] == ["C-001", "O-001", "O-002"]
    assert [row["jid"] for row in candidates] == ["O-001", "O-002"]
    unknown = next(row for row in all_rows if row["jid"] == "O-002")
    assert unknown["mbj_status"] == "unknown"
    assert unknown["mbj_gap_ev"] == ""
    assert unknown["shortlisted"] == "true"
    assert all(row["jid"] != "C-001" for row in candidates)

    markdown = (result["output_dir"] / "report.md").read_text(encoding="utf-8")
    assert "observed rate" in markdown.lower()
    assert "Unknown" in markdown
    assert "paired_coverage_generalizable=false" in markdown


def test_reports_are_deterministic_and_manifest_hashes_each_output(tmp_path: Path):
    first = write_report(_result(), _rows(), tmp_path / "first")
    second = write_report(_result(), _rows(), tmp_path / "second")

    first_files = {path.name: path.read_bytes() for path in first["output_dir"].iterdir()}
    second_files = {path.name: path.read_bytes() for path in second["output_dir"].iterdir()}
    assert first_files == second_files
    manifest = json.loads(first_files["checksums.json"].decode("utf-8"))
    assert set(manifest["files"]) == set(first_files) - {"checksums.json"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256(first_files[name]).hexdigest() == digest
    aggregate = json.loads(first_files["result.json"].decode("utf-8"))
    assert "O-001" not in json.dumps(aggregate)


def test_html_escapes_injected_markup_and_has_no_external_assets(tmp_path: Path):
    result = write_report(_result(), _rows(), tmp_path / "html")
    page = (result["output_dir"] / "report.html").read_text(encoding="utf-8")

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;style&gt;body{display:none}&lt;/style&gt;" in page
    assert "&lt;b&gt;the same JID&lt;/b&gt;" in page
    assert "<script>alert(1)</script>" not in page
    assert "<style>body{display:none}</style>" not in page
    assert "https://" not in page
    assert "candidate-search" in page and "family-filter" in page and "label-filter" in page
    assert "source_hashes.method_audit_report.py" in page


def test_existing_output_path_is_refused_before_science_executor(tmp_path: Path, monkeypatch, capsys):
    existing = tmp_path / "already-there"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    calls = {"executor": 0}

    def forbidden_executor_loader():
        calls["executor"] += 1
        raise AssertionError("science executor must not be loaded for an existing path")

    monkeypatch.setattr(run_method_audit, "_load_experiment", forbidden_executor_loader)
    with pytest.raises(SystemExit) as error:
        run_method_audit.main(["--output-dir", str(existing)])

    assert error.value.code == 2
    assert calls["executor"] == 0
    assert sentinel.read_text(encoding="utf-8") == "untouched"
    assert "already exists" in capsys.readouterr().err


def test_cli_writes_report_from_returned_science_summary(tmp_path: Path, monkeypatch):
    def fake_run_experiment():
        return _result(), _rows()

    monkeypatch.setattr(run_method_audit, "_load_experiment", lambda: fake_run_experiment)
    assert run_method_audit.main(["--output-dir", str(tmp_path / "new-audit")]) == 0
    assert (tmp_path / "new-audit" / "report.html").is_file()


def test_writer_refuses_to_overwrite_existing_directory(tmp_path: Path):
    existing = tmp_path / "preserve"
    existing.mkdir()
    marker = existing / "marker"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_report(_result(), _rows(), existing)

    assert marker.read_text(encoding="utf-8") == "keep"


def test_synthetic_science_analysis_writes_through_report_schema(tmp_path: Path):
    protocol, protocol_sha256 = method_sensitivity._read_method_protocol()
    rows = [
        {
            "jid": "SYN-O-1",
            "reduced_formula": "LiO",
            "family": "oxide",
            "opt_gap_ev": 1.3,
            "mbj_gap_ev": 1.4,
            "ehull_ev_atom": 0.04,
            "ehull_valid": True,
            "split": "discovery",
            "excluded": False,
            "is_representative": True,
        },
        {
            "jid": "SYN-O-2",
            "reduced_formula": "NaO",
            "family": "oxide",
            "opt_gap_ev": 1.5,
            "mbj_gap_ev": None,
            "ehull_ev_atom": 0.04,
            "ehull_valid": True,
            "split": "discovery",
            "excluded": False,
            "is_representative": True,
        },
        {
            "jid": "SYN-C-1",
            "reduced_formula": "LiS",
            "family": "chalcogenide",
            "opt_gap_ev": 2.0,
            "mbj_gap_ev": None,
            "ehull_ev_atom": 0.04,
            "ehull_valid": True,
            "split": "discovery",
            "excluded": False,
            "is_representative": True,
        },
    ]
    analysis, audit = method_sensitivity.analyze_rows(rows, protocol)
    result = {
        "schema_version": 1,
        "template": "method_sensitivity",
        "execution_status": "synthetic_test",
        "split": "discovery",
        "dataset_sha256": "synthetic-fixture",
        "parent_protocol_sha256": "synthetic-fixture",
        "protocol_sha256": protocol_sha256,
        "representative_compositions_csv_sha256": "synthetic-fixture",
        "split_assignment_sha256": "synthetic-fixture",
        "started_at": "synthetic",
        "finished_at": "synthetic",
        "elapsed_seconds": 0.0,
        "timing_seconds": {"synthetic_analysis": 0.0},
        "source_sha256": "synthetic-fixture",
        "source_hashes": {"synthetic": "synthetic-fixture"},
        "interpretation_scope": "synthetic unit test only",
        "selection_mode": "human_selected",
        "no_new_model_calls": True,
        **analysis,
    }

    output = write_report(result, audit, tmp_path / "science-to-report")
    with (output["output_dir"] / "audit_rows.csv").open(encoding="utf-8", newline="") as stream:
        saved_rows = list(csv.DictReader(stream))
    with (output["output_dir"] / "candidates.csv").open(encoding="utf-8", newline="") as stream:
        saved_candidates = list(csv.DictReader(stream))
    saved_summary = json.loads((output["output_dir"] / "result.json").read_text(encoding="utf-8"))

    assert len(saved_rows) == analysis["n_eligible"] == 3
    assert len(saved_candidates) == analysis["n_shortlisted"] == 2
    assert [row["jid"] for row in saved_rows] == ["SYN-C-1", "SYN-O-1", "SYN-O-2"]
    assert next(row for row in saved_rows if row["jid"] == "SYN-O-2")["mbj_gap_ev"] == ""
    assert saved_summary["n_eligible"] == 3
    assert "SYN-O-1" not in (output["output_dir"] / "result.json").read_text(encoding="utf-8")
