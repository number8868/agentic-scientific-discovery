"""Narrow, host-bound tools exposed to the Runner agent.

The registry is deliberately in-process for the MVP.  A production adapter can
replace ``bind_execution_context`` with the storage-backed implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Dict


@dataclass(frozen=True)
class RegisteredExperiment:
    experiment_id: str
    spec: Mapping[str, Any]
    mode: str = "live"  # live, fixture, or replay


_registry = {}  # type: Dict[str, RegisteredExperiment]
_executor = None  # type: Optional[Callable[[Mapping[str, Any]], Any]]
_context = {}  # type: Dict[str, Any]


def bind_execution_context(
    *,
    experiments: Mapping[str, RegisteredExperiment],
    experiment_executor: Callable[[Mapping[str, Any]], Any],
    run_id: str,
    mode: str = "live",
) -> None:
    """Bind trusted host state; model/tool arguments cannot alter this state."""
    if mode not in {"live", "fixture", "replay"}:
        raise ValueError("mode must be live, fixture, or replay")
    if not callable(experiment_executor):
        raise TypeError("experiment_executor must be callable")
    _registry.clear()
    _registry.update(experiments)
    _context.clear()
    _context.update({"run_id": run_id, "mode": mode})
    global _executor
    _executor = experiment_executor


def register_experiment(experiment: RegisteredExperiment) -> None:
    if not experiment.experiment_id or experiment.experiment_id in _registry:
        raise ValueError("experiment_id must be unique and non-empty")
    if experiment.mode not in {"live", "fixture", "replay"}:
        raise ValueError("invalid experiment mode")
    _registry[experiment.experiment_id] = experiment


def execute_registered_experiment(experiment_id: str) -> Any:
    """Execute one pre-registered spec.  No code/path/spec is accepted here."""
    if not isinstance(experiment_id, str) or experiment_id not in _registry:
        raise PermissionError("only a registered experiment_id may be executed")
    if _executor is None:
        raise RuntimeError("execution context is not bound")
    entry = _registry[experiment_id]
    result = _executor(entry.spec)
    # Preserve provenance for consumers that return plain dicts or objects.
    if isinstance(result, dict):
        result.setdefault("experiment_id", experiment_id)
        result.setdefault("mode", entry.mode)
        result.setdefault("run_id", _context.get("run_id"))
    return result
