"""Host adapter from registered NOVA specs to the frozen science templates.

The workflow host must call execute only after resolving a registered
experiment ID. This module validates the full contract again, then passes only
the frozen scientific fields to a deterministic experiment implementation.

The shared Result contract stores quality flags as strings. The complete
structured quality flags are preserved as one
science-quality-json-v1:<canonical JSON> entry. Full numerical output
(including threshold grid points) is kept in an immutable JSON artifact under
runs/; its result and artifact IDs are content addressed. Execution timestamps
and elapsed time remain on Result and are excluded from that stable payload.
"""
from __future__ import annotations

from dataclasses import fields
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

from nova.contracts import ExperimentSpec, GroupSummary, Result, Template
from nova.experiments import family_screen


PROJECT_ROOT = family_screen.PROJECT_ROOT
_HOST_FIELDS = frozenset({"mode", "run_id"})
_CONTRACT_FIELDS = frozenset(field.name for field in fields(ExperimentSpec))
_SCIENCE_FIELDS = (
    "schema_version",
    "template",
    "split",
    "groups",
    "bandgap_method",
    "gap_window_ev",
    "ehull_max_ev_atom",
    "bootstrap_repeats",
    "seed",
    "dataset_sha256",
)
_FROZEN = {
    "schema_version": 1,
    "split": "discovery",
    "groups": ("oxide", "chalcogenide"),
    "bandgap_method": "opt",
    "gap_window_ev": (1.1, 1.8),
    "ehull_max_ev_atom": 0.05,
    "bootstrap_repeats": 2_000,
    "seed": 1_729,
    "timeout_seconds": 120,
}
_SUCCESS = "success"
_COMPLETED = "completed"
_SCIENTIFIC_STATES = frozenset({
    "supported_in_snapshot",
    "reversed_in_snapshot",
    "inconclusive",
    "data_limited",
})


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_frozen_manifest() -> dict[str, Any]:
    """Read only host-owned manifest metadata, never property outcomes."""
    path = PROJECT_ROOT / "data" / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("prepared dataset manifest must be a JSON object")
    return value


