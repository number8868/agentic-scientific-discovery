from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

import pytest

from scripts import audit_discovery_bundle as audit


ROOT = Path(__file__).resolve().parents[1]
RUN03 = ROOT / "docs" / "results" / "native_adaptive_live_03_frozen_cli_failed"
LEGACY = ROOT / "docs" / "results" / "native_adaptive_live_01_failed"


def _canonical(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                        allow_nan=False) + "\n").encode("utf-8")


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                                allow_nan=False) + "\n", encoding="utf-8")


def _refresh_manifest(package: Path, *names: str) -> None:
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in names:
        raw = (package / Path(*Path(name).parts)).read_bytes()
        manifest["files"][name] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "count": audit._inventory_count(name, raw),
        }
    _write_json(manifest_path, manifest)
    hashes_path = package / "hashes.json"
    if hashes_path.exists():
        external_inventory = {name: entry["sha256"] for name, entry in manifest["files"].items()}
        external_inventory["manifest.json"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        _write_json(hashes_path, external_inventory)


def _copy_run03(tmp_path: Path) -> Path:
    package = tmp_path / "evidence"
    shutil.copytree(RUN03, package)
    return package


def _rewrite_json(package: Path, name: str, mutate) -> dict:
    path = package / name
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    _write_json(path, value)
    _refresh_manifest(package, name)
    return value


def _resign_protocol(package: Path, mutate) -> None:
    """Recompute the protocol, derived Spec and B stage hashes after a semantic edit."""
    sidecar_path = package / "native-finalization-evidence.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    protocol = sidecar["final_protocol"]["protocol"]
    mutate(protocol)
    protocol_sha = hashlib.sha256(json.dumps(
        protocol, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    frozen_id = "NOVA-FINAL-" + protocol_sha[:16]
    holdout_id = "NOVA-HOLDOUT-" + hashlib.sha256(
        f"{sidecar['run_id']}:{frozen_id}".encode("utf-8")).hexdigest()[:16]
    final = sidecar["final_protocol"]
    final.update({"frozen_protocol_id": frozen_id, "protocol_sha256": protocol_sha,
                  "holdout_experiment_id": holdout_id})
    state = sidecar["finalization_state"]
    state["parent_result_id"] = protocol["main_result_id"]
    state["followup_result_id"] = protocol["followup_result_id"]
    freeze = state["freeze"]
    freeze.update({"frozen_protocol_id": frozen_id, "protocol_sha256": protocol_sha,
                   "holdout_experiment_id": holdout_id, "explanation": protocol["explanation"]})
    state["freeze_sha256"] = hashlib.sha256(json.dumps(
        freeze, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()
    sidecar["holdout_spec"] = audit.holdout_bridge._derive_holdout(
        sidecar["run_id"], protocol, frozen_id).to_dict()
    _write_json(sidecar_path, sidecar)

    events_path = package / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    for event in events:
        if event["event_type"] in {"final_protocol_frozen", "native_adaptive_final_protocol_frozen"}:
            event["payload_ref"] = frozen_id
    events_path.write_bytes(b"".join(_canonical(event) for event in events))
    _refresh_manifest(package, "native-finalization-evidence.json", "events.jsonl")


def _append_event(events: list[dict], event_type: str, actor: str, payload_ref: str | None) -> None:
    events.append({
        "actor": actor,
        "attempt": 0,
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "mode": "live",
        "payload_ref": payload_ref,
        "run_id": "native-adaptive-live-03",
        "seq": len(events) + 1,
        "timestamp_utc": f"2026-10-04T03:09:{len(events):02d}.000000+00:00",
    })


def _add_pi_response(package: Path, *, redacted: bool, clean: bool, bad_export_hash: bool = False) -> None:
    sidecar_path = package / "native-finalization-evidence.json"
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    response_text = "Final PI response was safely shortened: Δ remains uncertain."
    original_text = "Private original final PI response with more detail." if redacted else response_text
    response_sha = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
    exported_sha = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
    sidecar["final_pi_response"] = {
        "response_text": response_text,
        "response_sha256": response_sha,
        "exported_response_sha256": "0" * 64 if bad_export_hash else exported_sha,
        "response_redacted": redacted,
    }
    _write_json(sidecar_path, sidecar)

    events_path = package / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    terminal_index = next(index for index, event in enumerate(events)
                          if event["event_type"] == "native_adaptive_orchestration_failed")
    events[terminal_index].update({
        "actor": "pi", "event_id": str(uuid.uuid4()),
        "event_type": "native_finalization_supervisor_response",
        "payload_ref": f"sha256:{response_sha}",
    })
    if clean:
        followup_id = sidecar["final_protocol"]["protocol"]["followup_result_id"]
        _append_event(events, "native_adaptive_finalization_supervisor_returned", "host", followup_id)
        _append_event(events, "native_adaptive_orchestration_completed", "host", None)
    else:
        _append_event(events, "native_adaptive_orchestration_failed", "host", None)
    events_path.write_bytes(b"".join(_canonical(event) for event in events))
    _refresh_manifest(package, "native-finalization-evidence.json", "events.jsonl")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_run03_frozen_discovery_evidence_passes_without_authorizing_execution():
    files, _ = audit._audit_document(RUN03, "runs/native03-audit-test-output")
    report = json.loads(files["audit.json"])
    preflight = report["native_finalization_preflight"]
    assert preflight["status"] == "frozen_discovery_evidence_verified"
    assert preflight["frozen_protocol_id"] == "NOVA-FINAL-cc1de78f42fd68a2"
    assert preflight["holdout_experiment_id"] == "NOVA-HOLDOUT-57e13139dc1893c8"
    assert preflight["holdout_spec_derivation_verified"] is True
    assert preflight["holdout_execution_attempt_evidence_found"] is False
    assert preflight["post_freeze_cli_failure_preserved"] is True
    assert preflight["final_pi_response_present"] is False
    assert preflight["final_pi_response_export_hash_verified"] is False
    assert preflight["final_pi_response_original_hash_verified"] is False
    scope = report["validation_scope"]
    assert scope["holdout_outcomes_read"] is False
    assert scope["native_completion_verified"] is False
    assert scope["native_cli_success_verified"] is False
    assert scope["native_holdout_runtime_authorization_established"] is False
    assert scope["runtime_gate_and_context_checks_required"] is True


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_legacy_no_sidecar_audit_output_is_byte_identical():
    files, _ = audit._audit_document(LEGACY, "runs/legacy-audit-test-output")
    assert hashlib.sha256(files["audit.json"]).hexdigest() == (
        "c8eee6b23cadf94abf4025f0114f1c92ac103e5c652c67d2835f27c31e81cc8f")
    assert hashlib.sha256(files["manifest.json"]).hexdigest() == (
        "aeeb837ad8953599770cdd37fb9f7ae84229e705e037d7f5722bab356e354358")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_rehashed_unsupported_finalization_placeholder_is_rejected(tmp_path: Path):
    package = tmp_path / "evidence"
    shutil.copytree(LEGACY, package)
    (package / "native-finalization-evidence.json").write_bytes(
        _canonical({"holdout_execution_status": "not_tested"}))
    _refresh_manifest(package, "native-finalization-evidence.json")
    with pytest.raises(audit.AuditError, match="native finalization evidence identity"):
        audit._audit_document(package, "runs/unsupported-finalization-output")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
@pytest.mark.parametrize(
    "field,value",
    [("gap_window_ev", [1.0, 1.8]), ("bandgap_method", "pbe")],
)
def test_resigned_protocol_with_changed_frozen_science_spec_is_rejected(
        field: str, value, tmp_path: Path):
    package = _copy_run03(tmp_path)

    def mutate(protocol):
        for key in ("main_spec", "followup_spec"):
            protocol[key][field] = value

    _resign_protocol(package, mutate)
    with pytest.raises(audit.AuditError, match="native frozen discovery ownership is invalid"):
        audit._audit_document(package, "runs/frozen-protocol-tamper-output")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_resigned_wrong_discovery_reference_is_rejected(tmp_path: Path):
    package = _copy_run03(tmp_path)
    _resign_protocol(package, lambda protocol: protocol.update({
        "main_result_id": "nova-result-wrong-run",
        "review_refs": ["nova-result-wrong-run", protocol["followup_result_id"]],
    }))
    with pytest.raises(audit.AuditError, match="native final review differs|native frozen discovery ownership"):
        audit._audit_document(package, "runs/wrong-reference-output")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_resigned_float_seed_in_protocol_spec_is_rejected(tmp_path: Path):
    package = _copy_run03(tmp_path)
    _resign_protocol(package, lambda protocol: protocol["main_spec"].update(seed=1729.0))
    with pytest.raises(audit.AuditError):
        audit._audit_document(package, "runs/float-seed-output")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
@pytest.mark.parametrize("mutation", ["wrong_run", "claimed_result", "bad_stage_hash", "review_mismatch"])
def test_resigned_sidecar_integrity_tampering_is_rejected(mutation: str, tmp_path: Path):
    package = _copy_run03(tmp_path)
    if mutation == "wrong_run":
        _rewrite_json(package, "native-finalization-evidence.json",
                      lambda sidecar: sidecar.update(run_id="different-run"))
    elif mutation == "claimed_result":
        _rewrite_json(package, "native-finalization-evidence.json",
                      lambda sidecar: sidecar.update(holdout_result_present=True))
    elif mutation == "bad_stage_hash":
        _rewrite_json(package, "native-finalization-evidence.json",
                      lambda sidecar: sidecar["finalization_state"].update(review_sha256="0" * 64))
    else:
        def alter_review(sidecar):
            state = sidecar["finalization_state"]
            state["review"]["review"]["reason"] += " altered"
            state["review_sha256"] = audit._native_stage_sha256(state["review"])

        _rewrite_json(package, "native-finalization-evidence.json", alter_review)
    expected = {
        "bad_stage_hash": "native finalization stage packet hash is invalid",
        "review_mismatch": "native final review differs from the stored discovery review",
    }.get(mutation)
    if expected:
        with pytest.raises(audit.AuditError, match=expected):
            audit._audit_document(package, "runs/sidecar-tamper-output")
    else:
        with pytest.raises(audit.AuditError):
            audit._audit_document(package, "runs/sidecar-tamper-output")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_resigned_holdout_attempt_event_is_rejected(tmp_path: Path):
    package = _copy_run03(tmp_path)
    events_path = package / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    holdout_id = json.loads((package / "native-finalization-evidence.json").read_text(
        encoding="utf-8"))["final_protocol"]["holdout_experiment_id"]
    _append_event(events, "holdout_running", "runner", holdout_id)
    events_path.write_bytes(b"".join(_canonical(event) for event in events))
    _refresh_manifest(package, "events.jsonl")
    with pytest.raises(audit.AuditError, match="holdout execution attempt"):
        audit._audit_document(package, "runs/holdout-event-output")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_resigned_review_concern_with_unresolved_result_is_rejected(tmp_path: Path):
    package = _copy_run03(tmp_path)

    def mutate(reviews):
        reviews[0]["concerns"][0]["evidence_refs"] = ["nova-result-not-in-this-run"]

    reviews_path = package / "reviews.json"
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    mutate(reviews)
    _write_json(reviews_path, reviews)
    _refresh_manifest(package, "reviews.json")
    with pytest.raises(audit.AuditError, match="unresolved Result reference"):
        audit._audit_document(package, "runs/review-reference-output")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_resigned_parent_review_cannot_cite_the_followup_result(tmp_path: Path):
    package = _copy_run03(tmp_path)
    reviews_path = package / "reviews.json"
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    reviews[0]["concerns"][0]["evidence_refs"] = [reviews[1]["result_id"]]
    _write_json(reviews_path, reviews)
    _refresh_manifest(package, "reviews.json")
    with pytest.raises(audit.AuditError, match="review concern does not reference its own Result"):
        audit._audit_document(package, "runs/cross-result-review-output")


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
@pytest.mark.parametrize("redacted", [False, True])
def test_clean_shaped_unicode_freeze_and_pi_response_are_accepted(redacted: bool, tmp_path: Path):
    package = _copy_run03(tmp_path)
    _resign_protocol(package, lambda protocol: protocol.update({"explanation": protocol["explanation"] + " Δ"}))
    _add_pi_response(package, redacted=redacted, clean=True)
    files, _ = audit._audit_document(package, "runs/clean-native-shaped-output")
    report = json.loads(files["audit.json"])
    preflight = report["native_finalization_preflight"]
    assert preflight["status"] == "frozen_discovery_evidence_verified"
    assert preflight["post_freeze_cli_failure_preserved"] is False
    assert preflight["final_pi_response_present"] is True
    assert preflight["final_pi_response_export_hash_verified"] is True
    assert preflight["final_pi_response_original_hash_verified"] is (not redacted)
    assert report["validation_scope"]["native_completion_verified"] is False
    assert report["validation_scope"]["native_cli_success_verified"] is False


@pytest.mark.skipif(os.name == "nt", reason="the existing science payload gate requires POSIX file mode bits")
def test_bad_exported_final_pi_response_hash_is_rejected(tmp_path: Path):
    package = _copy_run03(tmp_path)
    _add_pi_response(package, redacted=False, clean=False, bad_export_hash=True)
    with pytest.raises(audit.AuditError, match="final PI response hashes"):
        audit._audit_document(package, "runs/bad-final-pi-response-output")


def test_frozen_export_comparison_distinguishes_json_boolean_and_numeric_types():
    assert audit._same_json({"schema_version": True, "seed": 1729.0},
                            {"schema_version": 1, "seed": 1729}) is False
