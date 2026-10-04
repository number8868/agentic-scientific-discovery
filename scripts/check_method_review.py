#!/usr/bin/env python3
"""Prepare or validate a structured method review from an exported package.

This command is deliberately offline: it reads only ``manifest.json``,
``method-audit.json``, and ``method-evidence.json`` from an existing package.
It does not call a model, open a run database, or execute scientific work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_FILENAMES = ("manifest.json", "method-audit.json", "method-evidence.json")


class ReviewCliError(ValueError):
    """A concise, safe-to-display CLI validation error."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewCliError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(_token: str) -> None:
    raise ReviewCliError("JSON contains a non-finite number")


def _finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ReviewCliError("JSON contains a non-finite number")
    return value


def _decode_json(data: bytes, description: str) -> Any:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReviewCliError(f"{description} is not valid UTF-8 JSON") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except ReviewCliError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ReviewCliError(f"{description} is not valid JSON") from exc


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReviewCliError("review data cannot be serialized as finite JSON") from exc
    return (text + "\n").encode("utf-8")


def _has_reparse_attribute(info: os.stat_result) -> bool:
    # Windows junctions and other reparse points can redirect paths without
    # reporting as POSIX symlinks. Treat them as unsafe path components too.
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(info, "st_file_attributes", 0) & reparse_flag)


def _absolute_user_path(value: str | Path, label: str, *, relative_to: Path | None = None) -> Path:
    raw = Path(value)
    if ".." in raw.parts:
        raise ReviewCliError(f"{label} path may not contain '..'")
    if relative_to is not None and not raw.is_absolute():
        raw = relative_to / raw
    try:
        return Path(os.path.abspath(raw))
    except (OSError, ValueError) as exc:
        raise ReviewCliError(f"invalid {label} path") from exc


def _reject_symlink_components(path: Path, label: str) -> None:
    """Reject symlink/reparse points in every existing component of a path."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ReviewCliError(f"cannot inspect {label} path") from exc
        if stat.S_ISLNK(info.st_mode) or _has_reparse_attribute(info):
            raise ReviewCliError(f"{label} path may not contain symlinks or reparse points")


def _read_regular_file(path: Path, label: str) -> bytes:
    _reject_symlink_components(path, label)
    try:
        info = path.lstat()
    except OSError as exc:
        raise ReviewCliError(f"{label} file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ReviewCliError(f"{label} must be a regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ReviewCliError(f"cannot read {label} file") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(value: Any) -> bool:
    return isinstance(value, dict)


def _load_evidence_package(evidence_dir: str | Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Read and verify exactly the manifest and two exported method files."""
    package_dir = _absolute_user_path(evidence_dir, "evidence directory")
    _reject_symlink_components(package_dir, "evidence directory")
    try:
        if not stat.S_ISDIR(package_dir.lstat().st_mode):
            raise ReviewCliError("evidence directory must be a regular directory")
    except OSError as exc:
        raise ReviewCliError("evidence directory is unavailable") from exc

    # Keep this read list literal and narrow. Manifest paths never decide what
    # the CLI opens, so unrelated run results and event/science files stay shut.
    raw: dict[str, bytes] = {}
    parsed: dict[str, Any] = {}
    for filename in SOURCE_FILENAMES:
        data = _read_regular_file(package_dir / filename, filename)
        raw[filename] = data
        parsed[filename] = _decode_json(data, filename)
        if not _object(parsed[filename]):
            raise ReviewCliError(f"{filename} must contain a JSON object")

    manifest = parsed["manifest.json"]
    body = parsed["method-audit.json"]
    packet = parsed["method-evidence.json"]
    files = manifest.get("files")
    method_manifest = manifest.get("method_audit")
    if not _object(files) or not _object(method_manifest):
        raise ReviewCliError("package manifest is missing method evidence integrity fields")

    audit_sha = _sha256(raw["method-audit.json"])
    for filename in ("method-audit.json", "method-evidence.json"):
        entry = files.get(filename)
        if not _object(entry) or entry.get("sha256") != _sha256(raw[filename]):
            raise ReviewCliError("method evidence file digest does not match package manifest")
    if method_manifest.get("evidence_file") != "method-audit.json":
        raise ReviewCliError("package manifest points to an unexpected evidence file")
    if method_manifest.get("citations_file") != "method-evidence.json":
        raise ReviewCliError("package manifest points to an unexpected citation file")
    if method_manifest.get("evidence_sha256") != audit_sha:
        raise ReviewCliError("package manifest evidence digest does not match method audit")
    request = body.get("request")
    registered = body.get("registered_execution")
    if not _object(request) or not _object(registered):
        raise ReviewCliError("method audit is missing source ownership metadata")
    audit_id = method_manifest.get("audit_id")
    run_id = manifest.get("run_id")
    if (not audit_id or method_manifest.get("audit_id") != request.get("audit_id")
            or method_manifest.get("audit_id") != registered.get("audit_id")):
        raise ReviewCliError("package manifest audit identity does not match method audit")
    if (not run_id or run_id != request.get("run_id") or run_id != registered.get("run_id")):
        raise ReviewCliError("package manifest run identity does not match method audit")
    if packet.get("evidence_file") != "method-audit.json" or packet.get("evidence_sha256") != audit_sha:
        raise ReviewCliError("method evidence packet digest does not match method audit")
    references = packet.get("references")
    if not isinstance(references, list) or any(
        not _object(reference) or reference.get("evidence_sha256") != audit_sha
        for reference in references
    ):
        raise ReviewCliError("method evidence references do not match the verified audit")
    return body, packet, {
        "audit_sha256": audit_sha,
        "evidence_packet_sha256": _sha256(raw["method-evidence.json"]),
        "package_manifest_sha256": _sha256(raw["manifest.json"]),
        "audit_id": audit_id,
        "run_id": run_id,
    }


