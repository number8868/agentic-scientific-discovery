"""Small transactional SQLite store for the NOVA prototype."""
from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Union
from .contracts import Event, ExperimentSpec, Result, ReviewPacket, Mode

class Storage:
    def __init__(self, path: Union[str, Path]): self.path=str(path)
    def _db(self):
        db=sqlite3.connect(self.path); db.row_factory=sqlite3.Row; db.execute("PRAGMA busy_timeout=5000"); return db
    def initialize(self):
        with self._db() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS specs (experiment_id TEXT PRIMARY KEY, spec_json TEXT NOT NULL, spec_sha256 TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_json TEXT NOT NULL, PRIMARY KEY(run_id,seq));
            CREATE TABLE IF NOT EXISTS results (result_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL UNIQUE, result_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews (result_id TEXT PRIMARY KEY, review_json TEXT NOT NULL);""")
        return self
    def register_spec(self,spec: ExperimentSpec):
        if not isinstance(spec,ExperimentSpec): raise TypeError("spec must be ExperimentSpec")
        with self._db() as db:
            row=db.execute("SELECT spec_json FROM specs WHERE experiment_id=?",(spec.experiment_id,)).fetchone()
            raw=spec.to_json()
            if row:
                if row[0] != raw: raise ValueError("experiment_id already registered with different spec")
                return spec
            db.execute("INSERT INTO specs VALUES (?,?,?)",(spec.experiment_id,raw,spec.sha256))
        return spec
    def get_spec(self, experiment_id):
        with self._db() as db:
            r=db.execute("SELECT spec_json FROM specs WHERE experiment_id=?",(experiment_id,)).fetchone()
        return ExperimentSpec.from_dict(json.loads(r[0])) if r else None
    read_spec = get_spec
    def append_event(self, run_id: Union[str, Event], event_type=None, actor="system", mode=Mode.LIVE, payload_ref=None, attempt=0, timestamp_utc=None, event_id=None):
        if isinstance(run_id,Event):
            event=run_id; run_id=event.run_id; event_type=event.event_type; actor=event.actor; mode=event.mode; payload_ref=event.payload_ref; attempt=event.attempt; timestamp_utc=event.timestamp_utc; event_id=event.event_id
        timestamp_utc=timestamp_utc or datetime.now(timezone.utc).isoformat(); event_id=event_id or str(uuid.uuid4())
        with self._db() as db:
            row=db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?",(run_id,)).fetchone(); seq=row[0]
            event=Event(run_id,seq,event_id,event_type,actor,timestamp_utc,attempt,mode,payload_ref)
            db.execute("INSERT INTO events VALUES (?,?,?)",(run_id,seq,event.to_json()))
        return event
    def list_events(self,run_id):
        with self._db() as db: rows=db.execute("SELECT event_json FROM events WHERE run_id=? ORDER BY seq",(run_id,)).fetchall()
        return [Event.from_dict(json.loads(r[0])) for r in rows]
    def save_result(self,result: Result):
        spec = self.get_spec(result.experiment_id)
        if spec is None: raise ValueError("result references unknown experiment")
        if result.spec_sha256 != spec.sha256: raise ValueError("result spec_sha256 does not match registered spec")
        with self._db() as db:
            old=db.execute("SELECT result_json FROM results WHERE experiment_id=?",(result.experiment_id,)).fetchone()
            raw=result.to_json()
            if old:
                if old[0] != raw: raise ValueError("experiment already has a different result")
                return result
            db.execute("INSERT INTO results VALUES (?,?,?)",(result.result_id,result.experiment_id,raw))
        return result
    def get_result(self,result_id):
        with self._db() as db: r=db.execute("SELECT result_json FROM results WHERE result_id=?",(result_id,)).fetchone()
        return Result.from_dict(json.loads(r[0])) if r else None
    read_result = get_result
    def save_review(self,review: ReviewPacket):
        if self.get_spec(review.experiment_id) is None: raise ValueError("review references unknown experiment")
        result = self.get_result(review.result_id)
        if result is None: raise ValueError("review references unknown result")
        if result.experiment_id != review.experiment_id: raise ValueError("review experiment/result mismatch")
        raw = review.to_json()
        with self._db() as db:
            old=db.execute("SELECT review_json FROM reviews WHERE result_id=?",(review.result_id,)).fetchone()
            if old and old[0] != raw: raise ValueError("result already has a different review")
            if not old: db.execute("INSERT INTO reviews VALUES (?,?)",(review.result_id,raw))
        return review
    def get_review(self,result_id):
        with self._db() as db: r=db.execute("SELECT review_json FROM reviews WHERE result_id=?",(result_id,)).fetchone()
        return ReviewPacket.from_dict(json.loads(r[0])) if r else None
    read_review = get_review
    def list_specs(self):
        with self._db() as db: rows=db.execute("SELECT spec_json FROM specs ORDER BY experiment_id").fetchall()
        return [ExperimentSpec.from_dict(json.loads(r[0])) for r in rows]
    def list_results(self):
        with self._db() as db: rows=db.execute("SELECT result_json FROM results ORDER BY result_id").fetchall()
        return [Result.from_dict(json.loads(r[0])) for r in rows]

def initialize(path): return Storage(path).initialize()
