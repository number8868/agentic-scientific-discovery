"""Durable, single-process adapter around the existing MVP Run state machine."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence
from uuid import uuid4

from .contracts import (Concern, ExperimentSpec, GroupSummary, Mode, ReviewPacket,
                        Result, Template)
from .runtime import Proposal, Run
from .storage import Storage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistentWorkflow:
    """A thin host-owned persistence composition for the two-round MVP.

    The model only supplies proposal/review values.  Actor, run id and mode are
    assigned by this object and every state transition is mirrored as an Event.
    """
    def __init__(self, storage: Storage, objective: str = "", executor: Optional[Callable[[Mapping[str, Any]], Any]] = None,
                 mode: str = "fixture", run_id: Optional[str] = None, budget_seconds: int = 360,
                 experiment_executor: Optional[Callable[[Mapping[str, Any]], Any]] = None):
        if mode not in {m.value for m in Mode}:
            raise ValueError("mode must be live, fixture, or replay")
        if not isinstance(storage, Storage): storage = Storage(storage)
        self.storage = storage.initialize()
        self.run_id = run_id or "run-" + uuid4().hex[:12]
        self.mode = mode
        self.objective = objective
        self._executor = experiment_executor or executor
        if self._executor is None:
            from .fixture_engine import execute
            self._executor = execute
        self.run = Run(objective, self._executor, budget_seconds=budget_seconds, run_id=self.run_id)
        self._specs = {}
        self._record("run_created", "host")

    def _record(self, event_type: str, actor: str, payload_ref: Optional[str] = None):
        if actor not in {"host", "pi", "planner", "runner", "skeptic"}:
            raise ValueError("invalid workflow actor")
        return self.storage.append_event(self.run_id, event_type, actor=actor, mode=self.mode, payload_ref=payload_ref)

    def _fail(self, exc: Exception):
        kind = "schema_failed" if isinstance(exc, (TypeError, ValueError, KeyError)) else "tool_failed"
        self._record(kind, "host", str(exc)[:500])
        raise exc

    def freeze_hypothesis(self, hypothesis: str = "H1: delta > 0"):
        try:
            self.run.freeze_hypothesis(hypothesis)
            return self._record("hypothesis_frozen", "pi")
        except Exception as exc:
            return self._fail(exc)

    @staticmethod
    def _proposal(value: Any) -> Proposal:
        if isinstance(value, Proposal): return value
        if not isinstance(value, Mapping): raise TypeError("proposal must be Proposal or mapping")
        return Proposal(str(value["proposal_id"]), str(value.get("template", value["spec"].get("template"))),
                        dict(value["spec"]), int(value.get("estimated_seconds", 1)), int(value.get("learning_score", 3)))

    def register_plan(self, proposals: Sequence[Any]):
        try:
            result = self.run.register_plan([self._proposal(p) for p in proposals])
            self._record("plan_registered", "planner")
            return result
        except Exception as exc:
            return self._fail(exc)

    def _canonical_spec(self, proposal: Proposal) -> ExperimentSpec:
        raw = dict(proposal.spec)
        if raw.get("mode", self.mode) != self.mode:
            raise ValueError("proposal mode does not match workflow mode")
        raw.pop("mode", None); raw.pop("run_id", None)
        raw.setdefault("schema_version", 1)
        raw.setdefault("experiment_id", proposal.proposal_id)
        raw.setdefault("hypothesis_id", getattr(self.run, "hypothesis", "H1"))
        if self.mode == "fixture":
            raw.setdefault("dataset_sha256", "fixture-demo-v1")
        elif not raw.get("dataset_sha256"):
            raise ValueError("live/replay proposals require an explicit dataset_sha256")
        raw.setdefault("split", "discovery")
        raw.setdefault("template", proposal.template)
        raw.setdefault("groups", ("oxide", "chalcogenide"))
        raw.setdefault("bandgap_method", "opt")
        raw.setdefault("gap_window_ev", (1.1, 1.8))
        raw.setdefault("ehull_max_ev_atom", 0.05)
        raw.setdefault("bootstrap_repeats", 200)
        raw.setdefault("seed", 1729)
        raw.setdefault("timeout_seconds", 120)
        return ExperimentSpec.from_dict(raw)

    def select(self, proposal_id: str):
        try:
            value = self.run.choose(proposal_id)
            proposal = self.run.selected
            spec = self._canonical_spec(proposal)
            self.storage.register_spec(spec); self._specs[proposal_id] = spec
            self._record("second_selection" if self.run.results else "selection", "pi", proposal_id)
            return value
        except Exception as exc:
            return self._fail(exc)

    def _to_result(self, value: Any, spec: ExperimentSpec) -> Result:
        if isinstance(value, Result): return value
        data = value.to_dict() if hasattr(value, "to_dict") else dict(value)
        summaries = []
        raw_groups = data.get("groups_summary") or {}
        if isinstance(raw_groups, Mapping):
            raw_groups = tuple(dict(item, group=group) for group, item in raw_groups.items())
        for index, item in enumerate(raw_groups):
            item = dict(item)
            item.setdefault("group", "group-%d" % index)
            summaries.append(GroupSummary.from_dict(item))
        status = data.get("execution_status", "completed")
        scientific = data.get("scientific_status")
        if status in {"failed", "timeout"}: scientific = None
        return Result(result_id=str(data["result_id"]), experiment_id=spec.experiment_id,
                      spec_sha256=spec.sha256, dataset_sha256=spec.dataset_sha256,
                      execution_status=status, scientific_status=scientific,
                      started_at=str(data.get("started_at", _now())), finished_at=str(data.get("finished_at", _now())),
                      elapsed_seconds=float(data.get("elapsed_seconds", 0)), groups_summary=tuple(summaries),
                      delta=data.get("delta"), resampling_interval=data.get("resampling_interval"),
                      missingness_interval=data.get("missingness_interval"),
                      quality_flags=tuple(data.get("quality_flags", ("fixture",) if self.mode == "fixture" else ())),
                      artifact_ids=tuple(data.get("artifact_ids", ())), error=data.get("error"))

    def _run(self, second: bool = False, proposal_id: Optional[str] = None):
        try:
            self._record("running", "runner")
            value = self.run.run_second(proposal_id or self.run.selected.proposal_id) if second else self.run.run_first()
            spec = self._specs[self.run.selected.proposal_id]
            result = self._to_result(value, spec)
            self.storage.save_result(result)
            self._record("second_result" if second else "result", "runner", result.result_id)
            return result
        except Exception as exc:
            return self._fail(exc)

    def run_first(self): return self._run(False)

    select_proposal = select

    def submit_review(self, concern: str, next_template: str, result_id: Optional[str] = None):
        try:
            latest = self.run.results[-1]
            rid = result_id or getattr(latest, "result_id", None) or (latest.get("result_id") if isinstance(latest, dict) else None)
            self.run.submit_skeptic_review(concern=concern, next_template=next_template, result_id=rid)
            packet = ReviewPacket(self.run.selected.proposal_id, rid,
                                  (Concern("scientific", "medium", (rid,)),), Template(next_template), concern, (rid,))
            self.storage.save_review(packet); self._record("review", "skeptic", rid)
            return packet
        except Exception as exc:
            return self._fail(exc)

    submit_skeptic_review = submit_review

    def run_second(self, proposal_id: str):
        try:
            proposal = next(p for p in self.run.proposals if p.proposal_id == proposal_id)
            if self.run.review is None:
                raise RuntimeError("second experiment requires Skeptic review")
            if self.run.selected is not None and proposal.template == self.run.selected.template:
                raise ValueError("second experiment must use a different template")
            if proposal.template != self.run.review["next_template"]:
                raise ValueError("second experiment must follow the reviewed next_template")
            spec = self._canonical_spec(proposal); self.storage.register_spec(spec); self._specs[proposal_id] = spec
            self._record("second_selection", "pi", proposal_id)
        except Exception as exc:
            return self._fail(exc)
        return self._run(True, proposal_id)