def _validate_selection(candidate_jids: list[str] | None, available_actions: list[str] | None) -> tuple[list[str] | None, list[str]]:
    if candidate_jids is not None:
        if any(not item or item.strip() != item for item in candidate_jids):
            raise ReviewCliError("candidate JIDs must be nonempty and have no surrounding whitespace")
        if len(set(candidate_jids)) != len(candidate_jids):
            raise ReviewCliError("candidate JIDs must be unique")
    actions = list(available_actions) if available_actions is not None else []
    if len(set(actions)) != len(actions):
        raise ReviewCliError("available actions must be unique")
    if "stop" not in actions:
        actions.insert(0, "stop")
    return candidate_jids, actions


def _review_api():
    """Import only the pure contract module after package bytes are verified."""
    try:
        from nova.method_review import (  # type: ignore[import-not-found]
            build_method_review_input,
            method_review_output_schema,
            validate_method_review,
        )
    except ImportError as exc:
        raise ReviewCliError("method review contract module is unavailable") from exc
    return build_method_review_input, method_review_output_schema, validate_method_review


def _build_input(body: dict[str, Any], packet: dict[str, Any], candidate_jids: list[str] | None,
                 available_actions: list[str]) -> dict[str, Any]:
    build_method_review_input, _, _ = _review_api()
    try:
        value = build_method_review_input(
            body,
            packet,
            candidate_jids=candidate_jids,
            available_actions=tuple(available_actions),
        )
    except (ValueError, TypeError, KeyError) as exc:
        # API exception text can contain user-supplied content; keep CLI errors safe.
        raise ReviewCliError("verified package does not satisfy the method review input contract") from exc
    if not _object(value):
        raise ReviewCliError("method review input builder returned an invalid value")
    return value


def _selection_disclosure(review_input: dict[str, Any], candidate_jids: list[str] | None,
                          available_actions: list[str]) -> dict[str, Any]:
    selection = review_input.get("selection")
    selected = selection.get("selected_jids") if _object(selection) else None
    return {
        "requested_candidate_jids": list(candidate_jids) if candidate_jids is not None else None,
        "selected_candidate_jids": selected,
        "available_actions": list(available_actions),
    }


def _scope_disclosure() -> dict[str, Any]:
    return {
        "source_files_read": list(SOURCE_FILENAMES),
        "other_package_files_read": False,
        "database_or_live_context_read": False,
        "prepared_data_or_holdout_read_or_executed": False,
        "model_call_made": False,
    }


def _prepare_output_path(value: str | Path, evidence_dir: str | Path) -> Path:
    target = _absolute_user_path(value, "output", relative_to=ROOT)
    source_dir = _absolute_user_path(evidence_dir, "evidence directory")
    runs_dir = Path(os.path.abspath(ROOT / "runs"))
    # A new artifact directory must be a descendant of the repository's runs/.
    try:
        relative = target.relative_to(runs_dir)
    except ValueError as exc:
        raise ReviewCliError("output must be a new directory under project runs/") from exc
    if not relative.parts:
        raise ReviewCliError("output must be below project runs/")
    try:
        target.relative_to(source_dir)
    except ValueError:
        pass
    else:
        raise ReviewCliError("output directory may not be inside the source evidence package")
    _reject_symlink_components(runs_dir, "output")
    _reject_symlink_components(target, "output")
    if target.exists():
        raise ReviewCliError("output directory must not already exist")
    if runs_dir.exists() and not runs_dir.is_dir():
        raise ReviewCliError("project runs/ directory is unavailable")
    return target


