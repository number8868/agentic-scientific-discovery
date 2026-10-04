from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

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


def test_native_export_uses_persisted_state_and_sanitizes_trusted_runtime_files(tmp_path, monkeypatch):
    db, store, _spec, result = _seed(tmp_path, "native-run", monkeypatch, artifact=True)
    from nova.adaptive_policy import propose_followups

    packet = propose_followups(result, remaining_seconds=600)
    packet["selection"] = None
    review = {"parent_result_id": result.result_id, "concern": "Coverage review",
              "evidence_refs": [f"result:{result.result_id}#groups_summary"]}
    selection = {"choice": "stop", "reason": "Stop after reviewing discovery evidence",
                 "scope": "discovery_only", "evidence_refs": [f"result:{result.result_id}"]}
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE native_adaptive_state (
                run_id TEXT PRIMARY KEY, parent_result_id TEXT NOT NULL, packet_json TEXT NOT NULL,
                review_json TEXT, selection_json TEXT, selected_id TEXT, selected_kind TEXT, status TEXT NOT NULL
            );
            CREATE TABLE native_adaptive_supervisor_results (
                run_id TEXT PRIMARY KEY, parent_result_id TEXT NOT NULL,
                response_text TEXT NOT NULL, response_sha256 TEXT NOT NULL
            );
        """)
        conn.execute("INSERT INTO native_adaptive_state VALUES (?,?,?,?,?,?,?,?)", (
            "native-run", result.result_id, json.dumps(packet), json.dumps(review),
            json.dumps(selection), None, None, "committed"))
        response = "The PI stopped after considering the registered evidence."
        conn.execute("INSERT INTO native_adaptive_supervisor_results VALUES (?,?,?,?)", (
            "native-run", result.result_id, response, hashlib.sha256(response.encode()).hexdigest()))
    store.append_event("native-run", "native_adaptive_options_registered", actor="planner", mode=Mode.LIVE,
                       payload_ref=result.result_id)
    store.append_event("native-run", "native_adaptive_review_submitted", actor="skeptic", mode=Mode.LIVE,
                       payload_ref=result.result_id)
    store.append_event("native-run", "native_adaptive_choice_committed", actor="pi", mode=Mode.LIVE,
                       payload_ref=result.result_id)
    store.append_event("native-run", "native_adaptive_supervisor_returned", actor="host", mode=Mode.LIVE,
                       payload_ref=result.result_id)

    run_dir = db.parent
    manifest = {
        "schema_version": 1, "run_id": "native-run", "omnigent_version": "0.16.0",
        "model_override": "gpt-6-luna",
        "effective_role_models": {role: "gpt-6-luna" for role in ("pi", "planner", "skeptic", "runner")},
        "native_tools_disabled": True, "web_search_disabled": True, "skills": "none",
        "config_overrides": ["features.code_mode_host=true", "features.code_mode=false"],
        "host_binary_env": "CODEX_CODE_MODE_HOST_PATH",
    }
    manifest_path = run_dir / "native-runtime-manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n")
    manifest_path.chmod(0o600)
    trace_records = [
        {"event": "native_adaptive_trace_started", "run_id": "native-run", "requested_model": "gpt-6-luna"},
        {"event": "tool_complete", "actor": "omnigent-tool-dispatch", "tool": "commit_adaptive_choice",
         "status": "success", "result_text": "sk-abcdefghijklmnopqrstuv"},
    ]
    trace_path = run_dir / "native-model-audit.jsonl"
    trace_path.write_text("".join(json.dumps(record) + "\n" for record in trace_records))
    trace_path.chmod(0o600)

    output = exporter.export_adaptive_evidence(db, "native-run", tmp_path / "runs" / "native-export")
    evidence = json.loads((output / "adaptive_evidence.json").read_text())
    assert evidence["packet_source"] == "recorded_native_packet"
    assert evidence["adaptive_packet"] == packet
    assert evidence["adaptive_review"] == review
    assert evidence["adaptive_selection"] == selection
    assert evidence["native_supervisor_response"]["response_text"] == response
    assert evidence["runtime"]["selector_kind"] == "native_omnigent_yaml"
    assert evidence["runtime"]["requested_model"] == "operator_reported_not_attested"
    assert evidence["runtime"]["effective_role_models_reported_not_attested"]["pi"] == "gpt-6-luna"
    assert evidence["provider_attestation"] is None
    assert evidence["native_runtime_verification"]["guardrail_verification"] == "requested_unverified_not_effective"
    assert evidence["native_runtime_verification"]["model_tool_trace"] == "unavailable"
    exported_manifest = json.loads((output / "native-runtime-manifest.json").read_text())
    assert (output / "native-runtime-manifest.json").read_bytes() == manifest_path.read_bytes()
    assert exported_manifest["model_override"] == "gpt-6-luna"
    exported_trace = (output / "native-model-audit.jsonl").read_text()
    assert "sk-abcdefghijklmnopqrstuv" not in exported_trace
    assert "[redacted]" in exported_trace
    inventory = json.loads((output / "hashes.json").read_text())
    assert {"native-runtime-manifest.json", "native-model-audit.jsonl"} <= set(inventory)
    for relative, digest in inventory.items():
        assert hashlib.sha256((output / relative).read_bytes()).hexdigest() == digest
    with pytest.raises(ValueError, match="output directory must be new or empty"):
        exporter.export_adaptive_evidence(db, "native-run", output)
    assert json.loads((output / "hashes.json").read_text()) == inventory


def test_failed_native_runner_export_preserves_failure_without_supervisor_completion(tmp_path, monkeypatch):
    db, store, _parent_spec, parent_result = _seed(
        tmp_path, "native-failed", monkeypatch, artifact=True)
    threshold = ExperimentSpec(
        1, "NOVA-native-threshold", "H1", "d" * 64, Split.DISCOVERY,
        Template.THRESHOLD_SENSITIVITY, ("oxide", "chalcogenide"), "opt",
        (1.1, 1.8), 0.05, 2000, 1729, 120, parent_result.result_id, parent_result.result_id,
    )
    threshold_payload = b'{"template":"threshold_sensitivity","split":"discovery","points":[]}\n'
    digest = hashlib.sha256(threshold_payload).hexdigest()
    (tmp_path / "runs" / f"science-payload-{digest}.json").write_bytes(threshold_payload)
    threshold_result = Result(
        "result-native-threshold", threshold.experiment_id, threshold.sha256,
        threshold.dataset_sha256, "completed", "inconclusive", "start", "end", 30.0,
        artifact_ids=(f"nova-result-payload:{digest}",
                      f"nova-artifact-path:runs/science-payload-{digest}.json"),
    )
    store.register_spec(threshold)
    store.save_result(threshold_result)
    packet = {"packet_type": "adaptive_discovery_followups", "parent_result_id": parent_result.result_id,
              "selection": None}
    review = {"parent_result_id": parent_result.result_id, "concern": "sparse passes"}
    selection = {"choice": "threshold_sensitivity", "selected_id": threshold.experiment_id,
                 "selected_kind": "experiment_id", "scope": "discovery_only"}
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE native_adaptive_state (
            run_id TEXT PRIMARY KEY, parent_result_id TEXT NOT NULL, packet_json TEXT NOT NULL,
            review_json TEXT, selection_json TEXT, selected_id TEXT, selected_kind TEXT, status TEXT NOT NULL
        )""")
        conn.execute("INSERT INTO native_adaptive_state VALUES (?,?,?,?,?,?,?,?)", (
            "native-failed", parent_result.result_id, json.dumps(packet), json.dumps(review),
            json.dumps(selection), threshold.experiment_id, "experiment_id", "failed"))
    events = (
        ("native_adaptive_orchestration_started", "host", None),
        ("native_adaptive_options_registered", "planner", parent_result.result_id),
        ("native_adaptive_review_submitted", "skeptic", parent_result.result_id),
        ("second_selection", "pi", threshold.experiment_id),
        ("native_adaptive_choice_committed", "pi", threshold.experiment_id),
        ("native_adaptive_runner_started", "runner", threshold.experiment_id),
        ("result", "runner", threshold_result.result_id),
        ("native_adaptive_runner_failed", "host", threshold.experiment_id),
        ("native_adaptive_orchestration_failed", "host", None),
    )
    for event_type, actor, reference in events:
        store.append_event("native-failed", event_type, actor=actor, mode=Mode.LIVE,
                           payload_ref=reference)
    run_dir = db.parent
    manifest = {"schema_version": 1, "run_id": "native-failed", "model_override": "gpt-6-luna",
                "effective_role_models": {role: "gpt-6-luna" for role in ("pi", "planner", "skeptic", "runner")},
                "native_tools_disabled": True, "web_search_disabled": True, "skills": "none",
                "config_overrides": ["features.code_mode_host=true", "features.code_mode=false"]}
    manifest_path = run_dir / "native-runtime-manifest.json"
    manifest_path.write_text(json.dumps(manifest) + "\n")
    manifest_path.chmod(0o600)
    trace_path = run_dir / "native-model-audit.jsonl"
    trace_path.write_text(json.dumps({"event": "native_adaptive_trace_started", "run_id": "native-failed"}) + "\n")
    trace_path.write_text(trace_path.read_text() + json.dumps({"event": "function_complete", "actor": "runner",
                                                               "tool": "execute_selected_adaptive"}) + "\n")
    trace_path.chmod(0o600)
    output = exporter.export_adaptive_evidence(
        db, "native-failed", tmp_path / "runs" / "native-failed-export",
        failure_detail="science payload does not match the registered Result Spec",
    )
    evidence = json.loads((output / "adaptive_evidence.json").read_text())
    assert evidence["packet_source"] == "recorded_native_packet"
    assert len(evidence["registered_results"]) == 2
    assert len(json.loads((output / "science-artifacts.json").read_text())["results"]) == 2
    assert evidence["native_runtime_verification"]["native_workflow_status"] == "failed"
    assert evidence["native_runtime_verification"]["supervisor_response_persisted"] is False
    assert evidence["native_supervisor_response"] is None
    assert evidence["native_runtime_verification"]["guardrail_verification"] == "requested_unverified_not_effective"
    assert evidence["native_runtime_verification"]["model_tool_trace"] == "unavailable"
    assert evidence["native_runtime_verification"]["model_request_or_completion_observed"] is False
    assert evidence["native_runtime_verification"]["native_model_audit_scope"] == "host_function_events_only"
    assert evidence["native_runtime_verification"]["failure_detail"] == (
        "science payload does not match the registered Result Spec")
    assert evidence["native_runtime_verification"]["failure_detail_source"] == "operator_supplied_not_persisted"
    assert evidence["native_runtime_verification"]["runner_feedback_validation"] == "failed"
    assert evidence["native_runtime_verification"]["run_owned_results_persisted"] == 2
    assert (output / "native-runtime-manifest.json").read_bytes() == manifest_path.read_bytes()
    assert evidence["provider_attestation"] is None


