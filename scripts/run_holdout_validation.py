#!/usr/bin/env python3
"""Execute one frozen registered holdout through its bounded host gate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to((ROOT / "runs").resolve())
    except ValueError:
        raise ValueError("evidence output must be inside the project runs directory") from None
    if resolved == (ROOT / "runs").resolve():
        raise ValueError("use a separate evidence subdirectory")
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise ValueError("evidence output must be new or empty")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True, help="holdout ID returned by freeze_final")
    parser.add_argument("--output", type=Path, help="new or empty directory under runs/")
    args = parser.parse_args(argv)
    try:
        # Check output before invoking the one-attempt holdout gate.
        output = _output_path(args.output or ROOT / "runs" / ("holdout-export-" + uuid4().hex[:12]))
        from nova.evidence import export_run
        from nova.experiments.executor import export_science_artifacts
        from nova.holdout_bridge import execute_live_registered_holdout
        from nova.live_bridge import _read_context
        from nova.storage import Storage

        db, run_id = _read_context()
        result = execute_live_registered_holdout(args.experiment_id)
        if _read_context() != (db, run_id):
            raise ValueError("live context changed; refusing evidence export")
        store = Storage(db).initialize()
        export_run(db, run_id, output)
        for stored in store.list_results():
            if stored.result_id == result.result_id or any(
                event.event_type == "result" and event.actor == "runner"
                and event.payload_ref == stored.result_id
                for event in store.list_events(run_id)
            ):
                export_science_artifacts(stored, output)
        protocol = store.get_final_protocol(run_id)
        protocol_bytes = (json.dumps(protocol, sort_keys=True, separators=(",", ":")) + "\n").encode()
        (output / "final_protocol.json").write_bytes(protocol_bytes)
        manifest_path = output / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name in ("final_protocol.json", "science-artifacts.json"):
            content = (output / name).read_bytes()
            manifest["files"][name] = {"sha256": hashlib.sha256(content).hexdigest(), "count": 1}
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"run_id": run_id, "result_id": result.result_id,
                          "execution_status": result.execution_status,
                          "scientific_status": result.scientific_status,
                          "evidence_directory": str(output)}, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"holdout validation/export failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
