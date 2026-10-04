from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from nova import holdout_bridge, live_bridge, method_evidence_export as export, registered_method_audit
from nova.contracts import ExperimentSpec, Result, Split, Template
from nova.experiments import executor, method_sensitivity
from nova.method_evidence import build_method_evidence_packet
from nova.storage import Storage


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _stub_body(request, _audit_output, parent, spec):
    return {
        "schema_version": 1,
        "artifact_type": "nova.method_evidence.v1",
        "request": dict(request),
        "parent": {"result_id": parent.result_id, "experiment_id": spec.experiment_id,
                   "spec_sha256": spec.sha256, "dataset_sha256": parent.dataset_sha256},
        "science_result": {
            "arms": {"opt_all": {"delta": 0.1}, "opt_paired": {"delta": 0.2},
                     "mbj_paired": {"delta": 0.3, "missingness_interval": None}},
            "paired_method_change": {"delta": 0.2}, "candidate_counts": {"shortlisted": 1},
            "candidate_counts_by_family": {"oxide": {"shortlisted": 1}},
            "subset_shift": {"oxide": 0}, "transitions": {"oxide": {"fail_to_pass": 1}},
            "candidates": [{"jid": "JVASP-SYNTH-1", "mbj_gap_ev": None,
                            "mbj_status": "unknown", "reason": "MBJ value unavailable",
                            "next_validation": "retain as unknown"}],
        },
    }


