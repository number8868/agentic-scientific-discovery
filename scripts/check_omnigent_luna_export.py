#!/usr/bin/env python3
"""Fail-closed checks for the portable Omnigent Luna export.

This is intentionally independent of the live SQLite checker.  A portable
export is complete only when its event log, reviews, and final-protocol
artifacts all prove the complete 13-event contract.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_EVENTS = (
    "run_created", "objective_registered", "hypothesis_frozen", "plan_registered",
    "selection", "running", "result", "review", "second_selection", "running",
    "result", "second_review", "final_protocol_frozen",
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_export(directory: str | Path) -> dict:
    root = Path(directory)
    events_path = root / "events.jsonl"
    if not events_path.is_file():
        raise ValueError("missing events.jsonl")
    events = [_read_json_line(line, events_path, n) for n, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1)]
    event_types = [event.get("event_type") for event in events]
    if tuple(event_types) != REQUIRED_EVENTS:
        raise ValueError("export lacks the complete 13-event final-protocol sequence")
    results = _read_json(root / "results.json")
    reviews = _read_json(root / "reviews.json")
    specs = _read_json(root / "specs.json")
    if not isinstance(results, list) or len(results) != 2:
        raise ValueError("exactly two discovery Results are required")
    if not isinstance(reviews, list) or len(reviews) != 2:
        raise ValueError("first and second reviews are required")
    if not isinstance(specs, list) or len(specs) != 3:
        raise ValueError("two discovery Specs and one holdout Spec are required")
    if not any(spec.get("split") == "holdout" for spec in specs):
        raise ValueError("holdout Spec is missing")
    decisions = _read_json(root / "decisions.json")
    if not isinstance(decisions, dict) or not decisions.get("final_protocol"):
        raise ValueError("final protocol record is missing")
    return {"ok": True, "results": 2, "reviews": 2, "final_protocol_frozen": True}


def _read_json_line(line: str, path: Path, number: int):
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at {path}:{number}") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(check_export(args.directory), sort_keys=True))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
