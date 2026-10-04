from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest

from nova import holdout_bridge
from nova.experiments import executor, family_screen, threshold_sensitivity
from scripts import audit_discovery_bundle as audit


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs" / "results" / "native_adaptive_live_01_failed"


def _canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                        allow_nan=False) + "\n").encode("utf-8")


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                                allow_nan=False) + "\n", encoding="utf-8")


def _count(name: str, raw: bytes) -> int:
    if name.endswith(".jsonl"):
        return len(raw.decode("utf-8").splitlines())
    value = json.loads(raw.decode("utf-8"))
    if name in {"specs.json", "results.json", "reviews.json"}:
        return len(value)
    if name == "science-artifacts.json":
        return len(value["results"])
    return 1


def _refresh_manifest(package: Path, names: tuple[str, ...]) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in names:
        raw = (package / Path(*Path(name).parts)).read_bytes()
        manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "count": _count(name, raw)}
    _write_json(manifest_path, manifest)


def _copy_fixture(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    package = tmp_path / "evidence"
    shutil.copytree(FIXTURE, package)
    return package


@pytest.fixture
def output_dir():
    output = ROOT / "runs" / f"test-discovery-audit-{uuid.uuid4().hex}"
    try:
        yield output
    finally:
        if output.exists():
            assert output.parent == ROOT / "runs"
            shutil.rmtree(output)


def _assert_rejected(package: Path, output: Path) -> str:
    with pytest.raises(audit.AuditError) as error:
        audit.audit_bundle(package, output)
    assert not output.exists()
    return str(error.value)


def _assert_bridge_rejection(package: Path, output: Path, monkeypatch, expected: str) -> None:
    original = holdout_bridge._artifact_payload
    observed = []

    def capture(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except ValueError as error:
            observed.append(str(error))
            raise

    monkeypatch.setattr(holdout_bridge, "_artifact_payload", capture)
    message = _assert_rejected(package, output)
    assert message == "discovery evidence audit failed"
    assert any(expected in item for item in observed)


def _rewrite_threshold_payload(package: Path, mutate) -> str:
    index_path = package / "science-artifacts.json"
    result_path = package / "results.json"
    events_path = package / "events.jsonl"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    results = json.loads(result_path.read_text(encoding="utf-8"))
    artifact = next(item for item in index["artifacts"] if item["artifact_id"].startswith("nova-result-payload:b7"))
    old_name = artifact["exported_path"]
    old_artifact_id = artifact["artifact_id"]
    old_source_path = artifact["source_path"]
    body = json.loads((package / Path(*Path(old_name).parts)).read_text(encoding="utf-8"))
    mutate(body)
    raw = _canonical(body)
    digest = hashlib.sha256(raw).hexdigest()
    new_name = f"science-artifacts/science-payload-{digest}.json"
    new_source_path = f"runs/science-payload-{digest}.json"
    new_artifact_id = f"nova-result-payload:{digest}"
    old_file = package / Path(*Path(old_name).parts)
    new_file = package / Path(*Path(new_name).parts)
    new_file.write_bytes(raw)
    old_file.unlink()
    artifact.update({"artifact_id": new_artifact_id, "exported_path": new_name,
                     "sha256": digest, "size_bytes": len(raw), "source_path": new_source_path})

    child_result = next(item for item in results if item["experiment_id"] == "NOVA-cd3b328843109e3d")
    old_result_id = child_result["result_id"]
    child_result["result_id"] = "nova-result-" + hashlib.sha256(_canonical({
        "experiment_id": child_result["experiment_id"],
        "spec_sha256": child_result["spec_sha256"],
        "payload_sha256": digest,
    }).strip()).hexdigest()
    child_result["artifact_ids"] = [
        new_artifact_id if item == old_artifact_id else
        f"nova-artifact-path:{new_source_path}" if item == f"nova-artifact-path:{old_source_path}" else item
        for item in child_result["artifact_ids"]
    ]
    index_result = next(item for item in index["results"] if item["experiment_id"] == child_result["experiment_id"])
    index_result["artifact_ids"] = [new_artifact_id]
    index_result["result_id"] = child_result["result_id"]
    event_lines = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    for event in event_lines:
        if event.get("event_type") == "result" and event.get("payload_ref") == old_result_id:
            event["payload_ref"] = child_result["result_id"]
    events_path.write_bytes(b"".join(_canonical(event) for event in event_lines))

    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].pop(old_name)
    manifest["files"][new_name] = {"sha256": digest, "count": 1}
    _write_json(index_path, index)
    _write_json(result_path, results)
    _refresh_manifest(package, ("science-artifacts.json", "results.json", "events.jsonl"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].pop(old_name, None)
    manifest["files"][new_name] = {"sha256": digest, "count": 1}
    _write_json(manifest_path, manifest)
    return digest


@pytest.mark.skipif(os.name == "nt", reason="the existing bridge private-file check requires POSIX mode bits")
def test_real_bundle_passes_bridge_with_distinct_registered_and_computation_hashes(
        output_dir: Path, monkeypatch):
    before = {path.relative_to(FIXTURE): path.read_bytes() for path in FIXTURE.rglob("*") if path.is_file()}
    calls = {"artifact_validator": 0}
    original_validator = holdout_bridge._artifact_payload

    def count_validator(*args, **kwargs):
        calls["artifact_validator"] += 1
        return original_validator(*args, **kwargs)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("audit must not execute science")

    monkeypatch.setattr(holdout_bridge, "_artifact_payload", count_validator)
    monkeypatch.setattr(executor, "execute", forbidden)
    monkeypatch.setattr(executor, "execute_holdout", forbidden, raising=False)
    monkeypatch.setattr(executor, "_run_science_template", forbidden)
    monkeypatch.setattr(family_screen, "run_experiment", forbidden)
    monkeypatch.setattr(threshold_sensitivity, "run_experiment", forbidden)

    assert audit.main(["--evidence-dir", str(FIXTURE), "--output", str(output_dir)]) == 0
    assert calls["artifact_validator"] == 2
    assert {path.relative_to(FIXTURE): path.read_bytes() for path in FIXTURE.rglob("*") if path.is_file()} == before
    assert {item.name for item in output_dir.iterdir()} == {"audit.json", "manifest.json"}

    report = json.loads((output_dir / "audit.json").read_text(encoding="utf-8"))
    assert [item["role"] for item in report["results"]] == ["family_screen", "threshold_sensitivity"]
    for item in report["results"]:
        assert item["registered_spec_sha256"] != item["expected_computation_spec_sha256"]
        assert item["payload_sha256"]
    assert [point["threshold_ev_atom"] for point in report["threshold_grid"]] == [0.025, 0.05, 0.1]
    assert report["validation_scope"]["new_model_calls"] == 0
    assert report["validation_scope"]["new_science_executions"] == 0
    assert report["validation_scope"]["holdout_outcomes_read"] is False
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["audit.json"]["sha256"] == hashlib.sha256(
        (output_dir / "audit.json").read_bytes()).hexdigest()


@pytest.mark.skipif(os.name == "nt", reason="the existing bridge private-file check requires POSIX mode bits")
@pytest.mark.parametrize("field", ["registered_spec_sha256", "computation_spec_sha256"])
def test_resigned_payload_with_changed_contract_hash_is_rejected(
        field: str, tmp_path: Path, output_dir: Path, monkeypatch):
    package = _copy_fixture(tmp_path)

    def mutate(body):
        body[field] = "0" * 64

    _rewrite_threshold_payload(package, mutate)
    if field == "computation_spec_sha256":
        _assert_bridge_rejection(package, output_dir, monkeypatch, "computation hash does not match")
    else:
        _assert_bridge_rejection(package, output_dir, monkeypatch, "identity does not match its registered spec")


@pytest.mark.skipif(os.name == "nt", reason="the existing bridge private-file check requires POSIX mode bits")
def test_altered_stored_result_facts_are_rejected(tmp_path: Path, output_dir: Path, monkeypatch):
    package = _copy_fixture(tmp_path)
    results_path = package / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    results[0]["delta"] += 0.001
    _write_json(results_path, results)
    _refresh_manifest(package, ("results.json",))
    _assert_bridge_rejection(package, output_dir, monkeypatch, "stored Result fields do not match")


@pytest.mark.skipif(os.name == "nt", reason="the existing bridge private-file check requires POSIX mode bits")
def test_incorrect_primary_point_is_rejected(tmp_path: Path, output_dir: Path):
    package = _copy_fixture(tmp_path)

    def mutate(body):
        body["science_result"]["main_point"]["delta"] += 0.001

    _rewrite_threshold_payload(package, mutate)
    assert "main point" in _assert_rejected(package, output_dir)


@pytest.mark.skipif(os.name == "nt", reason="the existing bridge private-file check requires POSIX mode bits")
def test_internally_consistent_grid_total_change_is_rejected(tmp_path: Path, output_dir: Path):
    package = _copy_fixture(tmp_path)

    def mutate(body):
        science = body["science_result"]
        point = science["points"][0]
        oxide = point["groups_summary"]["oxide"]
        oxide["n_total"] += 1
        oxide["coverage"] = oxide["n_observed"] / oxide["n_total"]
        oxide["missing_lower"] = oxide["n_pass"] / oxide["n_total"]
        oxide["missing_upper"] = (oxide["n_pass"] + oxide["n_total"] - oxide["n_observed"]) / oxide["n_total"]
        missing = point["missingness_interval"]
        chalc = point["groups_summary"]["chalcogenide"]
        missing.update({
            "oxide_rate_lower": oxide["missing_lower"], "oxide_rate_upper": oxide["missing_upper"],
            "lower": chalc["missing_lower"] - oxide["missing_upper"],
            "upper": chalc["missing_upper"] - oxide["missing_lower"],
        })
        point["quality_flags"]["missingness_bounds_cross_zero"] = missing["lower"] <= 0 <= missing["upper"]
        assert audit._validate_point(point, 0.025)["groups_summary"]["oxide"]["n_total"] == oxide["n_total"]

    _rewrite_threshold_payload(package, mutate)
    message = _assert_rejected(package, output_dir)
    assert "counts" in message


@pytest.mark.skipif(os.name == "nt", reason="the existing bridge private-file check requires POSIX mode bits")
def test_internally_consistent_nonmonotonic_pass_count_is_rejected(tmp_path: Path, output_dir: Path):
    package = _copy_fixture(tmp_path)

    def mutate(body):
        science = body["science_result"]
        point = science["points"][2]
        chalc = point["groups_summary"]["chalcogenide"]
        chalc["n_pass"] = 4
        chalc["observed_rate"] = chalc["n_pass"] / chalc["n_observed"]
        chalc["missing_lower"] = chalc["n_pass"] / chalc["n_total"]
        chalc["missing_upper"] = (chalc["n_pass"] + chalc["n_total"] - chalc["n_observed"]) / chalc["n_total"]
        oxide = point["groups_summary"]["oxide"]
        point["delta"] = chalc["observed_rate"] - oxide["observed_rate"]
        point["bootstrap"]["delta"] = point["delta"]
        missing = point["missingness_interval"]
        missing.update({
            "chalcogenide_rate_lower": chalc["missing_lower"],
            "chalcogenide_rate_upper": chalc["missing_upper"],
            "lower": chalc["missing_lower"] - oxide["missing_upper"],
            "upper": chalc["missing_upper"] - oxide["missing_lower"],
        })
        assert audit._validate_point(point, 0.1)["groups_summary"]["chalcogenide"]["n_pass"] == 4

    _rewrite_threshold_payload(package, mutate)
    assert "counts" in _assert_rejected(package, output_dir)


def test_mismatched_source_run_and_parent_link_are_rejected(tmp_path: Path, output_dir: Path):
    package = _copy_fixture(tmp_path)
    event_path = package / "events.jsonl"
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    events[0]["run_id"] = "different-run"
    event_path.write_bytes(b"".join(_canonical(item) for item in events))
    _refresh_manifest(package, ("events.jsonl",))
    assert "run event identity" in _assert_rejected(package, output_dir)

    package = _copy_fixture(tmp_path / "parent")
    specs_path = package / "specs.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    specs[1]["parent_result_id"] = "nova-result-wrong-parent"
    specs[1]["review_id"] = "nova-result-wrong-parent"
    _write_json(specs_path, specs)
    results_path = package / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    child = next(item for item in results if item["experiment_id"] == specs[1]["experiment_id"])
    child["spec_sha256"] = audit.ExperimentSpec.from_dict(specs[1]).sha256
    _write_json(results_path, results)
    _refresh_manifest(package, ("specs.json",))
    _refresh_manifest(package, ("results.json",))
    assert "parent result" in _assert_rejected(package, output_dir)


def test_missing_payload_and_manifest_path_traversal_are_rejected(tmp_path: Path, output_dir: Path):
    package = _copy_fixture(tmp_path)
    payload = next((package / "science-artifacts").glob("science-payload-*.json"))
    payload.unlink()
    assert "unavailable" in _assert_rejected(package, output_dir)

    package = _copy_fixture(tmp_path / "traversal")
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["../private.json"] = {"sha256": "0" * 64, "count": 1}
    _write_json(manifest_path, manifest)
    assert "unsupported package path" in _assert_rejected(package, output_dir)


def test_optional_native_metadata_is_allowlisted_but_still_checked(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    package = _copy_fixture(tmp_path)
    metadata = {
        "README.md": b"# Native discovery evidence\n",
        "host-recovery.json": _canonical({"recovery_type": "hash_bound_transport_witness_recorded"}),
        "native-finalization-evidence.json": _canonical({"holdout_execution_status": "not_tested"}),
    }
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, raw in metadata.items():
        (package / name).write_bytes(raw)
        manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "count": 1}
    _write_json(manifest_path, manifest)

    output = audit.audit_bundle(package, tmp_path / "runs" / "metadata-audit")
    report = json.loads((output / "audit.json").read_text(encoding="utf-8"))
    assert report["source_sha256"]["README.md"] == hashlib.sha256(metadata["README.md"]).hexdigest()
    assert report["source_sha256"]["host-recovery.json"] == hashlib.sha256(
        metadata["host-recovery.json"]).hexdigest()

    tampered = _copy_fixture(tmp_path / "tampered")
    manifest_path = tampered / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, raw in metadata.items():
        (tampered / name).write_bytes(raw)
        manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "count": 1}
    _write_json(manifest_path, manifest)
    (tampered / "host-recovery.json").write_text("{}\n", encoding="utf-8")
    assert "digest does not match manifest" in _assert_rejected(
        tampered, tmp_path / "runs" / "tampered-audit")

    linked = _copy_fixture(tmp_path / "linked")
    manifest_path = linked / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, raw in metadata.items():
        (linked / name).write_bytes(raw)
        manifest["files"][name] = {"sha256": hashlib.sha256(raw).hexdigest(), "count": 1}
    _write_json(manifest_path, manifest)
    (linked / "README.md").unlink()
    (linked / "README.md").symlink_to("events.jsonl")
    assert "unsafe" in _assert_rejected(linked, tmp_path / "runs" / "linked-audit")


def test_holdout_spec_is_rejected_before_outcome_files_are_read(tmp_path: Path, output_dir: Path, monkeypatch):
    package = _copy_fixture(tmp_path)
    specs_path = package / "specs.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    specs[0]["split"] = "holdout"
    _write_json(specs_path, specs)
    _refresh_manifest(package, ("specs.json",))
    reads = []
    original = audit._read_relative

    def spy(root: Path, name: str):
        reads.append(name)
        assert name not in {"results.json", "science-artifacts.json"} and not name.startswith("science-artifacts/")
        return original(root, name)

    monkeypatch.setattr(audit, "_read_relative", spy)
    assert "holdout" in _assert_rejected(package, output_dir)
    assert reads == ["manifest.json", "specs.json"]


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}'])
def test_strict_json_rejects_duplicate_keys_and_nonfinite_values(raw: bytes):
    with pytest.raises(audit.AuditError):
        audit._strict_json(raw)


@pytest.mark.skipif(os.name == "nt", reason="the existing bridge private-file check requires POSIX mode bits")
def test_direct_cli_invocation_creates_runs_in_a_clean_checkout(tmp_path: Path):
    project = tmp_path / "fresh-checkout"
    project.mkdir()
    shutil.copytree(ROOT / "nova", project / "nova", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (project / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "audit_discovery_bundle.py", project / "scripts" / "audit_discovery_bundle.py")
    evidence = project / "docs" / "results" / "published"
    evidence.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE, evidence)
    assert not (project / "runs").exists()

    completed = subprocess.run(
        [sys.executable, str(project / "scripts" / "audit_discovery_bundle.py"),
         "--evidence-dir", str(evidence), "--output", "runs/cli-audit"],
        cwd=project, text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert {item.name for item in (project / "runs" / "cli-audit").iterdir()} == {"audit.json", "manifest.json"}
