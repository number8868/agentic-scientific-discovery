#!/usr/bin/env python3
"""Audit portable NOVA discovery evidence without running science or models."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova import holdout_bridge  # noqa: E402
from nova.contracts import Event, ExperimentSpec, Mode, Result, Split, Template  # noqa: E402
from nova.experiments import executor  # noqa: E402

_HEX = re.compile(r"^[0-9a-f]{64}$")
_PAYLOAD = re.compile(r"^science-artifacts/science-payload-([0-9a-f]{64})\.json$")
_FIXED_FILES = frozenset({
    "adaptive_evidence.json", "events.jsonl", "hashes.json", "manifest.json",
    "native-model-audit.jsonl", "native-runtime-manifest.json",
    "native-runtime-verification.json", "results.json", "reviews.json",
    "science-artifacts.json", "specs.json",
})
_REQUIRED_FILES = ("specs.json", "events.jsonl", "results.json", "science-artifacts.json")
_GROUPS = ("oxide", "chalcogenide")
_GRID = (0.025, 0.05, 0.10)
_POINT_FIELDS = frozenset({
    "threshold_ev_atom", "groups_summary", "delta", "resampling_interval",
    "missingness_interval", "quality_flags", "bootstrap", "scientific_status",
})
_PRIMARY_FIELDS = (
    "groups_summary", "delta", "resampling_interval", "missingness_interval",
    "quality_flags", "bootstrap", "scientific_status",
)


class AuditError(ValueError):
    """Safe, fixed-message error suitable for CLI output."""


def _fail(message: str) -> None:
    raise AuditError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_json(raw: bytes) -> Any:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    def constant(_value):
        raise ValueError("non-finite value")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite value")
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant,
                          parse_float=finite_float)
    except Exception:
        _fail("package contains invalid strict JSON")


def _is_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & flag)


def _check_components(path: Path, *, final_directory: bool) -> Path:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    parts = absolute.parts[1:]
    try:
        root_info = current.lstat()
        if _is_reparse(root_info) or not stat.S_ISDIR(root_info.st_mode):
            _fail("path contains an unsafe component")
        for index, part in enumerate(parts):
            current = current / part
            info = current.lstat()
            if _is_reparse(info):
                _fail("path contains an unsafe component")
            is_last = index == len(parts) - 1
            if (not is_last or final_directory) and not stat.S_ISDIR(info.st_mode):
                _fail("path contains an unsafe component")
            if is_last and not final_directory and not stat.S_ISREG(info.st_mode):
                _fail("package file is unavailable or unsafe")
    except AuditError:
        raise
    except OSError:
        _fail("path is unavailable")
    return absolute


def _check_existing_directory_ancestor(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    current = absolute
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            parent = current.parent
            if parent == current:
                _fail("output parent is unavailable")
            current = parent
            continue
        except OSError:
            _fail("output parent is unavailable")
        if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
            _fail("output path contains an unsafe component")
        _check_components(current, final_directory=True)
        return absolute


def _argument_path(value: str | Path, base: Path) -> Path:
    raw = Path(value)
    if ".." in raw.parts:
        _fail("paths must not contain traversal components")
    return Path(os.path.abspath(raw if raw.is_absolute() else base / raw))


def _package_name(name: str) -> tuple[str, ...]:
    if name in _FIXED_FILES:
        return (name,)
    match = _PAYLOAD.fullmatch(name)
    if match:
        return tuple(PurePosixPath(name).parts)
    _fail("manifest contains an unsupported package path")


def _read_relative(root: Path, name: str) -> bytes:
    parts = _package_name(name)
    path = root.joinpath(*parts)
    try:
        _check_components(path, final_directory=False)
        return path.read_bytes()
    except AuditError:
        raise
    except Exception:
        _fail("package file is unavailable or unsafe")


def _object(value: Any) -> bool:
    return isinstance(value, dict)


def _exact_int(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _read_manifest(root: Path) -> tuple[dict[str, Any], bytes, dict[str, str]]:
    raw = _read_relative(root, "manifest.json")
    manifest = _strict_json(raw)
    if (not _object(manifest) or manifest.get("schema_version") != 1 or
            type(manifest.get("schema_version")) is not int or
            manifest.get("mode") != "live" or
            not isinstance(manifest.get("run_id"), str) or not manifest["run_id"].strip()):
        _fail("manifest identity is invalid")
    files = manifest.get("files")
    if not _object(files):
        _fail("manifest file map is invalid")
    for name, entry in files.items():
        if not isinstance(name, str):
            _fail("manifest contains an unsupported package path")
        if name == "manifest.json":
            _fail("manifest cannot list itself as a package file")
        _package_name(name)
        if (not _object(entry) or set(entry) != {"sha256", "count"} or
                not isinstance(entry.get("sha256"), str) or not _HEX.fullmatch(entry["sha256"]) or
                not _exact_int(entry.get("count"))):
            _fail("manifest file metadata is invalid")
    if any(name not in files for name in _REQUIRED_FILES):
        _fail("manifest is missing required discovery metadata")
    return manifest, raw, {"manifest.json": _sha256(raw)}


def _read_verified(root: Path, manifest: dict[str, Any], source_hashes: dict[str, str], name: str,
                   expected_count: int | None = None) -> bytes:
    files = manifest["files"]
    entry = files.get(name)
    if not _object(entry):
        _fail("manifest is missing a required discovery file")
    raw = _read_relative(root, name)
    digest = _sha256(raw)
    if digest != entry["sha256"]:
        _fail("package file digest does not match manifest")
    if expected_count is not None and entry["count"] != expected_count:
        _fail("package file count does not match manifest")
    source_hashes[name] = digest
    return raw


def _read_json_file(root: Path, manifest: dict[str, Any], source_hashes: dict[str, str], name: str,
                    expected_count: int | None = None) -> Any:
    return _strict_json(_read_verified(root, manifest, source_hashes, name, expected_count))


def _inventory_count(name: str, raw: bytes) -> int:
    if name.endswith(".jsonl"):
        try:
            lines = raw.decode("utf-8").splitlines()
        except Exception:
            _fail("package file is not valid UTF-8")
        if any(not line.strip() for line in lines):
            _fail("package JSONL file contains an empty record")
        for line in lines:
            if not _object(_strict_json(line.encode("utf-8"))):
                _fail("package JSONL record is invalid")
        return len(lines)
    value = _strict_json(raw)
    if name in {"specs.json", "results.json", "reviews.json"}:
        if not isinstance(value, list):
            _fail("package list file is invalid")
        return len(value)
    if name == "science-artifacts.json":
        if not _object(value) or not isinstance(value.get("results"), list):
            _fail("science artifact index is invalid")
        return len(value["results"])
    if not _object(value):
        _fail("package metadata file is invalid")
    return 1


def _verify_manifest_inventory(root: Path, manifest: dict[str, Any],
                               source_hashes: dict[str, str]) -> None:
    """Hash and count every allowlisted manifest file without retaining prose."""
    for name, entry in manifest["files"].items():
        raw = _read_relative(root, name)
        digest = _sha256(raw)
        if digest != entry["sha256"]:
            _fail("package file digest does not match manifest")
        if _inventory_count(name, raw) != entry["count"]:
            _fail("package file count does not match manifest")
        source_hashes[name] = digest


def _check_specs(rows: Any) -> dict[str, ExperimentSpec]:
    if not isinstance(rows, list) or len(rows) != 2 or any(not _object(item) for item in rows):
        _fail("bundle must contain exactly two discovery specs")
    # This rejection is deliberately before results, events, or science payloads are opened.
    if any(item.get("split") == "holdout" or item.get("template") == "holdout_validation" for item in rows):
        _fail("holdout specs are outside this audit scope")
    by_template: dict[str, ExperimentSpec] = {}
    from dataclasses import fields

    expected_fields = {field.name for field in fields(ExperimentSpec)}
    for item in rows:
        if set(item) != expected_fields:
            _fail("spec metadata has an unsupported shape")
        template = item.get("template")
        if template not in {Template.FAMILY_SCREEN.value, Template.THRESHOLD_SENSITIVITY.value} or template in by_template:
            _fail("bundle must contain one family screen and one threshold sensitivity spec")
        try:
            spec = ExperimentSpec.from_dict(item)
        except Exception:
            _fail("spec metadata is invalid")
        if (spec.split is not Split.DISCOVERY or
                spec.template.value != template or spec.frozen_protocol_id is not None):
            _fail("spec metadata is not frozen discovery evidence")
        for key, expected in executor._FROZEN.items():
            observed = getattr(spec, key)
            if (isinstance(expected, int) and type(observed) is not int) or observed != expected:
                _fail("spec metadata differs from the frozen executor contract")
        if not _HEX.fullmatch(spec.dataset_sha256) or not spec.hypothesis_id:
            _fail("spec dataset or hypothesis identity is invalid")
        by_template[template] = spec
    parent = by_template[Template.FAMILY_SCREEN.value]
    child = by_template[Template.THRESHOLD_SENSITIVITY.value]
    if (parent.experiment_id == child.experiment_id or parent.dataset_sha256 != child.dataset_sha256 or
            parent.hypothesis_id != child.hypothesis_id or parent.parent_result_id is not None or
            parent.review_id is not None or not isinstance(child.parent_result_id, str) or
            not child.parent_result_id or child.review_id != child.parent_result_id):
        _fail("discovery specs do not form one parent and one linked follow-up")
    return {"family_screen": parent, "threshold_sensitivity": child}


def _read_events(raw: bytes, run_id: str, manifest: dict[str, Any]) -> list[Event]:
    from dataclasses import fields

    lines = raw.decode("utf-8").splitlines()
    if not lines or any(not line.strip() for line in lines):
        _fail("run events are invalid")
    if manifest["files"]["events.jsonl"]["count"] != len(lines):
        _fail("package file count does not match manifest")
    event_fields = {field.name for field in fields(Event)}
    events = []
    for line in lines:
        value = _strict_json(line.encode("utf-8"))
        if not _object(value) or set(value) != event_fields:
            _fail("run events have an unsupported shape")
        try:
            event = Event.from_dict(value)
        except Exception:
            _fail("run events are invalid")
        if (event.run_id != run_id or event.mode is not Mode.LIVE or type(event.seq) is not int or
                type(event.attempt) is not int or not event.event_id):
            _fail("run event identity does not match manifest")
        events.append(event)
    if ([event.seq for event in events] != list(range(1, len(events) + 1)) or
            len({event.event_id for event in events}) != len(events)):
        _fail("run event sequence is invalid")
    return events


def _check_event_ownership(events: list[Event], specs: dict[str, ExperimentSpec],
                           results: dict[str, Result] | None = None) -> None:
    def one(kind: str, actor: str, ref: str | None) -> Event:
        matches = [event for event in events if event.event_type == kind and event.actor == actor and
                   event.payload_ref == ref]
        if len(matches) != 1:
            _fail("discovery run ownership events are incomplete")
        return matches[0]

    parent, child = specs["family_screen"], specs["threshold_sensitivity"]
    created = one("run_created", "host", None)
    parent_selected = one("selection", "pi", parent.experiment_id)
    parent_running = one("running", "runner", parent.experiment_id)
    child_selected = one("second_selection", "pi", child.experiment_id)
    child_running = one("running", "runner", child.experiment_id)
    if (sum(event.event_type == "run_created" for event in events) != 1 or
            sum(event.event_type in {"selection", "second_selection"} for event in events) != 2 or
            sum(event.event_type == "running" for event in events) != 2):
        _fail("discovery run ownership events are ambiguous")
    if results is None:
        # Result events are checked after reading results.json; all other ownership metadata is checked first.
        if not created.seq < parent_selected.seq < parent_running.seq < child_selected.seq < child_running.seq:
            _fail("discovery run ownership order is invalid")
        return
    parent_result = one("result", "runner", results["family_screen"].result_id)
    child_result = one("result", "runner", results["threshold_sensitivity"].result_id)
    if (sum(event.event_type == "result" and event.actor == "runner" for event in events) != 2 or
            not created.seq < parent_selected.seq < parent_running.seq < parent_result.seq <
            child_selected.seq < child_running.seq < child_result.seq):
        _fail("discovery result ownership order is invalid")


def _read_results(rows: Any, specs: dict[str, ExperimentSpec]) -> dict[str, Result]:
    from dataclasses import fields

    if not isinstance(rows, list) or len(rows) != 2 or any(not _object(item) for item in rows):
        _fail("bundle must contain exactly two discovery results")
    expected_fields = {field.name for field in fields(Result)}
    by_experiment: dict[str, Result] = {}
    for item in rows:
        if set(item) != expected_fields:
            _fail("stored result has an unsupported shape")
        try:
            result = Result.from_dict(item)
        except Exception:
            _fail("stored result is invalid")
        if result.experiment_id in by_experiment:
            _fail("stored discovery results are ambiguous")
        by_experiment[result.experiment_id] = result
    output = {}
    for role, spec in specs.items():
        result = by_experiment.get(spec.experiment_id)
        if (result is None or result.spec_sha256 != spec.sha256 or
                result.dataset_sha256 != spec.dataset_sha256 or result.execution_status != "completed" or
                result.error is not None or not isinstance(result.result_id, str) or not result.result_id or
                isinstance(result.elapsed_seconds, bool) or not isinstance(result.elapsed_seconds, (int, float)) or
                not math.isfinite(result.elapsed_seconds) or result.elapsed_seconds < 0):
            _fail("stored result identity or status does not match its spec")
        output[role] = result
    if specs["threshold_sensitivity"].parent_result_id != output["family_screen"].result_id:
        _fail("follow-up spec does not reference the parent result")
    return output


def _check_artifact_index(index: Any, manifest: dict[str, Any], specs: dict[str, ExperimentSpec],
                          results: dict[str, Result]) -> dict[str, str]:
    if (not _object(index) or index.get("schema_version") != 1 or type(index.get("schema_version")) is not int or
            not isinstance(index.get("artifacts"), list) or not isinstance(index.get("results"), list) or
            len(index["artifacts"]) != 2 or len(index["results"]) != 2):
        _fail("science artifact index is invalid")
    if manifest["files"]["science-artifacts.json"]["count"] != 2:
        _fail("package file count does not match manifest")
    artifacts = {item.get("artifact_id"): item for item in index["artifacts"] if _object(item)}
    index_results = {item.get("experiment_id"): item for item in index["results"] if _object(item)}
    if len(artifacts) != 2 or len(index_results) != 2:
        _fail("science artifact index is ambiguous")
    output = {}
    for role, spec in specs.items():
        result = results[role]
        payload_ids = [value for value in result.artifact_ids if value.startswith("nova-result-payload:")]
        if len(payload_ids) != 1 or not _HEX.fullmatch(payload_ids[0].split(":", 1)[1]):
            _fail("stored result payload reference is invalid")
        digest = payload_ids[0].split(":", 1)[1]
        relative = f"science-artifacts/science-payload-{digest}.json"
        source_relative = f"runs/science-payload-{digest}.json"
        artifact = artifacts.get(payload_ids[0])
        entry = index_results.get(spec.experiment_id)
        if (not _object(artifact) or set(artifact) != {"artifact_id", "exported_path", "sha256", "size_bytes", "source_path"} or
                artifact.get("exported_path") != relative or artifact.get("sha256") != digest or
                artifact.get("source_path") != source_relative or
                not _exact_int(artifact.get("size_bytes")) or not _object(entry) or
                set(entry) != {"artifact_ids", "experiment_id", "registered_spec_sha256", "result_id"} or
                entry.get("artifact_ids") != [payload_ids[0]] or entry.get("registered_spec_sha256") != spec.sha256 or
                entry.get("result_id") != result.result_id):
            _fail("science artifact index does not match stored results")
        manifest_entry = manifest["files"].get(relative)
        if not _object(manifest_entry) or manifest_entry.get("sha256") != digest or manifest_entry.get("count") != 1:
            _fail("science payload manifest entry is invalid")
        output[role] = relative
    payload_names = {name for name in manifest["files"] if _PAYLOAD.fullmatch(name)}
    if payload_names != set(output.values()):
        _fail("manifest contains an unexpected science payload path")
    return output


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("threshold point contains an invalid numeric fact")
    return float(value)


def _close(actual: Any, expected: float | None) -> bool:
    if expected is None:
        return actual is None
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
        return False
    return math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-15)


def _interval(value: Any, nullable: bool = False) -> list[float] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, list) or len(value) != 2:
        _fail("threshold point interval has an invalid shape")
    low, high = (_finite_number(item) for item in value)
    if low > high or low < -1.0 or high > 1.0:
        _fail("threshold point interval is invalid")
    return [low, high]


def _validate_point(point: Any, threshold: float) -> dict[str, Any]:
    threshold_value = point.get("threshold_ev_atom") if _object(point) else None
    if (not _object(point) or set(point) != _POINT_FIELDS or isinstance(threshold_value, bool) or
            not isinstance(threshold_value, (int, float)) or not math.isfinite(threshold_value) or
            float(threshold_value) != threshold):
        _fail("threshold grid point has an invalid shape or value")
    groups = point.get("groups_summary")
    if not _object(groups) or set(groups) != set(_GROUPS):
        _fail("threshold point group summary is invalid")
    clean_groups = {}
    for group in _GROUPS:
        summary = groups[group]
        required = {"n_total", "n_observed", "n_pass", "coverage", "observed_rate", "missing_lower", "missing_upper"}
        if not _object(summary) or set(summary) != required:
            _fail("threshold point group summary is invalid")
        total, observed, passed = summary["n_total"], summary["n_observed"], summary["n_pass"]
        if not (_exact_int(total) and _exact_int(observed) and _exact_int(passed) and passed <= observed <= total):
            _fail("threshold point counts are invalid")
        expected = {
            "coverage": observed / total if total else None,
            "observed_rate": passed / observed if observed else None,
            "missing_lower": passed / total if total else None,
            "missing_upper": (passed + total - observed) / total if total else None,
        }
        if any(not _close(summary[key], val) for key, val in expected.items()):
            _fail("threshold point rates do not match counts")
        clean_groups[group] = {"n_total": total, "n_observed": observed, "n_pass": passed, **expected}

    oxide, chalc = (clean_groups[group] for group in _GROUPS)
    delta = (chalc["observed_rate"] - oxide["observed_rate"]
             if chalc["observed_rate"] is not None and oxide["observed_rate"] is not None else None)
    if not _close(point.get("delta"), delta):
        _fail("threshold point delta does not match observed rates")
    ci = _interval(point.get("resampling_interval"), nullable=delta is None)
    missing = point.get("missingness_interval")
    if oxide["n_total"] and chalc["n_total"]:
        expected_missing = {
            "lower": chalc["missing_lower"] - oxide["missing_upper"],
            "upper": chalc["missing_upper"] - oxide["missing_lower"],
            "oxide_rate_lower": oxide["missing_lower"], "oxide_rate_upper": oxide["missing_upper"],
            "chalcogenide_rate_lower": chalc["missing_lower"], "chalcogenide_rate_upper": chalc["missing_upper"],
        }
        if (not _object(missing) or set(missing) != set(expected_missing) or
                any(not _close(missing[key], val) for key, val in expected_missing.items())):
            _fail("threshold point missingness bounds do not match counts")
        crosses = expected_missing["lower"] <= 0.0 <= expected_missing["upper"]
    else:
        if missing is not None:
            _fail("threshold point missingness bounds are invalid")
        crosses = False

    quality = point.get("quality_flags")
    if not _object(quality) or set(quality) != set(_GROUPS) | {
            "minimum_sample_and_coverage_pass", "endpoint_non_degenerate", "missingness_bounds_cross_zero"}:
        _fail("threshold point quality flags are invalid")
    expected_quality = {}
    for group in _GROUPS:
        summary = clean_groups[group]
        expected_quality[group] = {
            "minimum_evaluable_count_pass": summary["n_observed"] >= 40,
            "minimum_coverage_pass": summary["coverage"] is not None and summary["coverage"] >= 0.80,
            "endpoint_has_pass_and_fail": summary["n_pass"] > 0 and summary["n_pass"] < summary["n_observed"],
        }
        if (not _object(quality[group]) or set(quality[group]) != set(expected_quality[group]) or
                any(type(quality[group][key]) is not bool or quality[group][key] != expected
                    for key, expected in expected_quality[group].items())):
            _fail("threshold point quality flags contradict counts")
    enough = all(v["minimum_evaluable_count_pass"] and v["minimum_coverage_pass"] for v in expected_quality.values())
    nondegenerate = all(v["endpoint_has_pass_and_fail"] for v in expected_quality.values())
    expected_quality.update({
        "minimum_sample_and_coverage_pass": enough,
        "endpoint_non_degenerate": nondegenerate,
        "missingness_bounds_cross_zero": crosses,
    })
    aggregate_quality = {key: value for key, value in expected_quality.items() if key not in _GROUPS}
    if (set(quality) != set(expected_quality) or any(
            type(quality[key]) is not bool or quality[key] != expected
            for key, expected in aggregate_quality.items())):
        _fail("threshold point quality flags contradict frozen rules")
    expected_status = ("data_limited" if not enough else
                       "inconclusive" if not nondegenerate or ci is None or ci[0] <= 0.0 <= ci[1] else
                       "supported_in_snapshot" if ci[0] > 0.0 else
                       "reversed_in_snapshot" if ci[1] < 0.0 else "inconclusive")
    if point.get("scientific_status") != expected_status:
        _fail("threshold point status contradicts frozen quality rules")

    bootstrap = point.get("bootstrap")
    bootstrap_fields = {"delta", "resampling_interval", "replicates", "seed", "interval_method",
                        "bootstrap_degenerate", "family_endpoint_degenerate"}
    if (not _object(bootstrap) or set(bootstrap) != bootstrap_fields or
            not _close(bootstrap.get("delta"), delta) or bootstrap.get("resampling_interval") != point["resampling_interval"] or
            bootstrap.get("replicates") != 2000 or type(bootstrap.get("replicates")) is not int or
            bootstrap.get("seed") != 1729 or type(bootstrap.get("seed")) is not int or
            bootstrap.get("interval_method") != "family-stratified percentile bootstrap at composition level" or
            type(bootstrap.get("bootstrap_degenerate")) is not bool):
        _fail("threshold point bootstrap metadata is invalid")
    degeneracy = bootstrap.get("family_endpoint_degenerate")
    if (not _object(degeneracy) or set(degeneracy) != set(_GROUPS) or any(
            type(degeneracy[group]) is not bool or
            degeneracy[group] != (clean_groups[group]["n_pass"] in (0, clean_groups[group]["n_observed"]))
            for group in _GROUPS)):
        _fail("threshold point bootstrap endpoint flags contradict counts")
    return {
        "threshold_ev_atom": threshold, "groups_summary": clean_groups, "delta": delta,
        "resampling_interval": ci, "missingness_interval": expected_missing if missing is not None else None,
        "quality_flags": expected_quality, "bootstrap": bootstrap,
        "scientific_status": expected_status,
    }


def _direction(delta: float | None) -> str:
    return "unavailable" if delta is None else "positive" if delta > 0 else "negative" if delta < 0 else "zero"


def _direction_classification(directions: list[str]) -> str:
    if "unavailable" in directions:
        return "unavailable"
    if "positive" in directions and "negative" in directions:
        return "mixed_signs"
    if all(item == "positive" for item in directions):
        return "all_positive"
    if all(item == "negative" for item in directions):
        return "all_negative"
    if all(item == "zero" for item in directions):
        return "all_zero"
    return "includes_zero"


def _validate_threshold(science: dict[str, Any], parent_science: dict[str, Any]) -> list[dict[str, Any]]:
    if (science.get("primary_point_index") != 1 or type(science.get("primary_point_index")) is not int or
            science.get("primary_threshold_ev_atom") != _GRID[1] or
            not isinstance(science.get("points"), list) or len(science["points"]) != 3):
        _fail("threshold primary point or grid is invalid")
    points = [_validate_point(value, threshold) for value, threshold in zip(science["points"], _GRID)]
    parent_groups = parent_science.get("groups_summary")
    if not _object(parent_groups) or set(parent_groups) != set(_GROUPS):
        _fail("parent discovery group summary is invalid")
    for group in _GROUPS:
        baseline = parent_groups[group]
        if not _object(baseline):
            _fail("parent discovery group summary is invalid")
        prior_pass = -1
        for point in points:
            summary = point["groups_summary"][group]
            if (summary["n_total"] != baseline.get("n_total") or
                    summary["n_observed"] != baseline.get("n_observed") or
                    summary["n_pass"] < prior_pass):
                _fail("threshold grid counts contradict the parent or frozen threshold ordering")
            prior_pass = summary["n_pass"]
    main = science.get("main_point")
    if not _object(main) or set(main) != _POINT_FIELDS or main != science["points"][1]:
        _fail("threshold main point differs from the frozen primary grid point")
    for key in _PRIMARY_FIELDS:
        if main.get(key) != parent_science.get(key):
            _fail("threshold primary point differs from its parent result")
        if science.get(key) != main.get(key):
            _fail("threshold result summary differs from its primary point")
    directions = [_direction(point["delta"]) for point in points]
    comparison = science.get("delta_direction_comparison")
    expected_comparison = {"point_directions": directions,
                           "classification": _direction_classification(directions)}
    if comparison != expected_comparison:
        _fail("threshold direction summary does not match the fixed grid")
    return points


def _result_facts(result: Result, role: str, spec: ExperimentSpec, digest: str,
                  science: dict[str, Any]) -> dict[str, Any]:
    expected_computation = executor._computation_spec_sha256(executor._minimal_science_spec(spec))
    if (science.get("execution_status") != "success" or science.get("error") is not None or
            science.get("split") != "discovery" or science.get("dataset_sha256") != spec.dataset_sha256 or
            science.get("template") != spec.template.value):
        _fail("science payload facts do not match discovery spec")
    groups = {item.group: {"n_total": item.n_total, "n_observed": item.n_observed, "n_pass": item.n_pass}
              for item in result.groups_summary}
    if set(groups) != set(_GROUPS):
        _fail("stored result group facts are invalid")
    return {
        "role": role, "experiment_id": spec.experiment_id, "result_id": result.result_id,
        "registered_spec_sha256": spec.sha256,
        "expected_computation_spec_sha256": expected_computation,
        "payload_sha256": digest, "scientific_status": result.scientific_status,
        "counts": groups,
    }


def _validate_artifact_payload(result: Result, spec: ExperimentSpec, root: Path,
                               temporary_payload: Path) -> tuple[str, dict[str, Any]]:
    if os.name != "nt":
        return holdout_bridge._artifact_payload(result, spec, root)
    # The existing bridge deliberately enforces POSIX private-file mode bits.
    # Windows st_mode cannot represent those bits, so do not weaken or replace
    # that guard here; run full payload validation from Linux or WSL.
    _fail("full payload validation requires Linux or WSL mode-bit checks")


def _audit_document(evidence_dir: str | Path, output: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence = _argument_path(evidence_dir, ROOT)
    _check_components(evidence, final_directory=True)
    target = _argument_path(output, ROOT)
    runs = Path(os.path.abspath(ROOT / "runs"))
    if not target.is_relative_to(runs) or target == runs:
        _fail("output must be a new directory under project runs")
    if evidence == target or evidence.is_relative_to(target) or target.is_relative_to(evidence):
        _fail("output and evidence directories must be separate")
    _check_existing_directory_ancestor(target.parent)
    try:
        target.lstat()
        _fail("output directory already exists")
    except FileNotFoundError:
        pass
    except AuditError:
        raise
    except OSError:
        _fail("output path is unavailable")

    manifest, manifest_raw, source_hashes = _read_manifest(evidence)
    specs_rows = _read_json_file(evidence, manifest, source_hashes, "specs.json")
    specs = _check_specs(specs_rows)
    if manifest["files"]["specs.json"]["count"] != 2:
        _fail("package file count does not match manifest")

    event_raw = _read_verified(evidence, manifest, source_hashes, "events.jsonl")
    events = _read_events(event_raw, manifest["run_id"], manifest)
    _check_event_ownership(events, specs)
    _verify_manifest_inventory(evidence, manifest, source_hashes)

    result_rows = _read_json_file(evidence, manifest, source_hashes, "results.json", expected_count=2)
    results = _read_results(result_rows, specs)
    _check_event_ownership(events, specs, results)
    index = _read_json_file(evidence, manifest, source_hashes, "science-artifacts.json", expected_count=2)
    artifact_paths = _check_artifact_index(index, manifest, specs, results)

    payload_bytes = {}
    payload_json = {}
    for role in ("family_screen", "threshold_sensitivity"):
        name = artifact_paths[role]
        raw = _read_verified(evidence, manifest, source_hashes, name, expected_count=1)
        body = _strict_json(raw)
        if not _object(body):
            _fail("science payload is invalid")
        payload_bytes[role] = raw
        payload_json[role] = body
        if len(raw) != next(item["size_bytes"] for item in index["artifacts"]
                            if item.get("exported_path") == name):
            _fail("science payload size does not match artifact index")

    payload_digests: dict[str, str] = {}
    science_results = {}
    with tempfile.TemporaryDirectory(prefix="nova-discovery-audit-") as temporary:
        temp_root = Path(temporary)
        (temp_root / "runs").mkdir()
        for role in ("family_screen", "threshold_sensitivity"):
            raw = payload_bytes[role]
            digest = _sha256(raw)
            path = temp_root / "runs" / f"science-payload-{digest}.json"
            path.write_bytes(raw)
            try:
                path.chmod(0o600)
            except OSError:
                _fail("temporary science payload could not be secured")
            payload_digests[role] = _validate_artifact_payload(
                results[role], specs[role], temp_root, path
            )[0]
            science_results[role] = payload_json[role].get("science_result")
            if not _object(science_results[role]):
                _fail("science payload result is invalid")

    parent_science = science_results["family_screen"]
    threshold_science = science_results["threshold_sensitivity"]
    grid = _validate_threshold(threshold_science, parent_science)
    result_facts = [_result_facts(results[role], role, specs[role], payload_digests[role], science_results[role])
                    for role in ("family_screen", "threshold_sensitivity")]
    audit = {
        "schema_version": 1,
        "audit_type": "portable_discovery_evidence_audit",
        "status": "pass",
        "run_id": manifest["run_id"],
        "hypothesis_id": specs["family_screen"].hypothesis_id,
        "dataset_sha256": specs["family_screen"].dataset_sha256,
        "source_sha256": dict(sorted(source_hashes.items())),
        "results": result_facts,
        "threshold_grid": grid,
        "validation_scope": {
            "new_model_calls": 0,
            "new_science_executions": 0,
            "holdout_outcomes_read": False,
            "native_completion_verified": False,
            "model_role_identity_verified": False,
            "prose_semantics_verified": False,
            "payload_consistency_is_raw_source_reproduction": False,
            "frozen_dataset_identity_authenticated": False,
            "registered_payload_result_consistency_verified": True,
            "threshold_counts_rates_delta_status_and_quality_verified": True,
            "bootstrap_resampling_interval_reproduced": False,
        },
    }
    audit_raw = (json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    output_manifest = {
        "schema_version": 1,
        "source_run_id": manifest["run_id"],
        "source_manifest_sha256": _sha256(manifest_raw),
        "source_files_sha256": dict(sorted(source_hashes.items())),
        "files": {"audit.json": {"sha256": _sha256(audit_raw), "count": 1}},
    }
    return {"audit.json": audit_raw,
            "manifest.json": (json.dumps(output_manifest, ensure_ascii=False, sort_keys=True,
                                           indent=2, allow_nan=False) + "\n").encode("utf-8")}, output_manifest


def audit_bundle(evidence_dir: str | Path, output: str | Path) -> Path:
    try:
        files, _ = _audit_document(evidence_dir, output)
        target = _argument_path(output, ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        _check_components(target.parent, final_directory=True)
        with tempfile.TemporaryDirectory(prefix=".discovery-audit-", dir=target.parent) as staging:
            stage = Path(staging)
            for name, raw in files.items():
                (stage / name).write_bytes(raw)
            stage.rename(target)
        return target
    except AuditError:
        raise
    except Exception:
        # Do not expose data, input paths, or exception text from untrusted bundles.
        raise AuditError("discovery evidence audit failed") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, help="portable published evidence bundle")
    parser.add_argument("--output", required=True, help="fresh output directory under project runs/")
    args = parser.parse_args(argv)
    try:
        result = audit_bundle(args.evidence_dir, args.output)
    except AuditError as error:
        print(f"audit failed: {error}", file=sys.stderr)
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