def test_native_export_labels_host_validation_recovery_and_preserves_prior_failure(tmp_path, monkeypatch):
    db, store, _spec, parent_result = _seed(
        tmp_path, "native-recovered", monkeypatch, artifact=True)
    selected_id = "NOVA-threshold"
    packet = {"packet_type": "adaptive_discovery_followups",
              "parent_result_id": parent_result.result_id, "selection": None}
    review = {"parent_result_id": parent_result.result_id, "concern": "Snapshot limitation"}
    selection = {"choice": "threshold_sensitivity", "selected_id": selected_id,
                 "selected_kind": "experiment_id", "scope": "discovery_only"}
    response = "The Runner returned the committed discovery Result."
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE native_adaptive_state (
                run_id TEXT PRIMARY KEY, parent_result_id TEXT NOT NULL, packet_json TEXT NOT NULL,
                review_json TEXT, selection_json TEXT, selected_id TEXT, selected_kind TEXT, status TEXT NOT NULL
            );
            CREATE TABLE native_adaptive_supervisor_results (
                run_id TEXT PRIMARY KEY, parent_result_id TEXT NOT NULL,
                response_text TEXT NOT NULL, response_sha256 TEXT NOT NULL
            );
        """)
        conn.execute("INSERT INTO native_adaptive_state VALUES (?,?,?,?,?,?,?,?)", (
            "native-recovered", parent_result.result_id, json.dumps(packet), json.dumps(review),
            json.dumps(selection), selected_id, "experiment_id", "completed"))
        conn.execute("INSERT INTO native_adaptive_supervisor_results VALUES (?,?,?,?)", (
            "native-recovered", parent_result.result_id, response,
            hashlib.sha256(response.encode()).hexdigest()))
    store.append_event("native-recovered", "native_adaptive_runner_failed", actor="host", mode=Mode.LIVE,
                       payload_ref=selected_id)
    store.append_event("native-recovered", "native_adaptive_orchestration_failed", actor="host", mode=Mode.LIVE)
    store.append_event("native-recovered", "native_adaptive_supervisor_returned", actor="host", mode=Mode.LIVE,
                       payload_ref=parent_result.result_id)
    store.append_event("native-recovered", "native_adaptive_host_validation_recovered", actor="host",
                       mode=Mode.LIVE, payload_ref=selected_id)

    trace = [{"event": "tool_result_decoded_retrospectively", "actor": "host-transport-verifier"}]
    trace.extend({"event": "executor_guard_installed", "pid": pid} for pid in range(100, 104))
    trace.extend({"event": "turn_complete", "pid": pid} for pid in range(5))
    trace_path = db.parent / "native-model-audit.jsonl"
    trace_path.write_text("".join(json.dumps(item) + "\n" for item in trace), encoding="utf-8")
    trace_path.chmod(0o600)

    output = exporter.export_adaptive_evidence(
        db, "native-recovered", tmp_path / "runs" / "native-recovered-export")
    evidence = json.loads((output / "adaptive_evidence.json").read_text())
    verification = evidence["native_runtime_verification"]
    assert verification["native_workflow_status"] == "completed_with_host_validation_recovery"
    assert verification["supervisor_response_persisted"] is True
    assert verification["prior_failure_observed"] is True
    assert verification["runner_feedback_validation"] == "retrospective_transport_witness_recorded"
    assert verification["retrospective_transport_witness_observed"] is True
    assert verification["observed_executor_pid_count"] == 4
    assert verification["observed_turn_complete_count"] == 5
    assert any(item["event_type"] == "native_adaptive_orchestration_failed"
               for item in evidence["run_events"])
    assert verification["guardrail_verification"] == "requested_unverified_not_effective"
    assert evidence["provider_attestation"] is None