def active_dataset_sha256() -> str:
    """Return the hash of the prepared dft_3d source snapshot."""
    manifest = _load_frozen_manifest()
    if manifest.get("dataset") != "dft_3d":
        raise ValueError("prepared dataset must be dft_3d")
    digest = manifest.get("original_download_zip_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("prepared manifest has no valid source dataset SHA256")
    try:
        int(digest, 16)
    except ValueError:
        raise ValueError("prepared manifest has no valid source dataset SHA256") from None
    return digest


def _normalise_and_validate(spec: Mapping[str, Any]) -> ExperimentSpec:
    if not isinstance(spec, Mapping):
        raise TypeError("registered experiment spec must be a mapping")
    unknown = set(spec) - _CONTRACT_FIELDS - _HOST_FIELDS
    if unknown:
        raise ValueError(f"unknown live executor fields: {sorted(unknown)}")
    if spec.get("mode") != "live":
        raise ValueError("science executor accepts live mode only")
    if not isinstance(spec.get("experiment_id"), str) or not spec["experiment_id"]:
        raise ValueError("experiment_id is required on the registered spec")
    run_id = spec.get("run_id")
    if run_id is not None and (not isinstance(run_id, str) or not run_id):
        raise ValueError("run_id host metadata must be a non-empty string")

    contract_fields = {key: value for key, value in spec.items() if key in _CONTRACT_FIELDS}
    contract = ExperimentSpec.from_dict(contract_fields)
    if contract.template not in {Template.FAMILY_SCREEN, Template.THRESHOLD_SENSITIVITY}:
        raise ValueError("only discovery family and threshold sensitivity templates are supported")
    if contract.dataset_sha256 != active_dataset_sha256():
        raise ValueError("registered dataset_sha256 does not match the prepared dft_3d snapshot")

    for key, expected in _FROZEN.items():
        observed = getattr(contract, key)
        if key in {"groups", "gap_window_ev"}:
            observed = tuple(observed)
        if observed != expected:
            raise ValueError(f"{key} is frozen by the live science protocol at {expected!r}")
    return contract


def _minimal_science_spec(contract: ExperimentSpec) -> dict[str, Any]:
    values = contract.to_dict()
    minimal = {key: values[key] for key in _SCIENCE_FIELDS}
    minimal["groups"] = list(contract.groups)
    minimal["gap_window_ev"] = list(contract.gap_window_ev)
    return minimal


def _computation_spec_sha256(minimal: Mapping[str, Any]) -> str:
    effective = {key: minimal[key] for key in _SCIENCE_FIELDS}
    if minimal["template"] == Template.THRESHOLD_SENSITIVITY.value:
        from nova.experiments import threshold_sensitivity

        effective["ehull_grid_ev_atom"] = list(threshold_sensitivity.THRESHOLD_GRID_EV_ATOM)
        effective["extension_protocol_sha256"] = threshold_sensitivity.THRESHOLD_PROTOCOL_SHA256
    return _sha256(_canonical_json(effective).encode("utf-8"))


def _interval(value: Any, name: str) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        if "lower" not in value or "upper" not in value:
            raise ValueError(f"{name} must contain lower and upper bounds")
        value = (value["lower"], value["upper"])
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError(f"{name} must be a pair of finite bounds")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ValueError(f"{name} must be a pair of finite bounds")
    pair = tuple(float(item) for item in value)
    if any(not math.isfinite(item) or not -1.0 <= item <= 1.0 for item in pair):
        raise ValueError(f"{name} bounds must be finite and between -1 and 1")
    if pair[0] > pair[1]:
        raise ValueError(f"{name} lower bound cannot exceed upper bound")
    return pair


def _groups_summary(value: Any) -> tuple[GroupSummary, ...]:
    if isinstance(value, Mapping):
        entries = [dict(summary, group=label) for label, summary in value.items()]
    elif isinstance(value, (tuple, list)):
        entries = [dict(item) for item in value]
    else:
        raise ValueError("science result must contain groups_summary")
    by_name: dict[str, GroupSummary] = {}
    for entry in entries:
        label = entry.get("group")
        if not isinstance(label, str) or not label:
            raise ValueError("each group summary must have a group label")
        if label in by_name:
            raise ValueError(f"duplicate group summary: {label}")
        by_name[label] = GroupSummary.from_dict(entry)
    expected = ("oxide", "chalcogenide")
    if set(by_name) != set(expected):
        raise ValueError("science result must summarize oxide and chalcogenide")
    return tuple(by_name[label] for label in expected)


def _artifact_body(
    raw_result: Mapping[str, Any],
    contract: ExperimentSpec,
    computation_sha256: str,
) -> dict[str, Any]:
    science_result = {
        key: value
        for key, value in raw_result.items()
        if key not in {"started_at", "finished_at", "elapsed_seconds"}
    }
    return {
        "schema_version": 1,
        "artifact_type": "nova.science_payload.v1",
        "experiment_id": contract.experiment_id,
        "registered_spec_sha256": contract.sha256,
        "computation_spec_sha256": computation_sha256,
        "science_result": science_result,
    }


def _write_immutable_artifact(body: Mapping[str, Any]) -> tuple[str, str]:
    payload = (_canonical_json(body) + "\n").encode("utf-8")
    digest = _sha256(payload)
    relative_path = Path("runs") / f"science-payload-{digest}.json"
    output_path = PROJECT_ROOT / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        if output_path.read_bytes() != payload:
            raise FileExistsError("content-addressed science artifact has different contents")
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".science-payload-",
            suffix=".tmp",
            dir=output_path.parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # Hard-link creation is atomic and refuses to replace an
                # artifact created by another execution.
                os.link(temporary_name, output_path)
            except FileExistsError:
                if output_path.read_bytes() != payload:
                    raise FileExistsError("content-addressed science artifact has different contents")
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    return f"nova-result-payload:{digest}", relative_path.as_posix()


def export_science_artifacts(result: Result, output_dir: Path) -> Path:
    """Copy executor-owned payloads into a run export and checksum the copies."""
    if not isinstance(result, Result):
        raise TypeError("result must be a shared Result")
    output_dir = Path(output_dir).resolve()
    runs_root = (PROJECT_ROOT / "runs").resolve()
    try:
        output_dir.relative_to(runs_root)
    except ValueError:
        raise ValueError("science artifact export must be under the project runs directory") from None
    if not output_dir.is_dir():
        raise ValueError("run evidence export directory must already exist")

    artifact_ids = [value for value in result.artifact_ids if value.startswith("nova-result-payload:")]
    artifact_paths = [value for value in result.artifact_ids if value.startswith("nova-artifact-path:")]
    if len(artifact_ids) != len(artifact_paths):
        raise ValueError("science payload IDs and paths are incomplete")
    exported = {}
    target_dir = output_dir / "science-artifacts"
    target_dir.mkdir(exist_ok=True)
    for artifact_id, path_ref in zip(artifact_ids, artifact_paths):
        digest = artifact_id.partition(":")[2]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("invalid content-addressed science payload ID")
        expected_relative = Path("runs") / f"science-payload-{digest}.json"
        if path_ref != f"nova-artifact-path:{expected_relative.as_posix()}":
            raise ValueError("science payload path does not match its content-addressed ID")
        source = PROJECT_ROOT / expected_relative
        source_bytes = source.read_bytes()
        if _sha256(source_bytes) != digest:
            raise ValueError("stored science payload checksum does not match its artifact ID")
        target_name = expected_relative.name
        target = target_dir / target_name
        if target.exists():
            if target.read_bytes() != source_bytes:
                raise FileExistsError("exported science payload already has different contents")
        else:
            shutil.copyfile(source, target)
        entry = {
            "artifact_id": artifact_id,
            "source_path": expected_relative.as_posix(),
            "exported_path": (Path("science-artifacts") / target_name).as_posix(),
            "sha256": digest,
            "size_bytes": len(source_bytes),
        }
        existing = exported.get(digest)
        if existing is not None and existing != entry:
            raise ValueError("duplicate science payload digest has inconsistent metadata")
        exported[digest] = entry

    manifest_path = output_dir / "science-artifacts.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("existing science artifact manifest has an unsupported schema")
        if not isinstance(manifest.get("results"), list) or not isinstance(manifest.get("artifacts"), list):
            raise ValueError("existing science artifact manifest is malformed")
    else:
        manifest = {"schema_version": 1, "results": [], "artifacts": []}

    result_entry = {
        "result_id": result.result_id,
        "experiment_id": result.experiment_id,
        "registered_spec_sha256": result.spec_sha256,
        "artifact_ids": [entry["artifact_id"] for entry in exported.values()],
    }
    prior_result = next(
        (item for item in manifest["results"] if item.get("result_id") == result.result_id),
        None,
    )
    if prior_result is not None and prior_result != result_entry:
        raise ValueError("result ID already has different science artifact references")
    if prior_result is None:
        manifest["results"].append(result_entry)

    known = {item.get("sha256"): item for item in manifest["artifacts"]}
    for digest, entry in exported.items():
        if digest in known and known[digest] != entry:
            raise ValueError("science artifact digest already has different manifest metadata")
        if digest not in known:
            manifest["artifacts"].append(entry)
    manifest_path.write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
    return manifest_path


def _run_science_template(template: Template, minimal: dict[str, Any]) -> dict[str, Any]:
    if template is Template.FAMILY_SCREEN:
        module = family_screen
    else:
        # Threshold code is loaded only when a registered threshold experiment
        # is selected. Its primary point is defined by the frozen 0.05 limit.
        from nova.experiments import threshold_sensitivity

        module = threshold_sensitivity
    value = module.run_experiment(minimal)
    if not isinstance(value, Mapping):
        raise TypeError("science template must return a mapping")
    return dict(value)


def execute(spec: Mapping[str, Any]) -> Result:
    """Execute a registered live science spec and adapt it to the shared Result.

    Registry authorization, wall clock cancellation, and worker lifecycle
    belong to B's host workflow. This function accepts only registered data
    fields plus host mode/run metadata; mode/run metadata do not register or
    authorize an experiment. The 120 second contract field is validated here,
    while its enforcement remains the host's responsibility.
    """
    contract = _normalise_and_validate(spec)
    minimal = _minimal_science_spec(contract)
    computation_sha256 = _computation_spec_sha256(minimal)
    raw = _run_science_template(contract.template, minimal)

    if raw.get("execution_status") != _SUCCESS:
        raise RuntimeError("science template did not complete successfully")
    if raw.get("template") != contract.template.value:
        raise ValueError("science result template does not match the registered template")
    if raw.get("dataset_sha256") != contract.dataset_sha256:
        raise ValueError("science result dataset does not match the registered dataset")
    if raw.get("spec_sha256") != computation_sha256:
        raise ValueError("science result computation spec hash does not match executor input")
    scientific_status = raw.get("scientific_status")
    if scientific_status not in _SCIENTIFIC_STATES:
        raise ValueError("science result has an invalid scientific_status")

    groups = _groups_summary(raw.get("groups_summary"))
    started_at = raw.get("started_at")
    finished_at = raw.get("finished_at")
    elapsed = raw.get("elapsed_seconds")
    if not isinstance(started_at, str) or not started_at:
        raise ValueError("science result is missing started_at")
    if not isinstance(finished_at, str) or not finished_at:
        raise ValueError("science result is missing finished_at")
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("science result has invalid elapsed_seconds")

    artifact_body = _artifact_body(raw, contract, computation_sha256)
    artifact_id, artifact_path = _write_immutable_artifact(artifact_body)
    payload_sha256 = artifact_id.partition(":")[2]
    result_id = "nova-result-" + _sha256(
        _canonical_json({
            "experiment_id": contract.experiment_id,
            "spec_sha256": contract.sha256,
            "payload_sha256": payload_sha256,
        }).encode("utf-8")
    )

    raw_artifacts = raw.get("artifact_ids", ())
    if not isinstance(raw_artifacts, (tuple, list)) or any(not isinstance(item, str) for item in raw_artifacts):
        raise ValueError("science result artifact_ids must be a sequence of strings")
    artifact_ids = tuple(raw_artifacts) + (
        artifact_id,
        f"nova-artifact-path:{artifact_path}",
    )
    quality_flags = raw.get("quality_flags")
    quality_entry = "science-quality-json-v1:" + _canonical_json(quality_flags)

    return Result(
        result_id=result_id,
        experiment_id=contract.experiment_id,
        spec_sha256=contract.sha256,
        dataset_sha256=contract.dataset_sha256,
        execution_status=_COMPLETED,
        scientific_status=scientific_status,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_seconds=float(elapsed),
        groups_summary=groups,
        delta=raw.get("delta"),
        resampling_interval=_interval(raw.get("resampling_interval"), "resampling_interval"),
        missingness_interval=_interval(raw.get("missingness_interval"), "missingness_interval"),
        quality_flags=(quality_entry,),
        artifact_ids=artifact_ids,
        error=None,
    )


__all__ = ["active_dataset_sha256", "execute", "export_science_artifacts"]
