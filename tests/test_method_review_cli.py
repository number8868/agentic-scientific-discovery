from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import urllib.request
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_method_review.py"
spec = importlib.util.spec_from_file_location("check_method_review", SCRIPT)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _assert_output_hashes(output: Path):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in manifest["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == entry["sha256"]


def _synthetic_package(directory: Path):
    directory.mkdir(parents=True)
    body = {
        "artifact_type": "nova.method_evidence.v1",
        "request": {"audit_id": "AUDIT-SYNTH", "run_id": "RUN-SYNTH"},
        "registered_execution": {"audit_id": "AUDIT-SYNTH", "run_id": "RUN-SYNTH"},
    }
    audit_bytes = _json_bytes(body)
    audit_sha = hashlib.sha256(audit_bytes).hexdigest()
    packet = {
        "artifact_type": "nova.method_evidence_packet.v1",
        "evidence_file": "method-audit.json",
        "evidence_sha256": audit_sha,
        "references": [{"ref_id": "arm-opt", "evidence_sha256": audit_sha}],
    }
    packet_bytes = _json_bytes(packet)
    manifest = {
        "schema_version": 1,
        "run_id": "RUN-SYNTH",
        "files": {
            "method-audit.json": {"sha256": audit_sha},
            "method-evidence.json": {"sha256": hashlib.sha256(packet_bytes).hexdigest()},
        },
        "method_audit": {
            "audit_id": "AUDIT-SYNTH",
            "evidence_file": "method-audit.json",
            "citations_file": "method-evidence.json",
            "evidence_sha256": audit_sha,
        },
    }
    (directory / "manifest.json").write_bytes(_json_bytes(manifest))
    (directory / "method-audit.json").write_bytes(audit_bytes)
    (directory / "method-evidence.json").write_bytes(packet_bytes)
    return {"manifest.json": (directory / "manifest.json").read_bytes(),
            "method-audit.json": audit_bytes, "method-evidence.json": packet_bytes}


def _fake_api(monkeypatch, *, reject=False):
    seen = {}

    def build(body, packet, *, candidate_jids=None, available_actions=("stop",)):
        seen["build"] = (body, packet, candidate_jids, available_actions)
        return {
            "schema_version": 1,
            "artifact_type": "nova.method_review_input.v1",
            "review_input_sha256": "0" * 64,
            "evidence_sha256": packet["evidence_sha256"],
            "selection": {"mode": "host_selected_explicit" if candidate_jids else "host_selected_default_sample",
                          "selected_jids": list(candidate_jids or ["JVASP-SYNTH-1"])},
            "available_actions": list(available_actions),
        }

    def schema(review_input):
        seen["schema"] = review_input
        return {"type": "object", "required": ["recommendation"]}

    def validate(review, review_input):
        seen["validate"] = (review, review_input)
        if reject or review.get("review_input_sha256") != review_input["review_input_sha256"]:
            raise ValueError("synthetic mismatch detail should not appear in CLI output")
        return dict(review)

    monkeypatch.setitem(sys.modules, "nova.method_review", SimpleNamespace(
        build_method_review_input=build,
        method_review_output_schema=schema,
        validate_method_review=validate,
    ))
    return seen


def _run_paths(tmp_path, monkeypatch, package_bytes):
    project = tmp_path / "project"
    runs = project / "runs"
    evidence = project / "portable"
    runs.mkdir(parents=True)
    evidence.mkdir()
    for name, data in package_bytes.items():
        (evidence / name).write_bytes(data)
    monkeypatch.setattr(cli, "ROOT", project)
    return evidence, runs


def _published_package(tmp_path, monkeypatch):
    published = ROOT / "docs" / "results" / "registered_method_integration"
    package = {name: (published / name).read_bytes() for name in cli.SOURCE_FILENAMES}
    evidence, runs = _run_paths(tmp_path, monkeypatch, package)
    return evidence, runs


def _valid_synthetic_review(review_input):
    arms = [
        {
            "arm": arm["name"],
            "source_ref_id": arm["source_ref"]["ref_id"],
            "scientific_status": arm["scientific_status"],
            "delta": arm["delta"],
            "resampling_interval": arm["resampling_interval"],
            "groups_summary": arm["groups_summary"],
            "assessment": "Synthetic structured assessment.",
        }
        for arm in review_input["arms"]
    ]
    change = review_input["method_change"]
    method_change = {
        "kind": "paired_method_change",
        "source_ref_id": change["source_ref"]["ref_id"],
        "scientific_status": change["scientific_status"],
        "delta": change["delta"],
        "resampling_interval": change["resampling_interval"],
        "groups_summary": change["groups_summary"],
        "assessment": "Synthetic structured assessment.",
    }
    candidates = [
        {
            "jid": candidate["jid"],
            "source_ref_id": candidate["source_ref"]["ref_id"],
            "family": candidate["family"],
            "opt_gap_ev": candidate["opt_gap_ev"],
            "mbj_gap_ev": candidate["mbj_gap_ev"],
            "ehull_ev_atom": candidate["ehull_ev_atom"],
            "opt_status": candidate["opt_status"],
            "mbj_status": candidate["mbj_status"],
            "category": candidate["candidate_label"],
            "next_validation": candidate["next_validation"],
            "assessment": "Synthetic candidate assessment.",
        }
        for candidate in review_input["candidates"]
    ]
    refs = [arm["source_ref"]["ref_id"] for arm in review_input["arms"]]
    refs.append(review_input["method_change"]["source_ref"]["ref_id"])
    refs.extend(candidate["source_ref"]["ref_id"] for candidate in review_input["candidates"])
    return {
        "review_input_sha256": review_input["review_input_sha256"],
        "evidence_sha256": review_input["evidence_sha256"],
        "arms": arms,
        "method_change": method_change,
        "candidates": candidates,
        "limitations": review_input["required_limitations"],
        "recommendation": {
            "action": "stop",
            "evidence_refs": refs,
            "rationale": "Synthetic bounded recommendation.",
        },
    }


def test_published_portable_package_builds_input_and_schema_without_mutation(tmp_path, monkeypatch):
    published = ROOT / "docs" / "results" / "registered_method_integration"
    package = {name: (published / name).read_bytes() for name in cli.SOURCE_FILENAMES}
    evidence, runs = _run_paths(tmp_path, monkeypatch, package)
    before = {name: (evidence / name).read_bytes() for name in cli.SOURCE_FILENAMES}
    output = runs / "published-review-input"

    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 0

    review_input = json.loads((output / "review-input.json").read_text(encoding="utf-8"))
    output_schema = json.loads((output / "review-output-schema.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert review_input["artifact_type"] == "nova.method_review_input.v1"
    assert len(review_input["arms"]) == 3
    assert review_input["method_change"]["source_ref"]["evidence_sha256"] == review_input["evidence_sha256"]
    assert output_schema["type"] == "object"
    assert manifest["scope"]["source_files_read"] == list(cli.SOURCE_FILENAMES)
    assert manifest["scope"]["other_package_files_read"] is False
    assert manifest["selection"]["available_actions"] == ["stop"]
    assert not (output / "accepted-review.json").exists()
    assert {name: (evidence / name).read_bytes() for name in cli.SOURCE_FILENAMES} == before
    _assert_output_hashes(output)


def test_preparation_discloses_requested_selection_and_requires_fresh_output(tmp_path, monkeypatch):
    seen = _fake_api(monkeypatch)
    package = _synthetic_package(tmp_path / "source")
    evidence, runs = _run_paths(tmp_path / "workspace", monkeypatch, package)
    output = runs / "scoped"
    assert cli.main([
        "--evidence-dir", str(evidence), "--output", str(output),
        "--candidate-jid", "JVASP-SYNTH-1", "--available-action", "threshold_sensitivity",
    ]) == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert seen["build"][2:] == (["JVASP-SYNTH-1"], ("stop", "threshold_sensitivity"))
    assert manifest["selection"] == {
        "requested_candidate_jids": ["JVASP-SYNTH-1"],
        "selected_candidate_jids": ["JVASP-SYNTH-1"],
        "available_actions": ["stop", "threshold_sensitivity"],
    }
    assert set(manifest["files"]) == {"review-input.json", "review-output-schema.json"}
    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 1


def test_valid_external_review_is_accepted_with_limits_recorded(tmp_path, monkeypatch, capsys):
    evidence, runs = _published_package(tmp_path / "workspace", monkeypatch)
    body, packet, _ = cli._load_evidence_package(evidence)
    review_input = cli._build_input(body, packet, None, ["stop"])
    review = _valid_synthetic_review(review_input)
    review_file = tmp_path / "external-review.json"
    review_file.write_bytes(_json_bytes(review))
    output = runs / "accepted"

    assert cli.main([
        "--evidence-dir", str(evidence), "--review-json", str(review_file), "--output", str(output),
    ]) == 0

    assert json.loads((output / "accepted-review.json").read_text(encoding="utf-8")) == review
    validation = json.loads((output / "validation.json").read_text(encoding="utf-8"))
    assert validation["structured_references"] == "passed"
    assert validation["structured_facts"] == "passed"
    assert validation["free_text_semantics"] == "not_verified"
    assert validation["model_source_authenticity"] == "not_verified"
    assert validation["independent_skeptic_turn"] == "not_verified"
    assert validation["review_input_sha256"] == review_input["review_input_sha256"]
    assert validation["evidence_sha256"] == review_input["evidence_sha256"]
    assert "model" not in capsys.readouterr().out.lower()
    _assert_output_hashes(output)


def test_rejected_review_creates_no_output_and_hides_review_content(tmp_path, monkeypatch, capsys):
    evidence, runs = _published_package(tmp_path / "workspace", monkeypatch)
    body, packet, _ = cli._load_evidence_package(evidence)
    review_input = cli._build_input(body, packet, None, ["stop"])
    review = _valid_synthetic_review(review_input)
    review["arms"][0]["source_ref_id"] = "foreign-reference"
    review["candidates"][0]["assessment"] = "never echo this private review text"
    review_file = tmp_path / "external-review.json"
    review_file.write_bytes(_json_bytes(review))
    output = runs / "rejected"

    assert cli.main([
        "--evidence-dir", str(evidence), "--review-json", str(review_file), "--output", str(output),
    ]) == 1
    assert not output.exists()
    assert "never echo this private review text" not in capsys.readouterr().err


def test_source_tamper_or_invalid_manifest_is_rejected_before_output(tmp_path, monkeypatch):
    _fake_api(monkeypatch)
    package = _synthetic_package(tmp_path / "source")
    evidence, runs = _run_paths(tmp_path / "tampered", monkeypatch, package)
    (evidence / "method-audit.json").write_bytes(package["method-audit.json"] + b" ")
    output = runs / "tampered"
    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 1
    assert not output.exists()

    # Restore the source and corrupt only the manifest's expected packet hash.
    (evidence / "method-audit.json").write_bytes(package["method-audit.json"])
    invalid_manifest = json.loads(package["manifest.json"])
    invalid_manifest["files"]["method-evidence.json"]["sha256"] = "f" * 64
    (evidence / "manifest.json").write_bytes(_json_bytes(invalid_manifest))
    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 1
    assert not output.exists()


def test_invalid_json_duplicates_and_non_finite_numbers_are_rejected(tmp_path, monkeypatch):
    _fake_api(monkeypatch)
    package = _synthetic_package(tmp_path / "source")
    evidence, runs = _run_paths(tmp_path / "invalid-json", monkeypatch, package)
    (evidence / "manifest.json").write_text('{"files":{},"files":{}}', encoding="utf-8")
    output = runs / "duplicate"
    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 1
    assert not output.exists()

    (evidence / "manifest.json").write_bytes(package["manifest.json"])
    review_file = tmp_path / "nonfinite.json"
    review_file.write_text('{"value":1e999}', encoding="utf-8")
    output = runs / "nonfinite"
    assert cli.main([
        "--evidence-dir", str(evidence), "--review-json", str(review_file), "--output", str(output),
    ]) == 1
    assert not output.exists()


def test_cli_uses_only_pure_contract_and_never_opens_storage(tmp_path, monkeypatch):
    seen = _fake_api(monkeypatch)
    package = _synthetic_package(tmp_path / "source")
    evidence, runs = _run_paths(tmp_path / "pure-only", monkeypatch, package)
    import nova.storage

    def forbidden(*_args, **_kwargs):
        raise AssertionError("method-review CLI must not access run storage")

    monkeypatch.setattr(nova.storage, "Storage", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    output = runs / "pure"
    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 0
    assert "build" in seen and "schema" in seen


@pytest.mark.parametrize("mismatch", ["run_id", "audit_id"])
def test_manifest_ownership_mismatch_is_rejected(tmp_path, monkeypatch, mismatch):
    _fake_api(monkeypatch)
    package = _synthetic_package(tmp_path / "source")
    evidence, runs = _run_paths(tmp_path / "ownership", monkeypatch, package)
    manifest = json.loads(package["manifest.json"])
    if mismatch == "run_id":
        manifest["run_id"] = "RUN-FOREIGN"
    else:
        manifest["method_audit"]["audit_id"] = "AUDIT-FOREIGN"
    (evidence / "manifest.json").write_bytes(_json_bytes(manifest))
    output = runs / f"foreign-{mismatch}"
    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 1
    assert not output.exists()


def test_source_symlink_is_rejected(tmp_path, monkeypatch):
    _fake_api(monkeypatch)
    package = _synthetic_package(tmp_path / "source")
    evidence, runs = _run_paths(tmp_path / "unsafe-paths", monkeypatch, package)
    outside = tmp_path / "external-audit.json"
    outside.write_bytes(package["method-audit.json"])
    audit_path = evidence / "method-audit.json"
    audit_path.unlink()
    try:
        audit_path.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {type(exc).__name__}")
    output = runs / "symlink"
    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 1
    assert not output.exists()


def test_output_path_traversal_is_rejected(tmp_path, monkeypatch):
    _fake_api(monkeypatch)
    package = _synthetic_package(tmp_path / "source")
    evidence, runs = _run_paths(tmp_path / "output-traversal", monkeypatch, package)
    traversal = str(runs / ".." / "escaped")
    assert cli.main(["--evidence-dir", str(evidence), "--output", traversal]) == 1
    assert not (runs.parent / "escaped").exists()


def test_direct_script_invocation_imports_contract_from_project_root_and_creates_missing_runs(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "nova").mkdir()
    shutil.copyfile(SCRIPT, project / "scripts" / "check_method_review.py")
    (project / "nova" / "method_review.py").write_text(
        "def build_method_review_input(body, packet, *, candidate_jids=None, available_actions=('stop',)):\n"
        "    return {'artifact_type': 'nova.method_review_input.v1',\n"
        "            'selection': {'selected_jids': list(candidate_jids or ['JID-1'])},\n"
        "            'available_actions': list(available_actions),\n"
        "            'evidence_sha256': packet['evidence_sha256']}\n"
        "def method_review_output_schema(review_input):\n"
        "    return {'type': 'object'}\n"
        "def validate_method_review(review, review_input):\n"
        "    return review\n",
        encoding="utf-8",
        newline="\n",
    )
    evidence = project / "portable"
    package = _synthetic_package(evidence)
    script = project / "scripts" / "check_method_review.py"
    output = project / "runs" / "direct-script"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)

    completed = subprocess.run(
        [sys.executable, str(script), "--evidence-dir", str(evidence), "--output", str(output)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.is_dir()
    assert json.loads((output / "review-input.json").read_text(encoding="utf-8"))["evidence_sha256"] == \
        json.loads(package["method-evidence.json"])["evidence_sha256"]
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["scope"]["model_call_made"] is False


def test_direct_subprocess_uses_actual_contract_with_published_package(tmp_path):
    published = ROOT / "docs" / "results" / "registered_method_integration"
    source = {name: (published / name).read_bytes() for name in cli.SOURCE_FILENAMES}
    output = ROOT / "runs" / f".method-review-cli-{uuid.uuid4().hex}"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)

    try:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--evidence-dir", str(published), "--output", str(output)],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        prepared = json.loads((output / "review-input.json").read_text(encoding="utf-8"))
        assert prepared["artifact_type"] == "nova.method_review_input.v1"
        assert prepared["evidence_sha256"] == hashlib.sha256(source["method-audit.json"]).hexdigest()
    finally:
        # Delete only this fresh, uniquely named direct child after verifying
        # the resolved parent remains the project runs directory.
        if output.exists():
            assert output.parent.resolve() == (ROOT / "runs").resolve()
            shutil.rmtree(output)
    assert {name: (published / name).read_bytes() for name in cli.SOURCE_FILENAMES} == source


def test_package_loader_does_not_read_results_events_or_science_files(tmp_path, monkeypatch):
    _fake_api(monkeypatch)
    package = _synthetic_package(tmp_path / "source")
    evidence, runs = _run_paths(tmp_path / "narrow-read", monkeypatch, package)
    for name in ("results.json", "events.jsonl", "science-artifacts.json", "holdout.json"):
        (evidence / name).write_bytes(b"must-not-be-opened\xff")
    read_names = set()
    original_read_bytes = Path.read_bytes

    def tracked_read_bytes(path):
        if path.parent == evidence:
            read_names.add(path.name)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read_bytes)
    output = runs / "narrow"
    assert cli.main(["--evidence-dir", str(evidence), "--output", str(output)]) == 0
    assert read_names == set(cli.SOURCE_FILENAMES)
