"""Host-authorized registered-ID bridge for the live science executor."""
from __future__ import annotations
import json, os, stat
from pathlib import Path
from typing import Any
from .contracts import Result, Template
from .storage import Storage

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_CONTEXT_PATH = REPO_ROOT / ".nova" / "live_context.json"

def _secure(path: Path, message: str):
    try: info = path.lstat()
    except OSError: raise ValueError(message) from None
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077: raise ValueError(message)

def _read_context():
    _secure(Path(LIVE_CONTEXT_PATH), "live context is unavailable")
    try: data = json.loads(Path(LIVE_CONTEXT_PATH).read_text(encoding="utf-8"))
    except Exception: raise ValueError("live context is invalid") from None
    if not isinstance(data, dict) or set(data) != {"schema_version", "mode", "db", "run_id"}:
        raise ValueError("live context is invalid")
    if data.get("schema_version") != 1 or data.get("mode") != "live": raise ValueError("live context is invalid")
    db, run_id = data.get("db"), data.get("run_id")
    if not isinstance(db, str) or not os.path.isabs(db) or not isinstance(run_id, str) or not run_id:
        raise ValueError("live context is invalid")
    db_path = Path(db); _secure(db_path, "live database is unavailable")
    return db_path, run_id

_context = _read_context

def execute_live_registered_experiment(experiment_id: str) -> Result:
    if not isinstance(experiment_id, str) or not experiment_id or os.path.sep in experiment_id:
        raise ValueError("invalid experiment id")
    db_path, run_id = _read_context()
    try:
        store = Storage(db_path).initialize(); events = store.list_events(run_id)
    except Exception: raise ValueError("live database is unavailable") from None
    if not events or any(str(event.mode) != "live" for event in events):
        raise ValueError("run is not authorized for live execution")
    if not any(event.event_type in {"selection", "second_selection"} and event.actor == "pi" and event.payload_ref == experiment_id for event in events):
        raise ValueError("experiment is not registered for this run")
    spec = store.read_spec(experiment_id)
    if spec is None or spec.template not in {Template.FAMILY_SCREEN, Template.THRESHOLD_SENSITIVITY}:
        raise ValueError("experiment is not registered for live execution")
    existing = next((result for result in store.list_results() if result.experiment_id == experiment_id), None)
    if existing is not None: return existing
    try:
        from .science_adapter import execute_science_experiment
        payload = spec.to_dict(); payload.update(mode="live", run_id=run_id)
        store.append_event(run_id, "running", actor="runner", mode="live", payload_ref=experiment_id)
        result = execute_science_experiment(payload)
        if not isinstance(result, Result): raise TypeError("science adapter returned non-canonical result")
        store.save_result(result)
        store.append_event(run_id, "result", actor="runner", mode="live", payload_ref=result.result_id)
        return result
    except Exception:
        try: store.append_event(run_id, "tool_failed", actor="host", mode="live", payload_ref=experiment_id)
        except Exception: pass
        raise ValueError("live execution failed") from None
