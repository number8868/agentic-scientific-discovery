from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from nova.contracts import ExperimentSpec, Mode, Result, Split, Template
from nova.storage import Storage
from scripts import export_adaptive_evidence as exporter


def _seed(tmp_path: Path, run_id: str, monkeypatch, *, artifact: bool = False):
    from nova.experiments import executor

    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    monkeypatch.setattr(exporter, "ROOT", tmp_path)
    monkeypatch.setattr(executor, "PROJECT_ROOT", tmp_path)
    db = runs / "run.sqlite"
    store = Storage(db).initialize()
    spec = ExperimentSpec(
        1, "NOVA-0123456789abcdef", "H1", "d" * 64, Split.DISCOVERY, Template.FAMILY_SCREEN,
        ("oxide", "chalcogenide"), "opt", (1.1, 1.8), 0.05, 2000, 1729, 120,
    )
    store.register_spec(spec)
    artifact_ids = ()
    if artifact:
        payload = b'{"template":"family_screen","execution_status":"success"}\n'
        digest = hashlib.sha256(payload).hexdigest()
        source = runs / f"science-payload-{digest}.json"
        source.write_bytes(payload)
        artifact_ids = (f"nova-result-payload:{digest}",
                        f"nova-artifact-path:runs/{source.name}")
    result = Result(
        "result-parent", spec.experiment_id, spec.sha256, spec.dataset_sha256,
        "completed", "inconclusive", "start", "end", 30.0, artifact_ids=artifact_ids,
    )
    store.save_result(result)
    store.append_event(run_id, "selection", actor="pi", mode=Mode.LIVE,
                       payload_ref=spec.experiment_id)
    store.append_event(run_id, "result", actor="runner", mode=Mode.LIVE,
                       payload_ref=result.result_id)
    return db, store, spec, result


def test_successful_threshold_export_carries_both_science_payloads_and_run_scoped_audits(tmp_path, monkeypatch):
    db, store, parent_spec, parent_result = _seed(
        tmp_path, "threshold-run", monkeypatch, artifact=True)
    threshold = ExperimentSpec(
        1, "NOVA-threshold", "H1", "d" * 64, Split.DISCOVERY,
        Template.THRESHOLD_SENSITIVITY, ("oxide", "chalcogenide"), "opt",
        (1.1, 1.8), 0.05, 2000, 1729, 120, parent_result.result_id, parent_result.result_id,
    )
    threshold_bytes = b'{"template":"threshold_sensitivity","grid":[0.04,0.05,0.06]}\n'
    digest = hashlib.sha256(threshold_bytes).hexdigest()
    (tmp_path / "runs" / f"science-payload-{digest}.json").write_bytes(threshold_bytes)
    threshold_result = Result(
        "result-threshold", threshold.experiment_id, threshold.sha256, threshold.dataset_sha256,
        "completed", "inconclusive", "start", "end", 30.0,
        artifact_ids=(f"nova-result-payload:{digest}",
                      f"nova-artifact-path:runs/science-payload-{digest}.json"),
    )
    store.register_spec(threshold)
    store.save_result(threshold_result)
    store.append_event("threshold-run", "second_selection", actor="pi", mode=Mode.LIVE,
                       payload_ref=threshold.experiment_id)
    store.append_event("threshold-run", "result", actor="runner", mode=Mode.LIVE,
                       payload_ref=threshold_result.result_id)

    method_run = "method-run"
    store.append_event(method_run, "selection", actor="pi", mode=Mode.LIVE,
                       payload_ref=parent_spec.experiment_id)
    store.append_event(method_run, "result", actor="runner", mode=Mode.LIVE,
                       payload_ref=parent_result.result_id)
    store.append_event(method_run, "method_audit_registered", actor="host", mode=Mode.LIVE,
                       payload_ref="audit-current")
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE registered_method_audits (
                audit_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, parent_result_id TEXT NOT NULL,
                parent_experiment_id TEXT NOT NULL, parent_spec_sha256 TEXT NOT NULL,
                dataset_sha256 TEXT NOT NULL, protocol_sha256 TEXT NOT NULL,
                request_json TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE TABLE registered_method_audit_results (
                audit_id TEXT PRIMARY KEY, result_json TEXT NOT NULL
            );
        """)
        for audit_id, owner in (("audit-current", method_run), ("audit-foreign", "other-run")):
            request = json.dumps({"audit_id": audit_id, "run_id": owner})
            conn.execute("INSERT INTO registered_method_audits VALUES (?,?,?,?,?,?,?,?,?)", (
                audit_id, owner, parent_result.result_id, parent_spec.experiment_id,
                parent_spec.sha256, parent_spec.dataset_sha256, "e" * 64, request, "completed"))
            conn.execute("INSERT INTO registered_method_audit_results VALUES (?,?)", (
                audit_id, json.dumps({"execution_status": "success", "owner": owner})))

    threshold_out = exporter.export_adaptive_evidence(
        db, "threshold-run", tmp_path / "runs" / "threshold-export")
    threshold_evidence = json.loads((threshold_out / "adaptive_evidence.json").read_text())
    assert len(threshold_evidence["registered_specs"]) == 2
    assert len(threshold_evidence["registered_results"]) == 2
    assert len(threshold_evidence["run_events"]) == 4
    science = json.loads((threshold_out / "science-artifacts.json").read_text())
    assert {item["result_id"] for item in science["results"]} == {"result-parent", "result-threshold"}
    assert len(science["artifacts"]) == 2
    manifest = json.loads((threshold_out / "manifest.json").read_text())
    assert manifest["files"]["events.jsonl"]["count"] == 4
    assert manifest["files"]["specs.json"]["count"] == 2
    assert manifest["files"]["results.json"]["count"] == 2
    assert manifest["files"]["science-artifacts.json"]["count"] == 2
    inventory = json.loads((threshold_out / "hashes.json").read_text())
    for relative, digest_value in inventory.items():
        assert hashlib.sha256((threshold_out / relative).read_bytes()).hexdigest() == digest_value

    method_out = exporter.export_adaptive_evidence(
        db, method_run, tmp_path / "runs" / "method-export")
    method_evidence = json.loads((method_out / "adaptive_evidence.json").read_text())
    assert [row["audit_id"] for row in method_evidence["method_audit_records"]["requests"]] == ["audit-current"]
    assert method_evidence["method_audit_records"]["results"][0]["result"]["owner"] == method_run
    assert "other-run" not in (method_out / "adaptive_evidence.json").read_text()


def test_failed_export_labels_reconstructed_packet_and_unattested_model(tmp_path, monkeypatch):
    db, store, _spec, _result = _seed(tmp_path, "failed-run", monkeypatch, artifact=True)
    store.append_event("failed-run", "adaptive_followup_decision_started", actor="host", mode=Mode.LIVE,
                       payload_ref="result-parent")
    store.append_event("failed-run", "adaptive_followup_failed", actor="host", mode=Mode.LIVE,
                       payload_ref="result-parent")
    output = exporter.export_adaptive_evidence(
        db, "failed-run", tmp_path / "runs" / "failed-export", model="gpt-6-luna")
    evidence = json.loads((output / "adaptive_evidence.json").read_text())
    assert evidence["packet_source"] == "reconstructed_for_inspection_not_recorded_model_input"
    assert evidence["adaptive_selection"] is None
    assert evidence["runtime"]["requested_model"] == "operator_reported_not_attested"
    assert evidence["runtime"]["operator_reported_model"] == "gpt-6-luna"
    assert evidence["provider_attestation"] is None
    assert len(evidence["run_events"]) == 4