def _setup(tmp_path, monkeypatch, *, recorded_selection=False):
    protocol, protocol_sha = method_sensitivity._read_method_protocol()
    spec = ExperimentSpec(
        1, "E-method-parent", "H-method", protocol["dataset_sha256"], Split.DISCOVERY,
        Template.FAMILY_SCREEN, tuple(protocol["groups"]), "opt", tuple(protocol["gap_window_ev"]),
        protocol["ehull_max_ev_atom"], protocol["bootstrap_repeats"], protocol["seed"], 120,
    )
    root = tmp_path / "project"
    runs = root / "runs"
    runs.mkdir(parents=True)
    db_path = root / "live.sqlite"
    store = Storage(db_path).initialize()
    db_path.chmod(0o600)
    store.register_spec(spec)

    computation = executor._computation_spec_sha256(executor._minimal_science_spec(spec))
    summaries = {
        "oxide": {"n_total": 20, "n_observed": 18, "n_pass": 8, "coverage": 0.9,
                  "observed_rate": 8 / 18, "missing_lower": 0.4, "missing_upper": 0.5},
        "chalcogenide": {"n_total": 20, "n_observed": 17, "n_pass": 9, "coverage": 0.85,
                         "observed_rate": 9 / 17, "missing_lower": 0.45, "missing_upper": 0.6},
    }
    raw = {
        "schema_version": 1, "template": "family_screen", "split": "discovery",
        "execution_status": "success", "scientific_status": "inconclusive",
        "dataset_sha256": spec.dataset_sha256, "spec_sha256": computation,
        "groups_summary": summaries, "delta": 0.1,
        "resampling_interval": {"lower": -0.1, "upper": 0.3},
        "missingness_interval": {"lower": -0.2, "upper": 0.4},
        "quality_flags": {"synthetic": True}, "artifact_ids": [],
        "started_at": "2026-10-03T12:00:00+00:00", "finished_at": "2026-10-03T12:00:01+00:00",
        "elapsed_seconds": 1.0,
    }
    payload = (executor._canonical_json(executor._artifact_body(raw, spec, computation)) + "\n").encode()
    payload_sha = hashlib.sha256(payload).hexdigest()
    relative = Path("runs") / f"science-payload-{payload_sha}.json"
    (root / relative).write_bytes(payload)
    (root / relative).chmod(0o600)
    result_id = "nova-result-" + hashlib.sha256(executor._canonical_json({
        "experiment_id": spec.experiment_id, "spec_sha256": spec.sha256,
        "payload_sha256": payload_sha,
    }).encode()).hexdigest()
    result = Result(
        result_id, spec.experiment_id, spec.sha256, spec.dataset_sha256,
        "completed", raw["scientific_status"], raw["started_at"], raw["finished_at"], 1.0,
        executor._groups_summary(summaries), raw["delta"],
        executor._interval(raw["resampling_interval"], "resampling_interval"),
        executor._interval(raw["missingness_interval"], "missingness_interval"),
        ("science-quality-json-v1:" + executor._canonical_json(raw["quality_flags"]),),
        (f"nova-result-payload:{payload_sha}", f"nova-artifact-path:{relative.as_posix()}"), None,
    )
    store.save_result(result)

    run_id = "run-method-export"
    store.append_event(run_id, "run_created", actor="host", mode="live")
    store.append_event(run_id, "selection", actor="pi", mode="live", payload_ref=spec.experiment_id)
    store.append_event(run_id, "result", actor="runner", mode="live", payload_ref=result.result_id)
    audit_id = "NOVA-METHOD-" + hashlib.sha256(
        f"{run_id}:{result.result_id}:{spec.sha256}:{protocol_sha}".encode()
    ).hexdigest()[:24]
    request = {
        "schema_version": 1, "audit_id": audit_id, "run_id": run_id,
        "parent_result_id": result.result_id, "parent_experiment_id": spec.experiment_id,
        "parent_spec_sha256": spec.sha256, "dataset_sha256": spec.dataset_sha256,
        "protocol_sha256": protocol_sha,
    }
    with sqlite3.connect(db_path) as db:
        db.executescript("""
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
        db.execute("INSERT INTO registered_method_audits VALUES (?,?,?,?,?,?,?,?,?)", (
            audit_id, run_id, result.result_id, spec.experiment_id, spec.sha256,
            spec.dataset_sha256, protocol_sha, _canonical(request), "completed",
        ))
        cached = {"audit_id": audit_id, "result": {"execution_status": "success"},
                  "audit_rows": [{"private_sentinel": "do-not-export"}]}
        db.execute("INSERT INTO registered_method_audit_results VALUES (?,?)", (audit_id, _canonical(cached)))
        if recorded_selection:
            db.execute("""CREATE TABLE adaptive_followup_decisions (
                run_id TEXT PRIMARY KEY, parent_result_id TEXT NOT NULL, choice TEXT NOT NULL,
                reason TEXT NOT NULL, packet_json TEXT NOT NULL, selection_json TEXT NOT NULL
            )""")

    store.append_event(run_id, "method_audit_registered", actor="host", mode="live", payload_ref=audit_id)
    store.append_event(run_id, "method_audit_completed", actor="host", mode="live", payload_ref=audit_id)
    reason = "Paired MBJ coverage is useful — vérifier."
    if recorded_selection:
        packet = json.dumps({"parent_result_id": result.result_id, "scope": "shortlist"},
                            sort_keys=True, separators=(",", ":"))
        selected = json.dumps({"choice": "method_sensitivity", "reason": reason},
                              sort_keys=True, separators=(",", ":"))
        with sqlite3.connect(db_path) as db:
            db.execute("INSERT INTO adaptive_followup_decisions VALUES (?,?,?,?,?,?)",
                       (run_id, result.result_id, "method_sensitivity", reason, packet, selected))
        store.append_event(run_id, "adaptive_followup_selected", actor="pi", mode="live",
                           payload_ref=result.result_id)

    monkeypatch.setattr(live_bridge, "_read_context", lambda: (db_path, run_id))
    if os.name == "nt":
        # Windows cannot reproduce the Unix owner-only mode check; payload
        # hash, identity, and parent linkage remain exercised there.
        monkeypatch.setattr(holdout_bridge, "_secure_regular_file", lambda _path, _message: None)
    monkeypatch.setattr(export, "RUNS_ROOT", runs)
    monkeypatch.setattr(executor, "PROJECT_ROOT", root)
    from nova import method_evidence
    monkeypatch.setattr(method_evidence, "build_method_evidence", _stub_body)
    return {"runs": runs, "db": db_path, "run_id": run_id, "audit_id": audit_id,
            "request": request, "spec": spec, "result": result,
            "payload_sha": payload_sha, "expected_reason": reason}


def _assert_manifest_hashes(output):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for name, entry in manifest["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == entry["sha256"]
    return manifest


def test_export_is_read_only_run_scoped_and_never_executes_method(tmp_path, monkeypatch):
    fixture = _setup(tmp_path, monkeypatch)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("export must never execute or claim a method audit")

    monkeypatch.setattr(registered_method_audit, "execute_registered_method_audit", forbidden)
    monkeypatch.setattr(registered_method_audit, "_controller_factory", forbidden)
    before_db = fixture["db"].read_bytes()
    output = export.export_registered_method(fixture["audit_id"])

    assert fixture["db"].read_bytes() == before_db
    body = json.loads((output / "method-audit.json").read_text(encoding="utf-8"))
    assert "audit_rows" not in json.dumps(body) and "do-not-export" not in json.dumps(body)
    assert body["science_result"]["arms"]["mbj_paired"]["missingness_interval"] is None
    assert body["science_result"]["candidates"][0]["mbj_gap_ev"] is None
    packet = json.loads((output / "method-evidence.json").read_text(encoding="utf-8"))
    assert len(packet["references"]) == 11
    evidence_sha = hashlib.sha256((output / "method-audit.json").read_bytes()).hexdigest()
    for ref in packet["references"]:
        assert export._pointer(body, ref["json_pointer"]) is not None
        assert ref["evidence_sha256"] == evidence_sha
    parent_ref = packet["parent_result_ref"]
    results = json.loads((output / parent_ref["file"]).read_text(encoding="utf-8"))
    assert export._pointer(results, parent_ref["json_pointer"])["result_id"] == fixture["result"].result_id
    copied = output / "science-artifacts" / f"science-payload-{fixture['payload_sha']}.json"
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == fixture["payload_sha"]
    selection = json.loads((output / "adaptive-selection.json").read_text(encoding="utf-8"))
    assert selection["status"] == "not_recorded"
    assert not any(key in selection for key in ("choice", "reason", "model_cost", "elapsed_seconds"))
    manifest = _assert_manifest_hashes(output)
    assert manifest["files"]["results.json"]["count"] == 1
    assert manifest["method_audit"]["audit_id"] == fixture["audit_id"]


def test_unicode_adaptive_selection_is_preserved_and_hash_bound(tmp_path, monkeypatch):
    fixture = _setup(tmp_path, monkeypatch, recorded_selection=True)
    before_db = fixture["db"].read_bytes()
    output = export.export_registered_method(fixture["audit_id"])

    assert fixture["db"].read_bytes() == before_db
    selection = json.loads((output / "adaptive-selection.json").read_text(encoding="utf-8"))
    assert selection["status"] == "recorded"
    assert selection["reason"] == fixture["expected_reason"]
    assert selection["selection"]["reason"] == fixture["expected_reason"]
    packet = json.loads((output / "method-evidence.json").read_text(encoding="utf-8"))
    ref = packet["selection_ref"]
    assert hashlib.sha256((output / ref["file"]).read_bytes()).hexdigest() == ref["sha256"]
    _assert_manifest_hashes(output)


def test_incomplete_or_foreign_audit_is_rejected_before_creating_output(tmp_path, monkeypatch):
    fixture = _setup(tmp_path, monkeypatch)
    target = fixture["runs"] / "rejected-export"
    with sqlite3.connect(fixture["db"]) as db:
        db.execute("UPDATE registered_method_audits SET status='registered' WHERE audit_id=?",
                   (fixture["audit_id"],))
    with pytest.raises(ValueError, match="completed audit"):
        export.export_registered_method(fixture["audit_id"], target)
    assert not target.exists()
    with pytest.raises(ValueError, match="not registered for the active run"):
        export.export_registered_method("NOVA-METHOD-foreign", target)
    assert not target.exists()


def test_rejects_holdout_spec_before_selecting_its_malformed_result_json(tmp_path, monkeypatch):
    fixture = _setup(tmp_path, monkeypatch)
    holdout = replace(fixture["spec"], split=Split.HOLDOUT,
                      template=Template.HOLDOUT_VALIDATION, frozen_protocol_id="frozen-synthetic")
    request = dict(fixture["request"], parent_spec_sha256=holdout.sha256)
    with sqlite3.connect(fixture["db"]) as db:
        db.execute("UPDATE specs SET spec_json=?,spec_sha256=? WHERE experiment_id=?",
                   (holdout.to_json(), holdout.sha256, holdout.experiment_id))
        db.execute("UPDATE results SET result_json='not-json' WHERE result_id=?",
                   (fixture["result"].result_id,))
        db.execute("UPDATE registered_method_audits SET parent_spec_sha256=?,request_json=? WHERE audit_id=?",
                   (holdout.sha256, _canonical(request), fixture["audit_id"]))
    with pytest.raises(ValueError, match="not its discovery family Spec"):
        export._snapshot(fixture["db"], fixture["run_id"], fixture["audit_id"])
