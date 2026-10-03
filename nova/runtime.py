"""Single-process MVP orchestrator for the PI/Planner/Runner/Skeptic loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, List, Dict
from uuid import uuid4

from .tools import RegisteredExperiment, bind_execution_context, execute_registered_experiment


class RunState(str, Enum):
    OBJECTIVE_REGISTERED = "objective_registered"
    HYPOTHESIS_FROZEN = "hypothesis_frozen"
    OPTIONS_REGISTERED = "options_registered"
    EXPERIMENT_SELECTED = "experiment_selected"
    EXPERIMENT_RUNNING = "experiment_running"
    RESULT_READY = "result_ready"
    REVIEW_READY = "review_ready"
    NEXT_SPEC_FROZEN = "next_spec_frozen"
    SECOND_EXPERIMENT_RUNNING = "second_experiment_running"
    SECOND_RESULT_READY = "second_result_ready"
    SECOND_REVIEW_READY = "second_review_ready"
    FAILED = "failed"


@dataclass
class Proposal:
    proposal_id: str
    template: str
    spec: Dict[str, Any]
    estimated_seconds: int = 1
    learning_score: int = 3


@dataclass
class Run:
    objective: str
    experiment_executor: Callable[[Mapping[str, Any]], Any]
    budget_seconds: int = 360
    run_id: str = field(default_factory=lambda: f"run-{uuid4().hex[:12]}")
    state: RunState = RunState.OBJECTIVE_REGISTERED
    proposals: List[Proposal] = field(default_factory=list)
    selected: Optional[Proposal] = None
    results: List[Any] = field(default_factory=list)
    review: Optional[Dict[str, Any]] = None
    spent_seconds: int = 0

    def freeze_hypothesis(self, hypothesis: str = "H1: delta > 0") -> None:
        if self.state is not RunState.OBJECTIVE_REGISTERED:
            raise RuntimeError("hypothesis can only be frozen after objective registration")
        self.hypothesis = hypothesis
        self.state = RunState.HYPOTHESIS_FROZEN

    def register_plan(self, proposals: List[Proposal]) -> List[str]:
        if self.state not in {RunState.HYPOTHESIS_FROZEN, RunState.REVIEW_READY}:
            raise RuntimeError("plan is not allowed in current state")
        if len(proposals) < 2:
            raise ValueError("Planner must expose at least two proposals")
        if any(p.estimated_seconds < 0 for p in proposals):
            raise ValueError("estimated_seconds cannot be negative")
        self.proposals = list(proposals)
        if self.state is RunState.HYPOTHESIS_FROZEN:
            self.state = RunState.OPTIONS_REGISTERED
        return [p.proposal_id for p in proposals]

    def choose(self, proposal_id: str) -> str:
        if self.state not in {RunState.OPTIONS_REGISTERED, RunState.REVIEW_READY}:
            raise RuntimeError("proposal cannot be chosen in current state")
        found = next((p for p in self.proposals if p.proposal_id == proposal_id), None)
        if found is None:
            raise KeyError(proposal_id)
        if self.spent_seconds + found.estimated_seconds > self.budget_seconds:
            raise RuntimeError("budget exhausted")
        self.selected = found
        self.state = RunState.EXPERIMENT_SELECTED if not self.results else RunState.NEXT_SPEC_FROZEN
        return found.proposal_id

    def _execute(self, second: bool = False) -> Any:
        if self.selected is None:
            raise RuntimeError("no selected proposal")
        if second and self.state is not RunState.NEXT_SPEC_FROZEN:
            raise RuntimeError("second experiment requires a frozen next spec")
        if not second and self.state is not RunState.EXPERIMENT_SELECTED:
            raise RuntimeError("initial experiment is not selected")
        mode = self.selected.spec.get("mode", "live")
        registered_spec = dict(self.selected.spec)
        registered_spec["experiment_id"] = self.selected.proposal_id
        entry = RegisteredExperiment(self.selected.proposal_id, registered_spec, mode)
        bind_execution_context(experiments={entry.experiment_id: entry}, experiment_executor=self.experiment_executor, run_id=self.run_id, mode=mode)
        self.state = RunState.SECOND_EXPERIMENT_RUNNING if second else RunState.EXPERIMENT_RUNNING
        result = execute_registered_experiment(entry.experiment_id)
        self.results.append(result)
        self.spent_seconds += int(self.selected.estimated_seconds)
        self.state = RunState.SECOND_RESULT_READY if second else RunState.RESULT_READY
        return result

    def run_first(self) -> Any:
        return self._execute(False)

    def submit_skeptic_review(self, *, concern: str, next_template: str, result_id: Optional[str] = None) -> None:
        if self.state is not RunState.RESULT_READY:
            raise RuntimeError("Skeptic review requires a first result")
        if not concern or not next_template:
            raise ValueError("review requires concern and next_template")
        if result_id is not None:
            latest_result_id = (
                self.results[-1].get("result_id")
                if isinstance(self.results[-1], dict)
                else getattr(self.results[-1], "result_id", None)
            )
            if result_id != latest_result_id:
                raise ValueError("review must reference the latest result")
        self.review = {"concern": concern, "next_template": next_template, "result_id": result_id}
        self.state = RunState.REVIEW_READY

    def run_second(self, proposal_id: str) -> Any:
        if self.state is not RunState.REVIEW_READY or self.review is None:
            raise RuntimeError("second experiment requires Skeptic review")
        previous = self.selected
        candidate = next((p for p in self.proposals if p.proposal_id == proposal_id), None)
        if candidate is None:
            raise KeyError(proposal_id)
        if previous is not None and candidate.template == previous.template:
            raise ValueError("second experiment must use a different template")
        if candidate.template != self.review["next_template"]:
            raise ValueError("second experiment must follow the reviewed next_template")
        self.choose(proposal_id)
        return self._execute(True)


def fixture_executor(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic fixture executor; labels outputs as fixture provenance."""
    return {"result_id": f"fixture-{spec.get('experiment_id', spec.get('template', 'exp'))}", "template": spec.get("template"), "execution_status": "succeeded", "scientific_status": "inconclusive", "mode": "fixture"}
