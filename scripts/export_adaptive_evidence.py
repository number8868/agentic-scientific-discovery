#!/usr/bin/env python3
"""Export portable, sanitized evidence for a live adaptive discovery run."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
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


def export_adaptive_evidence(database: Path, run_id: str, output: Path,
                             *, remaining_seconds: float = 600,
                             model: str = "gpt-6-luna") -> Path:
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
    if row:
        packet = json.loads(row["packet_json"])
        selection = {"choice": row["choice"], "reason": row["reason"],
                     "selection": json.loads(row["selection_json"])}
        packet_source = "recorded_decision_packet"
        runtime = packet.get("selection_provenance", {})
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

    native = export_run(database, run_id, output)
    _sanitize_native_export(native)
    event_refs = {event.payload_ref for event in events if event.payload_ref}
    run_results = [result for result in store.list_results() if result.result_id in event_refs]
    for result in run_results:
        export_science_artifacts(result, native)
    specs = [spec.to_dict() for spec in store.list_specs() if spec.experiment_id in event_refs]
    results = [result.to_dict() for result in store.list_results() if result.result_id in event_refs]
    extra = {
        "schema_version": 1,
        "run_id": run_id,
        "packet_source": packet_source,
        "adaptive_packet": packet,
        "adaptive_selection": selection,
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
    args = parser.parse_args(argv)
    print(export_adaptive_evidence(args.database, args.run_id, args.output,
                                   remaining_seconds=args.remaining_seconds, model=args.model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
