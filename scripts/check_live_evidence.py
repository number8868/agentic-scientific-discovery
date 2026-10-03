#!/usr/bin/env python3
"""Fail-closed structural provenance check for one real Omnigent run.

This check deliberately does not inspect or recompute scientific payload values.  It
only checks the trusted SQLite records, their hashes, and the run's state machine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# When invoked as ``python scripts/check_live_evidence.py``, Python puts the
# scripts directory first and its nova.py launcher would shadow the package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nova.contracts import ExperimentSpec, Mode, Result


class EvidenceError(ValueError):
    pass


def _rows(db: sqlite3.Connection, table: str, column: str, where: str = "", args=()):
    query = f"SELECT {column} FROM {table}" + ((" WHERE " + where) if where else "")
    return [json.loads(row[0]) for row in db.execute(query, args).fetchall()]


def _fail(message: str):
    raise EvidenceError(message)


def check(db_path: str | Path, run_id: str) -> dict[str, Any]:
    """Validate the live-evidence contract for ``run_id``; raise on any failure."""
    if not isinstance(run_id, str) or not run_id:
        _fail("run_id must be non-empty")
    source = Path(db_path)
    if not source.is_file():
        _fail("database does not exist")
    with sqlite3.connect(str(source)) as db:
        events = _rows(db, "events", "event_json", "run_id=? ORDER BY seq", (run_id,))
        if not events:
            _fail("run has no events")
        if any(e.get("mode") != Mode.LIVE.value for e in events):
            _fail("fixture/replay/mixed event provenance")
        # Human-scripted runs are useful integration fixtures, but are not evidence
        # of an Omnigent model run and must never pass this gate.
        raw_events = "\n".join(json.dumps(e, sort_keys=True) for e in events).lower()
        if "human_scripted" in raw_events or "fixture" in raw_events or "replay" in raw_events:
            _fail("human-scripted or fixture provenance is not live Omnigent evidence")

        seqs = [e.get("seq") for e in events]
        if seqs != list(range(1, len(events) + 1)):
            _fail("event sequence is not contiguous")
        required = [
            "run_created", "objective_registered", "hypothesis_frozen", "plan_registered", "selection",
            "running", "result", "review", "second_selection", "running", "result",
            "second_review", "final_protocol_frozen",
        ]
        types = [e.get("event_type") for e in events]
        pos = -1
        for expected in required:
            try:
                nxt = types.index(expected, pos + 1)
            except ValueError:
                _fail(f"missing or out-of-order event: {expected}")
            pos = nxt
        if len(types) != len(required):
            _fail("unexpected event(s) in live run")

        specs_raw = _rows(db, "specs", "spec_json")
        results_raw = _rows(db, "results", "result_json")
        reviews_raw = _rows(db, "reviews", "review_json")
        final_db_rows = db.execute("SELECT frozen_protocol_id, protocol_sha256, protocol_json, holdout_experiment_id FROM final_protocols WHERE run_id=?", (run_id,)).fetchall()
        if len(final_db_rows) != 1:
            _fail("exactly one final protocol is required")
        frozen_protocol_id, protocol_hash, protocol_raw, holdout_id = final_db_rows[0]
        protocol = json.loads(protocol_raw)
        expected_protocol_hash = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if protocol_hash != expected_protocol_hash:
            _fail("final protocol hash mismatch")
        # The final protocol is stored separately; its two discovery Specs are the
        # only specs selected by this run, and the holdout must remain unexecuted.
        selected = [e.get("payload_ref") for e in events if e.get("event_type") in {"selection", "second_selection"}]
        if len(selected) != 2 or any(not x for x in selected) or selected[0] == selected[1]:
            _fail("run must select exactly two distinct experiments")
        specs = {s.get("experiment_id"): s for s in specs_raw if s.get("experiment_id") in set(selected) or s.get("experiment_id") == holdout_id}
        if set(specs) != set(selected) | {holdout_id} or len(specs) != 3:
            _fail("run must contain exactly two discovery specs and one holdout spec")
        parsed_specs = {}
        for experiment_id, raw in specs.items():
            try:
                parsed = ExperimentSpec.from_dict(raw)
            except Exception as exc:
                _fail(f"invalid registered spec: {experiment_id}: {exc}")
            if parsed.sha256 != hashlib.sha256(parsed.to_json().encode()).hexdigest():
                _fail(f"spec hash mismatch: {experiment_id}")
            parsed_specs[experiment_id] = parsed
        discovery = [parsed_specs[x] for x in selected]
        if any(s.split.value != "discovery" for s in discovery):
            _fail("selected specs must be discovery specs")
        holdout = parsed_specs[holdout_id]
        if holdout.split.value != "holdout" or holdout.template.value != "holdout_validation":
            _fail("holdout spec is not frozen holdout_validation")
        if holdout.frozen_protocol_id != frozen_protocol_id:
            _fail("holdout frozen protocol reference is inconsistent")

        result_map = {}
        for raw in results_raw:
            try:
                result = Result.from_dict(raw)
            except Exception as exc:
                _fail(f"invalid result record: {exc}")
            if result.experiment_id in selected:
                if result.experiment_id in result_map:
                    _fail("duplicate result for selected spec")
                result_map[result.experiment_id] = result
        if set(result_map) != set(selected) or len(result_map) != 2:
            _fail("exactly two selected Specs must have Results")
        if any(r.execution_status != "completed" or r.error is not None for r in result_map.values()):
            _fail("selected Results must be completed and error-free")
        for experiment_id, result in result_map.items():
            spec = parsed_specs[experiment_id]
            if result.spec_sha256 != spec.sha256 or result.dataset_sha256 != spec.dataset_sha256:
                _fail("Result/spec/dataset hash mismatch")
        if any(r.get("experiment_id") == holdout_id for r in results_raw):
            _fail("holdout has been executed")

        first, second = result_map[selected[0]], result_map[selected[1]]
        if parsed_specs[selected[1]].parent_result_id != first.result_id or parsed_specs[selected[1]].review_id != first.result_id:
            _fail("follow-up lineage does not point to first Result")
        if protocol.get("main_result_id") != first.result_id or protocol.get("followup_result_id") != second.result_id:
            _fail("final protocol Result references are inconsistent")
        if protocol.get("dataset_sha256") != discovery[0].dataset_sha256 or any(s.dataset_sha256 != protocol.get("dataset_sha256") for s in (discovery[1], holdout)):
            _fail("dataset hash is not consistent across protocol and specs")
        if protocol.get("review_refs") != [first.result_id, second.result_id]:
            _fail("final protocol review references are incomplete")

        review_map = {r.get("result_id"): r for r in reviews_raw}
        if set(review_map) != {first.result_id, second.result_id} or len(review_map) != 2:
            _fail("first and second reviews are both required")
        if first.result_id not in review_map[first.result_id].get("claim_refs", ()):
            _fail("first review does not cite first Result")
        if second.result_id not in review_map[second.result_id].get("claim_refs", ()):
            _fail("second review does not cite second Result")
        if any("human_scripted" in json.dumps(r, sort_keys=True).lower() for r in reviews_raw):
            _fail("human-scripted review is not admissible")

    return {"ok": True, "run_id": run_id, "mode": "live", "results": 2, "reviews": 2,
            "holdout_experiment_id": holdout_id}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed live Omnigent evidence gate")
    parser.add_argument("database")
    parser.add_argument("run_id")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(check(args.database, args.run_id), sort_keys=True))
    except EvidenceError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
