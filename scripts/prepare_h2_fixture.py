#!/usr/bin/env python3
"""Create a local, offline H2 fixture run for the Omnigent handoff test."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nova.contracts import ExperimentSpec, Mode, Split, Template
from nova.storage import Storage

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CONTEXT_PATH = ROOT / ".nova" / "context.json"


def _safe_db(path: Path) -> Path:
    path = path.expanduser().resolve()
    home = Path.home().resolve()
    if path == Path("/").resolve() or path == home:
        raise ValueError("refusing root or home as database target")
    if path.exists() and path.is_dir():
        raise ValueError("database target must be a file, not a directory")
    if path.exists() and path.stat().st_size:
        with path.open("rb") as handle:
            if handle.read(16) != b"SQLite format 3\x00":
                raise ValueError("existing non-empty target is not SQLite")
        try:
            with sqlite3.connect(str(path)) as connection:
                connection.execute("PRAGMA schema_version").fetchone()
        except sqlite3.DatabaseError as exc:
            raise ValueError("existing target is not a readable SQLite database") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(value: Optional[str]) -> str:
    value = value or "run-" + uuid.uuid4().hex[:12]
    if not SAFE_ID.fullmatch(value):
        raise ValueError("run-id must contain only safe identifier characters")
    return value


def _write_context(db: Path, run_id: str) -> Path:
    """Atomically publish the bridge context with restrictive permissions."""
    directory = CONTEXT_PATH.parent
    if directory.exists() and directory.is_symlink():
        raise ValueError("context directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    if CONTEXT_PATH.exists() and CONTEXT_PATH.is_symlink():
        raise ValueError("context path must not be a symlink")
    payload = {"schema_version": 1, "mode": "fixture", "db": str(db), "run_id": run_id}
    fd, temporary = tempfile.mkstemp(prefix="context.", suffix=".tmp", dir=str(directory))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(CONTEXT_PATH))
        os.chmod(CONTEXT_PATH, 0o600)
        return CONTEXT_PATH
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def prepare_h2_fixture(db: Path, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Prepare one canonical family_screen fixture without invoking a process."""
    target = _safe_db(Path(db))
    run_id = _safe_id(run_id)
    spec = ExperimentSpec(
        schema_version=1,
        experiment_id="EXP-H2-FIXTURE-001",
        hypothesis_id="H-001",
        dataset_sha256="fixture-dataset-sha256-placeholder",
        split=Split.DISCOVERY,
        template=Template.FAMILY_SCREEN,
        groups=("oxide", "chalcogenide"),
        bandgap_method="opt",
        gap_window_ev=(1.1, 1.8),
        ehull_max_ev_atom=0.05,
        bootstrap_repeats=2000,
        seed=1729,
        timeout_seconds=120,
    )
    store = Storage(target).initialize()
    store.register_spec(spec)
    store.append_event(run_id, "run_created", actor="host", mode=Mode.FIXTURE, payload_ref=None)
    store.append_event(run_id, "hypothesis_frozen", actor="pi", mode=Mode.FIXTURE, payload_ref=spec.hypothesis_id)
    store.append_event(run_id, "selection", actor="pi", mode=Mode.FIXTURE, payload_ref=spec.experiment_id)
    target.chmod(0o600)
    context_path = _write_context(target, run_id)
    return {
        "db": str(target),
        "run_id": run_id,
        "experiment_id": spec.experiment_id,
        "mode": "fixture",
        "spec_sha256": spec.sha256,
        "context_path": str(context_path),
        "next_command": "PATH=.venv-tmux/bin:$PATH .venv-omnigent/bin/omnigent run agents/opensource.yaml",
        "bridge_callable": "nova.omnigent_bridge.execute_fixture_registered_experiment",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare an offline NOVA H2 fixture database")
    parser.add_argument("--db", required=True, help="SQLite file to create or reuse")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    print(json.dumps(prepare_h2_fixture(Path(args.db), args.run_id), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