def _check_review_path(value: str | Path) -> Path:
    path = _absolute_user_path(value, "review")
    _reject_symlink_components(path, "review")
    try:
        info = path.lstat()
    except OSError as exc:
        raise ReviewCliError("review JSON file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ReviewCliError("review JSON must be a regular file")
    return path


def _validate_external_review(review: dict[str, Any], review_input: dict[str, Any]) -> dict[str, Any]:
    _, _, validate_method_review = _review_api()
    try:
        validated = validate_method_review(review, review_input)
    except (ValueError, TypeError, KeyError) as exc:
        raise ReviewCliError("review failed structured reference or fact validation") from exc
    if not _object(validated):
        raise ReviewCliError("method review validator returned an invalid value")
    return validated


def _manifest(workflow: str, source: dict[str, Any], review_input: dict[str, Any],
              candidate_jids: list[str] | None, available_actions: list[str],
              artifacts: dict[str, bytes]) -> bytes:
    value = {
        "schema_version": 1,
        "artifact_type": "nova.method_review_cli_manifest.v1",
        "workflow": workflow,
        "source": source,
        "selection": _selection_disclosure(review_input, candidate_jids, available_actions),
        "scope": _scope_disclosure(),
        "files": {name: {"sha256": _sha256(data)} for name, data in sorted(artifacts.items())},
    }
    return _canonical_json_bytes(value)


def _write_new_output(path: Path, artifacts: dict[str, bytes], manifest_bytes: bytes) -> None:
    """Create output only after all source and review validation has succeeded."""
    try:
        # Nested new directories are allowed, while each existing ancestor was
        # checked above for symlink/reparse redirection.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()
        for name, data in artifacts.items():
            (path / name).write_bytes(data)
        (path / "manifest.json").write_bytes(manifest_bytes)
    except OSError as exc:
        raise ReviewCliError("cannot create method review output") from exc


def _run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_jids, available_actions = _validate_selection(args.candidate_jid, args.available_action)
    body, packet, source = _load_evidence_package(args.evidence_dir)
    review_input = _build_input(body, packet, candidate_jids, available_actions)

    if args.review_json is None:
        _, method_review_output_schema, _ = _review_api()
        try:
            schema = method_review_output_schema(review_input)
        except (ValueError, TypeError, KeyError) as exc:
            raise ReviewCliError("method review schema could not be built") from exc
        if not _object(schema):
            raise ReviewCliError("method review schema builder returned an invalid value")
        artifacts = {
            "review-input.json": _canonical_json_bytes(review_input),
            "review-output-schema.json": _canonical_json_bytes(schema),
        }
        workflow = "prepare_review_input"
    else:
        review_path = _check_review_path(args.review_json)
        source_dir = _absolute_user_path(args.evidence_dir, "evidence directory")
        try:
            review_path.relative_to(source_dir)
        except ValueError:
            pass
        else:
            raise ReviewCliError("review JSON must be outside the source evidence package")
        review = _decode_json(_read_regular_file(review_path, "review JSON"), "review JSON")
        if not _object(review):
            raise ReviewCliError("review JSON must contain an object")
        validated_review = _validate_external_review(review, review_input)
        validation = {
            "schema_version": 1,
            "artifact_type": "nova.method_review_validation.v1",
            "result": "structured_review_accepted",
            "review_input_sha256": review_input["review_input_sha256"],
            "evidence_sha256": review_input["evidence_sha256"],
            "structured_references": "passed",
            "structured_facts": "passed",
            "free_text_semantics": "not_verified",
            "model_source_authenticity": "not_verified",
            "independent_skeptic_turn": "not_verified",
        }
        artifacts = {
            "review-input.json": _canonical_json_bytes(review_input),
            "accepted-review.json": _canonical_json_bytes(validated_review),
            "validation.json": _canonical_json_bytes(validation),
        }
        workflow = "validate_external_review"

    # Confirm output safety after all source/input/review validation and before
    # the first output file or directory is created.
    output = _prepare_output_path(args.output, args.evidence_dir)
    manifest_bytes = _manifest(workflow, source, review_input, candidate_jids, available_actions, artifacts)
    _write_new_output(output, artifacts, manifest_bytes)
    return {"workflow": workflow, "output": str(output), "source_audit_sha256": source["audit_sha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, help="existing portable method export directory")
    parser.add_argument("--output", required=True, help="new output directory below project runs/")
    parser.add_argument("--candidate-jid", action="append", default=None,
                        help="include a candidate JID (repeat to select more than one)")
    parser.add_argument("--available-action", action="append", choices=("stop", "threshold_sensitivity"),
                        default=None, help="action available to the reviewer (repeat as needed; default: stop)")
    parser.add_argument("--review-json", help="externally produced review to validate; omit to prepare reviewer input")
    args = parser.parse_args(argv)
    try:
        result = _run(args)
    except ReviewCliError as exc:
        print(f"method review failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # Keep unexpected exception text out of stderr because it may include
        # artifact content. Detailed diagnostics belong in a debugger.
        print("method review failed: unexpected validation or I/O error", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
