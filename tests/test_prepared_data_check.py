from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.check_prepared_data import PreparedDataError, check_prepared_data


def _write(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _prepared_tree(root: Path) -> dict:
    files = {
        "raw/snapshot.zip": b"frozen source archive bytes",
        "raw/snapshot.json": b'{"records": "opaque"}',
        "protocol.json": b'{"protocol_id": "family_screen_v1"}\n',
        "audit/records.csv": b"record_id,value\nSECRET-HOLDOUT,never parse\n",
        "audit/compositions.csv": b"composition,split\nLiO,discovery\n",
        "audit/metadata.json": b'{"discovery": {"count": 1}}\n',
    }
    hashes = {
        name: _write(root / "data" / name, content)
        for name, content in files.items()
    }
    pipeline_sha = _write(root / "nova" / "data" / "pipeline.py", b"# frozen pipeline\n")
    dependency_hashes = {
        "requirements-science.txt": _write(
            root / "requirements-science.txt",
            b"numpy==1.0\n",
        ),
        "requirements-science-lock.txt": _write(
            root / "requirements-science-lock.txt",
            b"numpy==1.0 --hash=sha256:abc\n",
        ),
    }
    manifest = {
        "schema_version": "nova.manifest.v1",
        "dataset": "dft_3d",
        "raw_record_count": 1,
        "original_download_zip": "raw/snapshot.zip",
        "original_download_zip_sha256": hashes["raw/snapshot.zip"],
        "original_inner_json": "raw/snapshot.json",
        "original_inner_json_sha256": hashes["raw/snapshot.json"],
        "protocol_file": "protocol.json",
        "protocol_sha256": hashes["protocol.json"],
        "full_audit_csv": "audit/records.csv",
        "full_audit_csv_sha256": hashes["audit/records.csv"],
        "representative_compositions_csv": "audit/compositions.csv",
        "representative_compositions_csv_sha256": hashes["audit/compositions.csv"],
        "metadata_file": "audit/metadata.json",
        "metadata_sha256": hashes["audit/metadata.json"],
        "cleaning_script_sha256": pipeline_sha,
        "dependency_spec": {"files": dependency_hashes},
        "split_assignment_sha256": "a" * 64,
    }
    (root / "data" / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    reference = {
        key: manifest[key]
        for key in (
            "dataset",
            "original_download_zip_sha256",
            "protocol_sha256",
            "representative_compositions_csv_sha256",
            "split_assignment_sha256",
            "cleaning_script_sha256",
            "dependency_spec",
        )
    }
    reference_dir = root / "docs" / "results"
    reference_dir.mkdir(parents=True)
    (reference_dir / "first_manifest.json").write_text(
        json.dumps(reference, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def _rewrite_manifest(root: Path, manifest: dict) -> None:
    (root / "data" / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )


def test_prepared_data_check_verifies_hashes_and_emits_metadata_only(tmp_path):
    _prepared_tree(tmp_path)

    report = check_prepared_data(tmp_path)

    assert report["status"] == "ready"
    assert report["dataset"] == "dft_3d"
    assert set(report["verified_files"]) == {
        "original_download_zip",
        "original_inner_json",
        "protocol_file",
        "full_audit_csv",
        "representative_compositions_csv",
        "metadata_file",
        "pipeline.py",
        "requirements-science.txt",
        "requirements-science-lock.txt",
    }
    assert "SECRET-HOLDOUT" not in json.dumps(report)


def test_prepared_data_check_reports_missing_file_without_traceback_path(tmp_path):
    _prepared_tree(tmp_path)
    (tmp_path / "data" / "audit" / "metadata.json").unlink()

    with pytest.raises(PreparedDataError, match="missing file: metadata_file"):
        check_prepared_data(tmp_path)


def test_prepared_data_check_detects_sha_tampering(tmp_path):
    _prepared_tree(tmp_path)
    (tmp_path / "data" / "audit" / "compositions.csv").write_bytes(b"changed\n")

    with pytest.raises(PreparedDataError, match="SHA256 mismatch: representative_compositions_csv"):
        check_prepared_data(tmp_path)


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("metadata_file", "../outside.json"),
        ("original_download_zip", "C:\\outside\\snapshot.zip"),
        ("protocol_file", "/outside/protocol.json"),
    ],
)
def test_prepared_data_check_rejects_manifest_paths_outside_data_root(
    tmp_path,
    field,
    unsafe_value,
):
    manifest = _prepared_tree(tmp_path)
    manifest[field] = unsafe_value
    _rewrite_manifest(tmp_path, manifest)

    with pytest.raises(PreparedDataError, match="unsafe manifest path"):
        check_prepared_data(tmp_path)


def test_prepared_data_check_rejects_symlink_escape(tmp_path):
    _prepared_tree(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.csv"
    outside.write_bytes(b"outside")
    target = tmp_path / "data" / "audit" / "metadata.json"
    target.unlink()
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this Windows environment")

    with pytest.raises(PreparedDataError, match="unsafe manifest path"):
        check_prepared_data(tmp_path)
