"""Cross-process bridge for the deliberately limited H2 fixture execution."""
from __future__ import annotations

import os
import stat
from typing import Any, Mapping

from .contracts import GroupSummary, Result
from .fixture_engine import execute as execute_fixture
from .storage import Storage


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError("fixture bridge environment is incomplete")
    return value


def _canonical(value: Any, spec) -> Result:
    data = value.to_dict() if hasattr(value, "to_dict") else dict(value)
    groups = data.get("groups_summary") or {}
    if isinstance(groups, Mapping):
        groups = [dict(item, group=group) for group, item in groups.items()]
    summaries = []
    for index, item in enumerate(groups):
        item = dict(item)
        item.setdefault("group", "group-%d" % index)
        summaries.append(GroupSummary.from_dict(item))
    status = data.get("execution_status", "completed")
    scientific = None if status in {"failed", "timeout"} else data.get("scientific_status")
    return Result(
        result_id=str(data["result_id"]), experiment_id=spec.experiment_id,
        spec_sha256=spec.sha256, dataset_sha256=spec.dataset_sha256,
        execution_status=status, scientific_status=scientific,
        started_at=str(data.get("started_at", "fixture")),
        finished_at=str(data.get("finished_at", "fixture")),
        elapsed_seconds=float(data.get("elapsed_seconds", 0)),
        groups_summary=tuple(summaries), delta=data.get("delta"),
        resampling_interval=data.get("resampling_interval"),
        missingness_interval=data.get("missingness_interval"),
        quality_flags=tuple(data.get("quality_flags", ("fixture",))),
        artifact_ids=tuple(data.get("artifact_ids", ())), error=data.get("error"),
    )


def execute_fixture_registered_experiment(experiment_id: str) -> Result:
    """Execute one host-authorized fixture experiment from a fresh process.

    The only caller-controlled value is the registered experiment id.  Database
    path and run id are host-injected environment values and are never echoed in
    errors.
    """
    if not isinstance(experiment_id, str) or not experiment_id or os.path.sep in experiment_id:
        raise ValueError("invalid experiment id")
    db_path = _env("NOVA_RUN_DB")
    run_id = _env("NOVA_RUN_ID")
    try:
        mode = os.lstat(db_path).st_mode
    except (OSError, ValueError):
        raise ValueError("fixture database is unavailable") from None
    if not stat.S_ISREG(mode):
        raise ValueError("fixture database is unavailable")
    try:
        store = Storage(db_path).initialize()
        events = store.list_events(run_id)
    except Exception:
        raise ValueError("fixture database is unavailable") from None
    if not events or any(str(event.mode) != "fixture" for event in events):
        raise ValueError("run is not authorized for fixture execution")
    selections = [event for event in events
                  if event.event_type in {"selection", "second_selection"}
                  and event.actor == "pi" and event.payload_ref == experiment_id]
    if not selections:
        raise ValueError("experiment is not registered for this run")
    spec = store.read_spec(experiment_id)
    if spec is None:
        raise ValueError("experiment is not registered for this run")
    existing = next((r for r in store.list_results() if r.experiment_id == experiment_id), None)
    if existing is not None:
        return existing
    try:
        payload = spec.to_dict()
        payload["mode"] = "fixture"
        store.append_event(run_id, "running", actor="runner", mode="fixture", payload_ref=experiment_id)
        result = _canonical(execute_fixture(payload), spec)
        store.save_result(result)
        store.append_event(run_id, "result", actor="runner", mode="fixture", payload_ref=result.result_id)
        return result
    except Exception:
        store.append_event(run_id, "tool_failed", actor="host", mode="fixture", payload_ref=experiment_id)
        raise ValueError("fixture execution failed") from None
