"""Export already persisted native holdout evidence without executing science."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def export_native_holdout_evidence(database: Path, run_id: str, holdout_result_id: str,
                                  deadline: float) -> Path:
    """Export a completed holdout Result and frozen protocol under the original deadline."""
    from nova.evidence import export_run
    from nova.experiments.executor import export_science_artifacts
    from nova.live_bridge import _read_context
    from nova.storage import Storage

    database_input = Path(database)
    if database_input.is_symlink() or not math.isfinite(deadline):
        raise ValueError("native holdout export requires a regular bound database and finite deadline")
    database = database_input.resolve(strict=True)
    run_dir = database.parent.resolve(strict=True)
    runs_root = (ROOT / "runs").resolve()
    output = run_dir / "native-holdout-evidence"

    def checkpoint() -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("native holdout evidence export exceeded the shared workflow deadline")
        actual_db, actual_run = _read_context()
        if Path(actual_db).resolve() != database or actual_run != run_id:
            raise ValueError("live context changed during native holdout evidence export")

    if (not run_dir.is_relative_to(runs_root) or not database.is_file() or
            database.is_symlink() or output.exists()):
        raise ValueError("native holdout evidence requires a run-owned database and new output directory")
    checkpoint()
    store = Storage(database).initialize()
    checkpoint()
    result = next((item for item in store.list_results() if item.result_id == holdout_result_id), None)
    with sqlite3.connect(str(database)) as db:
        row = db.execute("SELECT frozen_protocol_id,protocol_sha256,protocol_json,holdout_experiment_id "
                         "FROM final_protocols WHERE run_id=?",
                         (run_id,)).fetchone()
    if row is None:
        raise ValueError("frozen native protocol is unavailable during evidence export")
    frozen_id, protocol_sha256, protocol_raw, holdout_id = row
    if result is None or result.experiment_id != holdout_id:
        raise ValueError("completed holdout Result is not the frozen protocol's registered Result")
    protocol = json.loads(protocol_raw)
    canonical_protocol = json.dumps(protocol, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if hashlib.sha256(canonical_protocol.encode()).hexdigest() != protocol_sha256:
        raise ValueError("frozen native protocol hash is invalid")
    spec = store.get_spec(holdout_id)
    if spec is None:
        raise ValueError("frozen holdout Spec is unavailable during evidence export")
    try:
        with sqlite3.connect(str(database)) as db:
            claim = db.execute("SELECT frozen_protocol_id,protocol_sha256,spec_sha256,state,result_id "
                               "FROM holdout_bridge_claims WHERE run_id=? AND holdout_experiment_id=?",
                               (run_id, holdout_id)).fetchone()
    except sqlite3.OperationalError:
        claim = None
    run_events = store.list_events(run_id)
    if (claim != (frozen_id, protocol_sha256, spec.sha256, "succeeded", result.result_id) or
            not any(event.event_type == "holdout_result" and event.actor == "runner" and
                    event.mode.value == "live" and event.payload_ref == result.result_id for event in run_events)):
        raise ValueError("holdout Result lacks its succeeded claim and run-owned Result event")
    checkpoint()
    export_run(database, run_id, output)
    checkpoint()
    specs_path = output / "specs.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    if not any(item.get("experiment_id") == spec.experiment_id for item in specs):
        specs.append(spec.to_dict())
    (output / "specs.json").write_text(json.dumps(specs, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    results_path = output / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if not any(item.get("result_id") == result.result_id for item in results):
        results.append(result.to_dict())
    results_path.write_text(json.dumps(results, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    checkpoint()
    export_science_artifacts(result, output)
    event_refs = {event.payload_ref for event in run_events
                  if event.event_type == "result" and event.actor == "runner" and
                  event.mode.value == "live" and event.payload_ref}
    for stored in store.list_results():
        if stored.result_id in event_refs and stored.result_id != result.result_id:
            checkpoint()
            export_science_artifacts(stored, output)
    (output / "final_protocol.json").write_bytes(protocol_raw.encode("utf-8"))
    holdout_record = run_dir / "native-holdout-result.json"
    if holdout_record.is_file() and not holdout_record.is_symlink():
        shutil.copyfile(holdout_record, output / holdout_record.name)
    checkpoint()
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["native_final_protocol"] = {"protocol_sha256": protocol_sha256,
                                         "holdout_experiment_id": holdout_id}
    for path in sorted(item for item in output.iterdir() if item.is_file() and item.name != "manifest.json"):
        prior = manifest["files"].get(path.name, {})
        count = len(specs) if path.name == "specs.json" else len(results) if path.name == "results.json" else prior.get("count", 1)
        manifest["files"][path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "count": count}
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    checkpoint()
    return output
