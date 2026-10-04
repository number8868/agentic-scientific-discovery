#!/usr/bin/env python3
"""Export portable, sanitized evidence for a live adaptive discovery run."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import stat
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_SECRETISH = re.compile(r"(?i)\b(?:bearer\s+|sk-|rk-|gh[pousr]_|xox[baprs]-)[A-Za-z0-9._-]{12,}")


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRETISH.sub("[redacted]", value).replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    return value


def _dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_sanitize(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


def _sanitize_native_export(directory: Path) -> None:
    for path in directory.iterdir():
        if path.name in {"hashes.json", "manifest.json"} or not path.is_file():
            continue
        if path.suffix == ".jsonl":
            values = [json.loads(line) for line in path.read_text().splitlines() if line]
            path.write_text("".join(json.dumps(_sanitize(item), sort_keys=True, separators=(",", ":")) + "\n"
                                     for item in values))
        elif path.suffix == ".json":
            _dump(path, json.loads(path.read_text()))
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for name in manifest["files"]:
        data = (directory / name).read_bytes()
        manifest["files"][name]["sha256"] = hashlib.sha256(data).hexdigest()
    _dump(manifest_path, manifest)


def _update_manifests_and_hashes(directory: Path) -> None:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for path in sorted(item for item in directory.rglob("*") if item.is_file()
                       and item.name not in {"manifest.json", "hashes.json"}):
        relative = path.relative_to(directory).as_posix()
        data = path.read_bytes()
        if _SECRETISH.search(data.decode("utf-8", errors="ignore")):
            raise ValueError(f"credential-like pattern found in exported artifact: {relative}")
        entry = manifest["files"].get(relative, {})
        if relative == "events.jsonl":
            count = len([line for line in data.splitlines() if line.strip()])
        elif relative.endswith(".jsonl"):
            count = len([line for line in data.splitlines() if line.strip()])
        elif relative in {"specs.json", "results.json", "reviews.json"}:
            count = len(json.loads(data))
        elif relative == "science-artifacts.json":
            count = len(json.loads(data).get("results", []))
        else:
            count = entry.get("count", 1)
        manifest["files"][relative] = {"sha256": hashlib.sha256(data).hexdigest(), "count": count}
    _dump(manifest_path, manifest)
    files = sorted(item for item in directory.rglob("*") if item.is_file() and item.name != "hashes.json")
    _dump(directory / "hashes.json", {
        item.relative_to(directory).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in files
    })


def _owned_parent(store, run_id: str, events):
    from nova.contracts import Split, Template

    result_refs = {event.payload_ref for event in events
                   if event.actor == "runner" and event.event_type == "result" and event.payload_ref}
    selected_specs = {event.payload_ref for event in events
                      if event.actor == "pi" and event.event_type in {"selection", "second_selection"}
                      and event.payload_ref}
    candidates = []
    for result in store.list_results():
        if result.result_id not in result_refs or result.execution_status != "completed" or result.error is not None:
            continue
        spec = store.get_spec(result.experiment_id)
        if (spec is not None and spec.experiment_id in selected_specs and
                spec.template is Template.FAMILY_SCREEN and spec.split is Split.DISCOVERY and
                result.spec_sha256 == spec.sha256 and result.dataset_sha256 == spec.dataset_sha256):
            candidates.append((result, spec))
    if len(candidates) != 1:
        raise ValueError("export requires exactly one run-owned completed discovery family_screen parent")
    return candidates[0]


def _method_records(db: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    table_names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"registered_method_audits", "registered_method_audit_results"} <= table_names:
        return {"requests": [], "results": []}
    requests = [dict(row) for row in db.execute(
        "SELECT * FROM registered_method_audits WHERE run_id=? ORDER BY audit_id", (run_id,))]
    audit_ids = [row["audit_id"] for row in requests]
    results = []
    if audit_ids:
        placeholders = ",".join("?" for _ in audit_ids)
        results = [dict(row) for row in db.execute(
            f"SELECT r.* FROM registered_method_audit_results r JOIN registered_method_audits a "
            f"ON a.audit_id=r.audit_id WHERE a.run_id=? AND r.audit_id IN ({placeholders}) ORDER BY r.audit_id",
            (run_id, *audit_ids))]
        for record in results:
            record["result"] = json.loads(record.pop("result_json"))
    for request in requests:
        request["request"] = json.loads(request.pop("request_json"))
    return {"requests": requests, "results": results}


def _read_native_files(run_dir: Path, run_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    """Read only the two fixed native runtime evidence files from the run directory."""
    runs_root = (ROOT / "runs").resolve()
    resolved_dir = run_dir.resolve()
    if not resolved_dir.is_relative_to(runs_root):
        raise ValueError("native evidence directory must be inside runs/")
    manifest = None
    manifest_path = resolved_dir / "native-runtime-manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest_info = manifest_path.lstat()
        if (manifest_path.is_symlink() or not manifest_path.is_file() or
                not stat.S_ISREG(manifest_info.st_mode) or manifest_info.st_mode & 0o077):
            raise ValueError("native runtime manifest must be a regular run-owned file")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("native runtime manifest must be a JSON object")
        if manifest.get("run_id") != run_id:
            raise ValueError("native runtime manifest belongs to a different run")
    trace = None
    trace_path = resolved_dir / "native-model-audit.jsonl"
    if trace_path.exists() or trace_path.is_symlink():
        trace_info = trace_path.lstat()
        if (trace_path.is_symlink() or not trace_path.is_file() or not stat.S_ISREG(trace_info.st_mode)
                or trace_info.st_mode & 0o077):
            raise ValueError("native model audit must be a regular run-owned file")
        trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line]
        if not all(isinstance(record, dict) for record in trace):
            raise ValueError("native model audit lines must be JSON objects")
        headers = [record for record in trace if record.get("event") == "native_adaptive_trace_started"]
        if headers and (len(headers) != 1 or headers[0].get("run_id") != run_id):
            raise ValueError("native model audit belongs to a different run")
    return manifest, trace


def _native_state(db: sqlite3.Connection, run_id: str, parent_result_id: str) -> dict[str, Any] | None:
    tables = {record[0] for record in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "native_adaptive_state" not in tables:
        return None
    row = db.execute(
        "SELECT parent_result_id,packet_json,review_json,selection_json,selected_id,selected_kind,status "
        "FROM native_adaptive_state WHERE run_id=?", (run_id,),
    ).fetchone()
    if row is None:
        return None
    if row["parent_result_id"] != parent_result_id:
        raise ValueError("native adaptive state belongs to a different parent result")
    state = {
        "parent_result_id": row["parent_result_id"],
        "packet": json.loads(row["packet_json"]) if row["packet_json"] else None,
        "review": json.loads(row["review_json"]) if row["review_json"] else None,
        "selection": json.loads(row["selection_json"]) if row["selection_json"] else None,
        "selected_id": row["selected_id"],
        "selected_kind": row["selected_kind"],
        "status": row["status"],
        "supervisor_response": None,
    }
    if "native_adaptive_supervisor_results" in tables:
        response = db.execute(
            "SELECT parent_result_id,response_text,response_sha256 FROM native_adaptive_supervisor_results "
            "WHERE run_id=?", (run_id,),
        ).fetchone()
        if response is not None:
            if response["parent_result_id"] != parent_result_id:
                raise ValueError("native supervisor response belongs to a different parent result")
            state["supervisor_response"] = {
                "parent_result_id": response["parent_result_id"],
                "response_text": response["response_text"],
                "response_sha256": response["response_sha256"],
            }
    return state


def _native_runtime(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if manifest is None:
        reported = {}
    else:
        reported = manifest
    return {
        "selector_kind": "native_omnigent_yaml",
        "requested_model": "operator_reported_not_attested",
        "operator_reported_model_override": reported.get("model_override", "not_recorded"),
        "effective_role_models_reported_not_attested": reported.get("effective_role_models", {}),
        "omnigent_version": reported.get("omnigent_version", "not_recorded"),
        "requested_config_not_attested": {
            "native_tools_disabled": reported.get("native_tools_disabled"),
            "web_search_disabled": reported.get("web_search_disabled"),
            "skills": reported.get("skills"),
            "config_overrides": reported.get("config_overrides"),
            "host_binary_env": reported.get("host_binary_env"),
        },
        "runtime_manifest_source": "native-runtime-manifest.json" if manifest is not None else None,
        "provider_attestation": None,
    }


def export_adaptive_evidence(database: Path, run_id: str, output: Path,
                             *, remaining_seconds: float = 600,
                             model: str = "gpt-6-luna",
                             failure_detail: str | None = None) -> Path:
    from nova.adaptive_policy import propose_followups
    from nova.evidence import export_run
    from nova.experiments.executor import export_science_artifacts
    from nova.storage import Storage

    database, output = Path(database).resolve(), Path(output)
    if not database.is_relative_to((ROOT / "runs").resolve()):
        raise ValueError("database must be under runs/")
    store = Storage(database).initialize()
    events = store.list_events(run_id)
    if not events or any(event.mode.value != "live" for event in events):
        raise ValueError("adaptive evidence requires a live run")
    parent, _parent_spec = _owned_parent(store, run_id, events)
    with sqlite3.connect(str(database)) as db:
        db.row_factory = sqlite3.Row
        has_decisions = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='adaptive_followup_decisions'").fetchone()
        row = (db.execute("SELECT * FROM adaptive_followup_decisions WHERE run_id=?", (run_id,)).fetchone()
               if has_decisions else None)
        method_output = _method_records(db, run_id)
        native_state = _native_state(db, run_id, parent.result_id)
    native_manifest, native_trace = _read_native_files(database.parent, run_id)
    native_events = any(event.event_type.startswith("native_adaptive_") for event in events)
    native_mode = native_state is not None or native_events or native_manifest is not None or native_trace is not None
    if row and native_state is not None:
        raise ValueError("run contains both classic and native adaptive state")
    if row:
        packet = json.loads(row["packet_json"])
        selection = {"choice": row["choice"], "reason": row["reason"],
                     "selection": json.loads(row["selection_json"])}
        packet_source = "recorded_decision_packet"
        runtime = packet.get("selection_provenance", {})
        provider_attestation = None
        review = None
        supervisor_response = None
    elif native_mode:
        packet = native_state["packet"] if native_state else None
        review = native_state["review"] if native_state else None
        selection = native_state["selection"] if native_state else None
        supervisor_response = native_state["supervisor_response"] if native_state else None
        packet_source = "recorded_native_packet" if packet is not None else "native_packet_not_persisted"
        runtime = _native_runtime(native_manifest)
        provider_attestation = None
    else:
        packet = propose_followups(parent, remaining_seconds=remaining_seconds,
                                   method_audit_available=True)
        from scripts.run_adaptive_followup import _threshold_commit_available
        if not _threshold_commit_available(database, run_id):
            for option in packet["candidate_tests"]:
                if option["choice"] == "threshold_sensitivity":
                    option["feasibility"] = False
                    option["reason"] += " Legacy host plan required to commit this template is unavailable."
                    option["learning_reasons"].append(
                        "Legacy host plan required to commit this template is unavailable.")
            packet["allowed_choices"] = [item["choice"] for item in packet["candidate_tests"]]
        packet["selection_provenance"] = {
            "selector_kind": "omnigent_codex",
            "requested_model": "operator_reported_not_attested",
            "operator_reported_model": model,
            "harness": "omnigent.inner.codex_executor.CodexExecutor",
            "omnigent_version": None,
            "tool_config": {"web_search": False, "native_tools": False, "skills": "none",
                             "max_tokens": 500, "reasoning_effort": "low"},
        }
        packet_source = "reconstructed_for_inspection_not_recorded_model_input"
        runtime = packet["selection_provenance"]
        try:
            runtime["omnigent_version"] = version("omnigent")
        except PackageNotFoundError:
            runtime["omnigent_version"] = "not_installed"
        selection = None
        provider_attestation = None
        review = None
        supervisor_response = None

    native_verification = None
    if native_mode:
        trace_events = {item.get("event") for item in (native_trace or [])}
        model_events_observed = bool(trace_events.intersection({"tool_request", "turn_complete"}))
        persisted_failed = (native_state is not None and native_state["status"] == "failed") or any(
            event.event_type in {"native_adaptive_runner_failed", "native_adaptive_orchestration_failed"}
            for event in events)
        native_status = (native_state["status"] if native_state is not None else
                         "failed_without_state" if persisted_failed else "state_not_persisted")
        native_verification = {
            "native_workflow_status": native_status,
            "guardrail_verification": "requested_unverified_not_effective",
            "guardrail_enforcement": "unverified",
            "model_tool_trace": "present_unverified" if model_events_observed else "unavailable",
            "model_request_or_completion_observed": model_events_observed,
            "native_model_audit_scope": ("host_function_events_only" if native_trace and not model_events_observed
                                         else "unverified_or_unavailable"),
            "supervisor_response_persisted": supervisor_response is not None,
            "runner_feedback_validation": "failed" if persisted_failed and failure_detail else "not_recorded",
            "failure_detail": failure_detail if persisted_failed else None,
            "failure_detail_source": "operator_supplied_not_persisted" if persisted_failed and failure_detail else None,
        }

    native = export_run(database, run_id, output)
    _sanitize_native_export(native)
    if native_manifest is not None:
        source_manifest = database.parent / "native-runtime-manifest.json"
        raw_manifest = source_manifest.read_bytes()
        if _SECRETISH.search(raw_manifest.decode("utf-8", errors="ignore")):
            raise ValueError("credential-like pattern found in the original native runtime manifest")
        (native / "native-runtime-manifest.json").write_bytes(raw_manifest)
    if native_trace is not None:
        trace_path = native / "native-model-audit.jsonl"
        trace_path.write_text("".join(
            json.dumps(_sanitize(record), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for record in native_trace), encoding="utf-8")
    event_refs = {event.payload_ref for event in events if event.payload_ref}
    run_results = [result for result in store.list_results() if result.result_id in event_refs]
    for result in run_results:
        export_science_artifacts(result, native)
    specs = [spec.to_dict() for spec in store.list_specs() if spec.experiment_id in event_refs]
    results = [result.to_dict() for result in store.list_results() if result.result_id in event_refs]
    if native_verification is not None:
        native_verification["run_owned_results_persisted"] = len(results)
        _dump(native / "native-runtime-verification.json", native_verification)
    extra = {
        "schema_version": 1,
        "run_id": run_id,
        "packet_source": packet_source,
        "adaptive_packet": packet,
        "adaptive_review": review,
        "adaptive_selection": selection,
        "native_supervisor_response": supervisor_response,
        "native_runtime_verification": native_verification,
        "run_events": [event.to_dict() for event in events],
        "registered_specs": specs,
        "registered_results": results,
        "method_audit_records": method_output,
        "runtime": runtime,
        "provider_attestation": provider_attestation,
    }
    _dump(native / "adaptive_evidence.json", extra)
    _update_manifests_and_hashes(native)
    return native


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--remaining-seconds", type=float, default=600)
    parser.add_argument("--model", default="gpt-6-luna", help="operator reported model if no decision is persisted")
    parser.add_argument("--failure-detail", help="operator supplied failure detail, labeled as not persisted")
    args = parser.parse_args(argv)
    print(export_adaptive_evidence(args.database, args.run_id, args.output,
                                   remaining_seconds=args.remaining_seconds, model=args.model,
                                   failure_detail=args.failure_detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
