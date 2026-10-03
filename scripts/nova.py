"""Minimal NOVA-MAT command line: prepare one snapshot, then screen discovery."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nova.data.pipeline import DATA_ROOT, DEFAULT_CACHE_DIR, PROJECT_ROOT, prepare_dataset
from nova.experiments.family_screen import run_experiment


def _default_spec() -> dict[str, object]:
    manifest = json.loads((DATA_ROOT / "manifest.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "template": "family_screen",
        "split": "discovery",
        "groups": ["oxide", "chalcogenide"],
        "bandgap_method": "opt",
        "gap_window_ev": [1.1, 1.8],
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "dataset_sha256": manifest["original_download_zip_sha256"],
    }


def _prepare(cache_dir: str) -> int:
    manifest = prepare_dataset(cache_dir)
    print(json.dumps({
        "status": "prepared",
        "dataset": manifest["dataset"],
        "source_zip_sha256": manifest["original_download_zip_sha256"],
        "protocol_sha256": manifest["protocol_sha256"],
        "raw_record_count": manifest["raw_record_count"],
        "download_completed_at_utc": manifest["download_completed_at_utc"],
        "holdout_access": "metadata counts and coverage only",
    }, indent=2))
    return 0


def _screen() -> int:
    result = run_experiment(_default_spec())
    output_dir = PROJECT_ROOT / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_path = output_dir / f"family_screen.discovery.{result['spec_sha256'][:12]}.{run_stamp}.{uuid4().hex[:8]}.json"
    result["artifact_file"] = output_path.relative_to(PROJECT_ROOT).as_posix()
    with output_path.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(result, file, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        file.write("\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nova", description="NOVA-MAT minimal data preparation and discovery screen")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="download via jarvis-tools, audit, and freeze the snapshot/protocol")
    prepare.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="project-local jarvis-tools cache directory")
    subparsers.add_parser("screen", help="run the frozen family_screen on discovery compositions only")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        return _prepare(args.cache_dir)
    if args.command == "screen":
        return _screen()
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
