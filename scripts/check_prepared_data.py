#!/usr/bin/env python3
"""Read-only integrity check for the prepared NOVA data handoff."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DEPENDENCIES = (
    "requirements-science.txt",
    "requirements-science-lock.txt",
)
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PreparedDataError(ValueError):
    """A concise, user-safe handoff validation failure."""


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PreparedDataError(f"missing file: {label}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise PreparedDataError(f"cannot read JSON: {label}") from None
    if not isinstance(value, dict):
        raise PreparedDataError(f"invalid JSON object: {label}")
    return value


def _expected_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HASH_PATTERN.fullmatch(value):
        raise PreparedDataError(f"invalid manifest SHA256: {label}")
    return value


def _safe_data_file(
    data_root: Path,
    manifest_value: Any,
    label: str,
    *,
    required_subdirectory: str | None = None,
) -> Path:
    if not isinstance(manifest_value, str) or not manifest_value:
        raise PreparedDataError(f"invalid manifest path: {label}")
    posix = PurePosixPath(manifest_value)
    windows = PureWindowsPath(manifest_value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise PreparedDataError(f"unsafe manifest path: {label}")

    data_root = data_root.resolve()
    expected_root = (
        (data_root / required_subdirectory).resolve()
        if required_subdirectory is not None
        else data_root
    )
    candidate = (data_root / manifest_value).resolve()
    if not _within(expected_root, data_root) or not _within(candidate, expected_root):
        raise PreparedDataError(f"unsafe manifest path: {label}")
    if not candidate.is_file():
        raise PreparedDataError(f"missing file: {label}")
    return candidate


def _safe_repo_file(repo_root: Path, relative: str, label: str) -> Path:
    repo_root = repo_root.resolve()
    candidate = (repo_root / relative).resolve()
    if not _within(candidate, repo_root):
        raise PreparedDataError(f"unsafe repository path: {label}")
    if not candidate.is_file():
        raise PreparedDataError(f"missing file: {label}")
    return candidate


def _verify_hash(path: Path, expected: Any, label: str) -> str:
    expected_hash = _expected_digest(expected, label)
    try:
        actual_hash = _sha256_file(path)
    except OSError:
        raise PreparedDataError(f"cannot read file: {label}") from None
    if actual_hash != expected_hash:
        raise PreparedDataError(f"SHA256 mismatch: {label}")
    return expected_hash


def _verify_pair(manifest: dict[str, Any], reference: dict[str, Any]) -> None:
    pairs = (
        ("dataset", "dataset"),
        ("original_download_zip_sha256", "original_download_zip_sha256"),
        ("protocol_sha256", "protocol_sha256"),
        ("representative_compositions_csv_sha256", "representative_compositions_csv_sha256"),
        ("split_assignment_sha256", "split_assignment_sha256"),
        ("cleaning_script_sha256", "cleaning_script_sha256"),
        ("dependency_spec", "dependency_spec"),
    )
    for manifest_key, reference_key in pairs:
        if manifest.get(manifest_key) != reference.get(reference_key):
            raise PreparedDataError(f"reference mismatch: {manifest_key}")


def check_prepared_data(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Verify frozen file hashes and cross-check the committed first manifest.

    CSV files are streamed only for byte hashes. Their rows and values are
    never decoded or parsed.
    """
    repo_root = Path(repo_root).resolve()
    data_root = (repo_root / "data").resolve()
    if not _within(data_root, repo_root):
        raise PreparedDataError("unsafe repository path: data directory")
    manifest_path = data_root / "manifest.json"
    manifest = _read_json(manifest_path, "data/manifest.json")
    if manifest.get("schema_version") != "nova.manifest.v1":
        raise PreparedDataError("unsupported data manifest schema")
    if manifest.get("dataset") != "dft_3d":
        raise PreparedDataError("unexpected dataset")

    file_specs = (
        ("original_download_zip", "original_download_zip_sha256", "raw"),
        ("original_inner_json", "original_inner_json_sha256", "raw"),
        ("protocol_file", "protocol_sha256", None),
        ("full_audit_csv", "full_audit_csv_sha256", "audit"),
        (
            "representative_compositions_csv",
            "representative_compositions_csv_sha256",
            "audit",
        ),
        ("metadata_file", "metadata_sha256", "audit"),
    )
    verified = []
    for path_key, digest_key, subdirectory in file_specs:
        path = _safe_data_file(
            data_root,
            manifest.get(path_key),
            path_key,
            required_subdirectory=subdirectory,
        )
        _verify_hash(path, manifest.get(digest_key), path_key)
        verified.append(path_key)

    pipeline = _safe_repo_file(repo_root, "nova/data/pipeline.py", "pipeline.py")
    _verify_hash(pipeline, manifest.get("cleaning_script_sha256"), "pipeline.py")
    verified.append("pipeline.py")

    dependency = manifest.get("dependency_spec")
    if not isinstance(dependency, dict) or not isinstance(dependency.get("files"), dict):
        raise PreparedDataError("invalid dependency specification in manifest")
    dependency_files = dependency["files"]
    if set(dependency_files) != set(EXPECTED_DEPENDENCIES):
        raise PreparedDataError("dependency specification must name both frozen files")
    for name in EXPECTED_DEPENDENCIES:
        path = _safe_repo_file(repo_root, name, name)
        _verify_hash(path, dependency_files[name], name)
        verified.append(name)

    reference_path = _safe_repo_file(
        repo_root,
        "docs/results/first_manifest.json",
        "first_manifest.json",
    )
    reference = _read_json(reference_path, "first_manifest.json")
    _verify_pair(manifest, reference)

    return {
        "status": "ready",
        "dataset": manifest["dataset"],
        "raw_record_count": manifest.get("raw_record_count"),
        "source_zip_sha256": manifest["original_download_zip_sha256"],
        "protocol_sha256": manifest["protocol_sha256"],
        "representative_compositions_csv_sha256": manifest[
            "representative_compositions_csv_sha256"
        ],
        "split_assignment_sha256": manifest["split_assignment_sha256"],
        "verified_files": verified,
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description="Verify prepared data hashes and the frozen handoff reference."
    ).parse_args(argv)
    try:
        report = check_prepared_data()
    except PreparedDataError as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
