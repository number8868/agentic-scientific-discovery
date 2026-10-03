"""Strict B-to-A adapter for the registered live science executor."""
from __future__ import annotations
from dataclasses import fields
from typing import Any, Mapping
from .contracts import ExperimentSpec, Result, Template
class _LazyExecutor:
    def execute(self, payload):
        from .experiments import executor
        return executor.execute(payload)

science_executor = _LazyExecutor()

_CONTRACT_FIELDS = frozenset(field.name for field in fields(ExperimentSpec))
_HOST_FIELDS = frozenset({"mode", "run_id"})
_FORBIDDEN = frozenset({"path", "dataset_path", "data_path", "cache_dir", "callable", "executor", "module"})

def _input(value: Any):
    if isinstance(value, ExperimentSpec):
        data = value.to_dict(); data["mode"] = "live"
        return value, data
    if not isinstance(value, Mapping): raise TypeError("spec must be an ExperimentSpec or mapping")
    if _FORBIDDEN.intersection(value): raise ValueError("paths and callables are not accepted by the science adapter")
    unknown = set(value) - _CONTRACT_FIELDS - _HOST_FIELDS
    if unknown: raise ValueError("unknown science executor fields")
    if value.get("mode") != "live": raise ValueError("science adapter accepts live mode only")
    contract_data = {key: value[key] for key in value if key in _CONTRACT_FIELDS}
    return ExperimentSpec.from_dict(contract_data), dict(value)

def execute_science_experiment(spec: Any) -> Result:
    """Execute a registered live family or threshold science experiment."""
    contract, payload = _input(spec)
    if contract.template not in {Template.FAMILY_SCREEN, Template.THRESHOLD_SENSITIVITY}:
        raise ValueError("only family_screen and threshold_sensitivity are supported")
    if contract.split.value != "discovery": raise ValueError("science executor currently supports discovery only")
    payload["mode"] = "live"
    result = science_executor.execute(payload)
    if not isinstance(result, Result): raise TypeError("science executor must return canonical Result")
    if result.experiment_id != contract.experiment_id: raise ValueError("science result experiment_id does not match registered spec")
    if result.spec_sha256 != contract.sha256: raise ValueError("science result spec_sha256 does not match registered spec")
    if result.dataset_sha256 != contract.dataset_sha256: raise ValueError("science result dataset_sha256 does not match registered spec")
    if result.execution_status != "completed" or result.scientific_status is None:
        raise ValueError("science executor returned an invalid completed result")
    return result

__all__ = ["execute_science_experiment"]
