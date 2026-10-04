"""Host-owned Planner/PI/Skeptic persistence tools.

The LLM supplies only bounded choices and prose. Context, actors, IDs, paths,
dataset hash, and all persisted specifications are constructed here.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from .contracts import Concern, Event, ExperimentSpec, Mode, PlanProposal, PlanPacket, ReviewPacket, Split, Template
from .storage import Storage

try:
    from .live_bridge import _read_context as _bridge_read_context
except ImportError:  # expected while the live bridge is being integrated
    from .omnigent_bridge import _read_context as _bridge_read_context


ALLOWED_TEMPLATES = frozenset(("family_screen", "threshold_sensitivity"))


def _read_context() -> Tuple[Path, str]:
    return _bridge_read_context()


def _ctx() -> Tuple[Path, str, Storage]:
    path, run_id = _read_context()
    store = Storage(path).initialize()
    return path, run_id, store


def _fail(run_id: str, store: Storage, reason: str) -> None:
    try:
        store.append_event(run_id, "schema_failed", actor="host", mode=Mode.LIVE, payload_ref=None)
    except Exception:
        pass
    raise ValueError(reason)


def _id(run_id: str, label: str) -> str:
    return "NOVA-" + hashlib.sha256((run_id + ":" + label).encode()).hexdigest()[:16]


def _table(path: Path) -> None:
    with sqlite3.connect(str(path)) as db:
        db.execute("CREATE TABLE IF NOT EXISTS decision_packets (run_id TEXT PRIMARY KEY, plan_json TEXT NOT NULL, review_json TEXT)")


def _has_registered_method_audit(path: Path, run_id: str) -> bool:
    """Return whether this run has entered the dedicated method-audit path."""
    with sqlite3.connect(str(path), timeout=5) as db:
        present = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='registered_method_audits'"
        ).fetchone()
        if present is None:
            return False
        return db.execute(
            "SELECT 1 FROM registered_method_audits WHERE run_id=? LIMIT 1", (run_id,)
        ).fetchone() is not None


def _packet(path: Path) -> Dict[str, Any]:
    _table(path)
    with sqlite3.connect(str(path)) as db:
        row = db.execute("SELECT plan_json, review_json FROM decision_packets WHERE run_id=?", (_read_context()[1],)).fetchone()
    if not row:
        return {}
    return {"plan": json.loads(row[0]), "review": json.loads(row[1]) if row[1] else None}


def register_initial_plan(chosen_template: str, selection_reason: str) -> Dict[str, Any]:
    """Register two host-built proposals; only the selected template is caller input."""
    path, run_id, store = _ctx()
    if chosen_template != "family_screen" or not isinstance(selection_reason, str) or not selection_reason.strip():
        _fail(run_id, store, "invalid initial plan choice")
    existing = _packet(path).get("plan")
    if existing:
        _fail(run_id, store, "initial plan already registered")
    dataset = _active_dataset_sha256()
    proposals = []
    for template in ("family_screen", "threshold_sensitivity"):
        draft = _draft(template, dataset)
        proposals.append(PlanProposal("proposal-" + template, draft, True, 120.0, 3, "bounded protocol-axis alternative"))
    packet = PlanPacket("H-001", tuple(proposals), "proposal-" + chosen_template, selection_reason.strip())
    raw = packet.to_json()
    _table(path)
    with sqlite3.connect(str(path)) as db:
        db.execute("INSERT INTO decision_packets(run_id,plan_json,review_json) VALUES(?,?,NULL)", (run_id, raw))
    store.append_event(run_id, "plan_registered", actor="planner", mode=Mode.LIVE, payload_ref=_id(run_id, "plan"))
    return packet.to_dict()


def commit_initial_spec(chosen_template: str) -> str:
    path, run_id, store = _ctx()
    packet = _packet(path).get("plan")
    if not packet or chosen_template != "family_screen":
        _fail(run_id, store, "plan is missing or invalid")
    if packet.get("chosen_proposal_id") != "proposal-" + chosen_template:
        _fail(run_id, store, "template does not match Planner selection")
    if store.list_specs():
        _fail(run_id, store, "initial spec already committed")
    spec = _make_spec(run_id, "initial", chosen_template, _active_dataset_sha256())
    store.register_spec(spec)
    store.append_event(run_id, "selection", actor="pi", mode=Mode.LIVE, payload_ref=spec.experiment_id)
    return spec.experiment_id


def submit_live_review(result_id: str, concern: str, recommended_template: str) -> Dict[str, Any]:
    path, run_id, store = _ctx()
    if not isinstance(result_id, str) or not isinstance(concern, str) or not concern.strip() or recommended_template not in ALLOWED_TEMPLATES:
        _fail(run_id, store, "invalid review packet")
    result = store.get_result(result_id)
    if result is None or result.execution_status != "completed" or result.error is not None:
        _fail(run_id, store, "review requires a successful stored result")
    spec = store.get_spec(result.experiment_id)
    events = store.list_events(run_id)
    if spec is None or not any(e.actor == "pi" and e.event_type in {"selection", "second_selection"}
                               and e.payload_ref == spec.experiment_id for e in events):
        _fail(run_id, store, "review result is not registered for this run")
    if not any(e.actor == "runner" and e.event_type == "result" and e.payload_ref == result_id
               for e in events):
        _fail(run_id, store, "review result is not owned by this run")
    if spec is None or spec.template.value == recommended_template:
        _fail(run_id, store, "review must recommend a different template")
    review = ReviewPacket(spec.experiment_id, result_id, (Concern("protocol_weakness", "medium", (result_id,)),), Template(recommended_template), concern.strip(), (result_id,))
    store.save_review(review)
    store.append_event(run_id, "review", actor="skeptic", mode=Mode.LIVE, payload_ref=result_id)
    _table(path)
    with sqlite3.connect(str(path)) as db:
        db.execute("UPDATE decision_packets SET review_json=? WHERE run_id=?", (review.to_json(), run_id))
    return review.to_dict()


def submit_final_review(result_id: str, concern: str) -> Dict[str, Any]:
    """Persist the required second-round Skeptic review without opening choices."""
    path, run_id, store = _ctx()
    if not isinstance(result_id, str) or not result_id or "/" in result_id or "\\" in result_id:
        _fail(run_id, store, "invalid final review reference")
    if not isinstance(concern, str) or not concern.strip() or len(concern) > 500:
        _fail(run_id, store, "invalid final review concern")
    result = store.get_result(result_id)
    if result is None or result.execution_status != "completed" or result.error is not None:
        _fail(run_id, store, "final review requires a successful stored result")
    spec = store.get_spec(result.experiment_id)
    if spec is None or spec.split is not Split.DISCOVERY:
        _fail(run_id, store, "final review requires a discovery result")
    # A final review is specifically for the second registered experiment.
    if not spec.parent_result_id or spec.review_id != spec.parent_result_id:
        _fail(run_id, store, "final review requires a follow-up result")
    events = store.list_events(run_id)
    if not any(e.actor == "pi" and e.event_type == "second_selection" and
               e.payload_ref == spec.experiment_id for e in events):
        _fail(run_id, store, "final review experiment belongs to another run")
    if not any(e.actor == "runner" and e.event_type == "result" and
               e.payload_ref == result_id for e in events):
        _fail(run_id, store, "final review result belongs to another run")
    review = ReviewPacket(spec.experiment_id, result_id,
                          (Concern("final_protocol", "medium", (result_id,)),),
                          None, concern.strip(), (result_id,))
    store.save_review(review)
    store.append_event(run_id, "second_review", actor="skeptic", mode=Mode.LIVE, payload_ref=result_id)
    return review.to_dict()


def commit_next_spec(result_id: str, recommended_template: str) -> str:
    path, run_id, store = _ctx()
    packet = _packet(path)
    review = store.get_review(result_id)
    if not packet.get("plan") or review is None or review.recommended_template is None:
        _fail(run_id, store, "review is missing")
    if recommended_template != "threshold_sensitivity" or review.recommended_template.value != recommended_template:
        _fail(run_id, store, "only threshold_sensitivity is allowed as the MVP follow-up")
    result = store.get_result(result_id)
    first = store.get_spec(result.experiment_id) if result else None
    if result is None or first is None or first.template is not Template.FAMILY_SCREEN:
        _fail(run_id, store, "follow-up requires a family_screen initial spec")
    # Host role execution is serial. This read is deliberately before spec/event
    # creation; cross-table reservation is not atomic with method-audit registration.
    if _has_registered_method_audit(path, run_id):
        raise ValueError("threshold follow-up is closed after method-audit registration")
    experiment_id = _id(run_id, "second")
    spec = ExperimentSpec(1, experiment_id, first.hypothesis_id, _active_dataset_sha256(), Split.DISCOVERY, Template.THRESHOLD_SENSITIVITY, ("oxide", "chalcogenide"), "opt", (1.1, 1.8), 0.05, 2000, 1729, 120, result_id, result_id, None)
    store.register_spec(spec)
    store.append_event(run_id, "second_selection", actor="pi", mode=Mode.LIVE, payload_ref=experiment_id)
    return experiment_id


def freeze_final(main_result_id: str, followup_result_id: str, explanation: str = "") -> Dict[str, Any]:
    """Freeze the discovery protocol and derive the sole authorized holdout Spec.

    All protocol parameters are copied from registered Specs.  The caller can only
    identify existing results and provide a short explanation; it cannot supply a
    holdout window, dataset, experiment ID, or protocol hash.
    """
    path, run_id, store = _ctx()
    if not all(isinstance(x, str) and x and "/" not in x and "\\" not in x
               for x in (main_result_id, followup_result_id)):
        _fail(run_id, store, "invalid final protocol references")
    if not isinstance(explanation, str) or len(explanation) > 500 or any(ord(c) < 32 and c not in "\t" for c in explanation):
        _fail(run_id, store, "final explanation is invalid")
    if store.get_final_protocol(run_id) is not None:
        _fail(run_id, store, "final protocol already frozen")

    main = store.get_result(main_result_id)
    followup = store.get_result(followup_result_id)
    if main is None or followup is None or main_result_id == followup_result_id:
        _fail(run_id, store, "final protocol requires two existing results")
    main_spec = store.get_spec(main.experiment_id)
    followup_spec = store.get_spec(followup.experiment_id)
    # Result references must be native to this run, not merely present in a shared DB.
    def owned(spec, result_id):
        return spec is not None and any(e.actor == "pi" and e.payload_ref == spec.experiment_id and
                                        e.event_type in {"selection", "second_selection"}
                                        for e in store.list_events(run_id)) and any(
                                            e.event_type == "result" and e.payload_ref == result_id
                                            for e in store.list_events(run_id))
    if not owned(main_spec, main_result_id) or not owned(followup_spec, followup_result_id):
        _fail(run_id, store, "result belongs to another run")
    if (main.execution_status != "completed" or main.error is not None or
            followup.execution_status != "completed" or followup.error is not None):
        _fail(run_id, store, "final protocol requires successful results")
    if followup_spec.parent_result_id != main_result_id or followup_spec.review_id != main_result_id:
        _fail(run_id, store, "follow-up is not linked to the primary result")
    review = store.get_review(followup_result_id)
    if review is None or review.result_id != followup_result_id:
        _fail(run_id, store, "second review is required before final freeze")
    if not any(e.event_type == "second_review" and e.actor == "skeptic" and e.payload_ref == followup_result_id
               for e in store.list_events(run_id)):
        _fail(run_id, store, "second review event is required before final freeze")

    protocol = {
        "schema_version": 1,
        "hypothesis_id": main_spec.hypothesis_id,
        "dataset_sha256": main_spec.dataset_sha256,
        "main_result_id": main_result_id,
        "followup_result_id": followup_result_id,
        "main_spec": main_spec.to_dict(),
        "followup_spec": followup_spec.to_dict(),
        "review_refs": [main_result_id, followup_result_id],
        "explanation": explanation.strip(),
        "holdout_split": Split.HOLDOUT.value,
        "holdout_template": Template.HOLDOUT_VALIDATION.value,
    }
    canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":"))
    protocol_sha256 = hashlib.sha256(canonical.encode()).hexdigest()
    frozen_id = "NOVA-FINAL-" + protocol_sha256[:16]
    holdout_id = "NOVA-HOLDOUT-" + hashlib.sha256((run_id + ":" + frozen_id).encode()).hexdigest()[:16]
    holdout_spec = ExperimentSpec(
        1, holdout_id, main_spec.hypothesis_id, main_spec.dataset_sha256,
        Split.HOLDOUT, Template.HOLDOUT_VALIDATION, main_spec.groups,
        main_spec.bandgap_method, main_spec.gap_window_ev, main_spec.ehull_max_ev_atom,
        main_spec.bootstrap_repeats, main_spec.seed, main_spec.timeout_seconds,
        followup_result_id, followup_result_id, frozen_id)
    event = Event(run_id, 1, str(uuid.uuid4()), "final_protocol_frozen", "host",
                  datetime.now(timezone.utc).isoformat(), 0, Mode.LIVE, frozen_id)
    store.save_final_protocol(run_id, frozen_id, protocol_sha256, protocol, holdout_spec, event)
    return {"frozen_protocol_id": frozen_id, "protocol_sha256": protocol_sha256,
            "holdout_experiment_id": holdout_id, "protocol": protocol}


def _active_dataset_sha256() -> str:
    from .experiments.executor import active_dataset_sha256
    return active_dataset_sha256()


def _draft(template: str, dataset: str) -> Dict[str, Any]:
    return {"schema_version": 1, "hypothesis_id": "H-001", "dataset_sha256": dataset, "split": "discovery", "template": template, "groups": ["oxide", "chalcogenide"], "bandgap_method": "opt", "gap_window_ev": [1.1, 1.8], "ehull_max_ev_atom": 0.05, "bootstrap_repeats": 2000, "seed": 1729, "timeout_seconds": 120}


def _make_spec(run_id: str, label: str, template: str, dataset: str) -> ExperimentSpec:
    return ExperimentSpec(1, _id(run_id, label), "H-001", dataset, Split.DISCOVERY, Template(template), ("oxide", "chalcogenide"), "opt", (1.1, 1.8), 0.05, 2000, 1729, 120)
