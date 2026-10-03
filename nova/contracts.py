"""Version-one, JSON serialisable records shared by the prototype agents."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import Enum
import hashlib
import json
import math
from typing import Any, ClassVar, Mapping, TypeVar, Optional, Union

SCHEMA_VERSION = 1
_T = TypeVar("_T")

class _StrEnum(str, Enum):
    def __str__(self) -> str: return self.value

class Split(_StrEnum):
    DISCOVERY = "discovery"
    HOLDOUT = "holdout"

class Template(_StrEnum):
    FAMILY_SCREEN = "family_screen"
    THRESHOLD_SENSITIVITY = "threshold_sensitivity"
    GAP_WINDOW_SENSITIVITY = "gap_window_sensitivity"
    HOLDOUT_VALIDATION = "holdout_validation"

class Mode(_StrEnum):
    LIVE = "live"
    FIXTURE = "fixture"
    REPLAY = "replay"

def _finite(x: Any, name: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        raise ValueError(f"{name} must be finite")
    return float(x)

def _unknown(d: Mapping[str, Any], cls: type) -> None:
    allowed = {f.name for f in fields(cls)}
    unknown = set(d) - allowed
    if unknown: raise ValueError(f"unknown fields for {cls.__name__}: {sorted(unknown)}")

def _enum(v: Any, typ: type[Enum], name: str):
    try: return v if isinstance(v, typ) else typ(v)
    except (ValueError, TypeError): raise ValueError(f"invalid {name}: {v!r}") from None

class Contract:
    def to_dict(self) -> dict[str, Any]:
        def conv(v):
            if isinstance(v, Enum): return v.value
            if isinstance(v, Contract): return v.to_dict()
            if isinstance(v, tuple): return [conv(x) for x in v]
            if isinstance(v, list): return [conv(x) for x in v]
            if isinstance(v, dict): return {k: conv(x) for k,x in v.items()}
            return v
        return conv(asdict(self))
    def to_json(self) -> str: return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

@dataclass(frozen=True)
class ExperimentSpec(Contract):
    schema_version: int
    experiment_id: str
    hypothesis_id: str
    dataset_sha256: str
    split: Split
    template: Template
    groups: tuple[str, ...]
    bandgap_method: str
    gap_window_ev: tuple[float, float]
    ehull_max_ev_atom: float
    bootstrap_repeats: int
    seed: int
    timeout_seconds: int
    parent_result_id: Optional[str] = None
    review_id: Optional[str] = None
    frozen_protocol_id: Optional[str] = None

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION: raise ValueError("schema_version must be 1")
        for n in ("experiment_id", "hypothesis_id", "dataset_sha256", "bandgap_method"):
            if not isinstance(getattr(self,n), str) or not getattr(self,n): raise ValueError(f"{n} must be non-empty")
        object.__setattr__(self, "split", _enum(self.split, Split, "split"))
        object.__setattr__(self, "template", _enum(self.template, Template, "template"))
        if not self.groups or any(not isinstance(x,str) or not x for x in self.groups): raise ValueError("groups must be non-empty strings")
        if len(self.gap_window_ev) != 2: raise ValueError("gap_window_ev must have two values")
        lo, hi = map(lambda x: _finite(x, "gap_window_ev"), self.gap_window_ev)
        if lo >= hi: raise ValueError("gap window lower bound must be below upper bound")
        object.__setattr__(self, "gap_window_ev", (lo, hi))
        eh = _finite(self.ehull_max_ev_atom, "ehull_max_ev_atom")
        if eh < 0: raise ValueError("ehull threshold cannot be negative")
        object.__setattr__(self, "ehull_max_ev_atom", eh)
        if isinstance(self.bootstrap_repeats,bool) or not isinstance(self.bootstrap_repeats,int) or self.bootstrap_repeats < 0: raise ValueError("invalid bootstrap_repeats")
        if isinstance(self.timeout_seconds,bool) or not isinstance(self.timeout_seconds,int) or self.timeout_seconds <= 0: raise ValueError("timeout_seconds must be positive")
        if self.template is Template.HOLDOUT_VALIDATION and not self.frozen_protocol_id: raise ValueError("holdout_validation requires frozen_protocol_id")

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]):
        _unknown(d, cls)
        x = dict(d)
        x["split"] = _enum(x["split"], Split, "split"); x["template"] = _enum(x["template"], Template, "template")
        x["groups"] = tuple(x["groups"]); x["gap_window_ev"] = tuple(x["gap_window_ev"])
        return cls(**x)
    @property
    def sha256(self) -> str: return hashlib.sha256(self.to_json().encode()).hexdigest()

@dataclass(frozen=True)
class GroupSummary(Contract):
    group: str
    n_total: int
    n_observed: int
    n_pass: int
    coverage: Optional[float]
    observed_rate: Optional[float]
    missing_lower: Optional[float]
    missing_upper: Optional[float]

    def __post_init__(self):
        if self.n_total < 0 or self.n_observed < 0 or self.n_pass < 0 or self.n_observed > self.n_total or self.n_pass > self.n_observed: raise ValueError("invalid group counts")
        for n in ("coverage","observed_rate","missing_lower","missing_upper"):
            v=getattr(self,n)
            if v is not None and not 0 <= _finite(v,n) <= 1: raise ValueError(f"{n} must be between 0 and 1")
    @classmethod
    def from_dict(cls,d): _unknown(d,cls); return cls(**d)

@dataclass(frozen=True)
class Result(Contract):
    result_id: str; experiment_id: str; spec_sha256: str; dataset_sha256: str
    execution_status: str; scientific_status: Optional[str]; started_at: str; finished_at: str
    elapsed_seconds: float; groups_summary: tuple = (); delta: Optional[float] = None
    resampling_interval: Optional[tuple] = None; missingness_interval: Optional[tuple] = None
    quality_flags: tuple = (); artifact_ids: tuple = (); error: Optional[Mapping[str,Any]] = None
    def __post_init__(self):
        if self.elapsed_seconds < 0: raise ValueError("elapsed_seconds cannot be negative")
        if self.delta is not None and not -1 <= _finite(self.delta,"delta") <= 1: raise ValueError("delta must be between -1 and 1")
        if self.execution_status in ("timeout","failed") and self.scientific_status is not None: raise ValueError("failed result has null scientific_status")
    @classmethod
    def from_dict(cls,d):
        _unknown(d,cls); x=dict(d); x["groups_summary"]=tuple(GroupSummary.from_dict(v) if not isinstance(v,GroupSummary) else v for v in x.get("groups_summary",()))
        for k in ("resampling_interval","missingness_interval"): x[k]=tuple(x[k]) if x.get(k) is not None else None
        for k in ("quality_flags","artifact_ids"): x[k]=tuple(x.get(k,()))
        return cls(**x)

@dataclass(frozen=True)
class PlanProposal(Contract):
    proposal_id: str; draft_spec: Mapping[str,Any]; feasibility: bool; estimated_seconds: float; learning_score: int; score_reason: str
    @classmethod
    def from_dict(cls,d): _unknown(d,cls); return cls(**d)
@dataclass(frozen=True)
class PlanPacket(Contract):
    hypothesis_id: str; candidate_tests: tuple[PlanProposal,...]; chosen_proposal_id: str; selection_reason: str
    @classmethod
    def from_dict(cls,d): _unknown(d,cls); x=dict(d); x["candidate_tests"]=tuple(PlanProposal.from_dict(v) for v in x["candidate_tests"]); return cls(**x)
@dataclass(frozen=True)
class Concern(Contract):
    concern_type: str; severity: str; evidence_refs: tuple[str,...]
    @classmethod
    def from_dict(cls,d): _unknown(d,cls); x=dict(d); x["evidence_refs"]=tuple(x["evidence_refs"]); return cls(**x)
@dataclass(frozen=True)
class ReviewPacket(Contract):
    experiment_id: str; result_id: str; concerns: tuple; recommended_template: Optional[Template]; reason: str; claim_refs: tuple
    @classmethod
    def from_dict(cls,d): _unknown(d,cls); x=dict(d); x["concerns"]=tuple(Concern.from_dict(v) for v in x["concerns"]); x["claim_refs"]=tuple(x["claim_refs"]); x["recommended_template"]=_enum(x["recommended_template"],Template,"template") if x.get("recommended_template") else None; return cls(**x)
@dataclass(frozen=True)
class Event(Contract):
    run_id: str; seq: int; event_id: str; event_type: str; actor: str; timestamp_utc: str; attempt: int; mode: Mode; payload_ref: Optional[str] = None
    def __post_init__(self):
        object.__setattr__(self,"mode",_enum(self.mode,Mode,"mode"))
        if self.seq < 1 or self.attempt < 0: raise ValueError("invalid event sequence/attempt")
    @classmethod
    def from_dict(cls,d): _unknown(d,cls); return cls(**d)
