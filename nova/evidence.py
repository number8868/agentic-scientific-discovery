"""Auditable, run-scoped SQLite evidence export (standard library only)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Set


FILES = ("events.jsonl", "specs.json", "results.json", "reviews.json")


def _json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _safe_output(path: Path) -> Path:
    raw = os.path.abspath(os.fspath(path))
    if any(part == ".." for part in Path(os.fspath(path)).parts):
        raise ValueError("output path traversal is not allowed")
    resolved = Path(raw).resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home():
        raise ValueError("refusing root or home output directory")
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("output path is not a directory")
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError("output directory must be new or empty")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _atomic_write(path: Path, data: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=".nova-export-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _rows(db: sqlite3.Connection, query: str, args: tuple = ()) -> List[dict]:
    db.row_factory = sqlite3.Row
    return [json.loads(row[0]) for row in db.execute(query, args).fetchall()]


def export_run(db_path: os.PathLike, run_id: str, output_dir: os.PathLike) -> Path:
    """Export only entities referenced by this run's events."""
    if not run_id or not isinstance(run_id, str):
        raise ValueError("run_id must be a non-empty string")
    source = Path(db_path)
    if not source.is_file():
        raise ValueError("database must be an existing file")
    with sqlite3.connect(os.fspath(source)) as db:
        event_rows = _rows(db, "SELECT event_json FROM events WHERE run_id=? ORDER BY seq", (run_id,))
        if not event_rows:
            raise ValueError("run_id has no events")
        refs: Set[str] = set()
        modes: Set[str] = set()
        for event in event_rows:
            refs.add(str(event.get("payload_ref"))) if event.get("payload_ref") else None
            if event.get("mode") is not None:
                modes.add(str(event["mode"]))
        all_specs = _rows(db, "SELECT spec_json FROM specs")
        all_results = _rows(db, "SELECT result_json FROM results")
        all_reviews = _rows(db, "SELECT review_json FROM reviews")
        specs = [x for x in all_specs if x.get("experiment_id") in refs or x.get("spec_sha256") in refs]
        experiment_ids = {x.get("experiment_id") for x in specs}
        results = [x for x in all_results if x.get("experiment_id") in experiment_ids or x.get("result_id") in refs]
        result_ids = {x.get("result_id") for x in results}
        reviews = [x for x in all_reviews if x.get("result_id") in result_ids or x.get("result_id") in refs]
    out = _safe_output(Path(output_dir))
    mode = next(iter(modes)) if len(modes) == 1 else ("mixed" if modes else "unknown")
    payloads = {
        "events.jsonl": b"".join((json.dumps(_json(x), sort_keys=True, separators=(",", ":")) + "\n").encode() for x in event_rows),
        "specs.json": json.dumps(_json(specs), sort_keys=True, indent=2).encode() + b"\n",
        "results.json": json.dumps(_json(results), sort_keys=True, indent=2).encode() + b"\n",
        "reviews.json": json.dumps(_json(reviews), sort_keys=True, indent=2).encode() + b"\n",
    }
    for filename, data in payloads.items():
        _atomic_write(out / filename, data)
    manifest: Dict[str, Any] = {"schema_version": 1, "run_id": run_id, "mode": mode,
        "exported_at": datetime.now(timezone.utc).isoformat(), "files": {}}
    counts = {"events.jsonl": len(event_rows), "specs.json": len(specs), "results.json": len(results), "reviews.json": len(reviews)}
    for filename in FILES:
        data = (out / filename).read_bytes()
        manifest["files"][filename] = {"sha256": hashlib.sha256(data).hexdigest(), "count": counts[filename]}
    _atomic_write(out / "manifest.json", (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode())
    return out
