"""Durable bookkeeping and descriptive summaries for the parallel self-test.

This module contains no model or science calls. It deliberately distinguishes
observed completion time, deadline-penalized time, and structured grading
proxies; it does not perform the pending blind prose adjudication.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import tempfile
from typing import Any, Callable, Mapping
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
ARMS = ("single_self_review", "parallel_review")
MAX_TURNS_PER_ARM = 3
REPETITIONS = 2
DEADLINE_SECONDS = 150.0
BOOTSTRAP_REPEATS = 10_000
BOOTSTRAP_SEED = 1729
_SECRETISH = re.compile(r"(?i)\b(?:bearer\s+|sk-|rk-|gh[pousr]_|xox[baprs]-)[A-Za-z0-9._-]{12,}")


class BudgetExhausted(RuntimeError):
    """Raised before dispatch when the durable SDK-turn budget is spent."""


def safe_text(value: Any, limit: int = 4000) -> str:
    return _SECRETISH.sub("[redacted]", str(value)).replace("\x00", "")[:limit]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                        allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).rstrip(b"\n"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_run_directory(requested: str | Path | None = None) -> Path:
    """Create a new private run directory under runs/, never reuse an output."""
    RUNS.mkdir(mode=0o700, parents=True, exist_ok=True)
    if RUNS.is_symlink():
        raise ValueError("runs directory may not be a symlink")
    if requested is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = RUNS / f"parallel-selftest-{stamp}-{uuid.uuid4().hex[:8]}"
    else:
        path = Path(requested)
        if not path.is_absolute():
            path = ROOT / path
    cursor = path.parent
    while cursor != cursor.parent:
        if cursor.exists() and cursor.is_symlink():
            raise ValueError("output path may not traverse a symlink")
        if cursor == ROOT:
            break
        cursor = cursor.parent
    try:
        path.parent.resolve().relative_to(RUNS.resolve())
    except ValueError as exc:
        raise ValueError("parallel self-test output must be under runs/") from exc
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.mkdir(mode=0o700, exist_ok=False)
    _fsync_directory(path.parent)
    return path.resolve()


class DurableRunStore:
    """Append-only fsynced journal plus atomic, directory-fsynced checkpoint."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.journal_path = run_dir / "events.jsonl"
        self.checkpoint_path = run_dir / "report.json"
        self._fd = os.open(self.journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        _fsync_directory(run_dir)
        self.sequence = 0

    def append(self, event: str, payload: Mapping[str, Any]) -> None:
        record = {"seq": self.sequence + 1, "event": event,
                  "at_utc": datetime.now(timezone.utc).isoformat(), **dict(payload)}
        data = canonical_json(record)
        view = memoryview(data)
        while view:
            count = os.write(self._fd, view)
            if count <= 0:
                raise OSError("short journal write")
            view = view[count:]
        os.fsync(self._fd)
        self.sequence += 1

    def checkpoint(self, report: Mapping[str, Any]) -> None:
        data = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2,
                          allow_nan=False).encode("utf-8") + b"\n"
        fd, temp_name = tempfile.mkstemp(prefix=".report-", suffix=".tmp", dir=self.run_dir)
        temp_path = Path(temp_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.checkpoint_path)
            _fsync_directory(self.run_dir)
        except BaseException:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def close(self) -> None:
        if self._fd is not None:
            os.fsync(self._fd)
            os.close(self._fd)
            self._fd = None  # type: ignore[assignment]

    @staticmethod
    def read_journal(path: Path) -> list[dict[str, Any]]:
        """Strictly parse a complete journal; partial final records fail closed."""
        records: list[dict[str, Any]] = []
        with path.open("rb") as stream:
            for expected, raw in enumerate(stream, 1):
                if not raw.endswith(b"\n"):
                    raise ValueError("journal has a partial record")
                item = json.loads(raw)
                if not isinstance(item, dict) or item.get("seq") != expected:
                    raise ValueError("journal sequence is invalid")
                records.append(item)
        return records


class AtomicTurnBudget:
    """Parent-owned budget, reserved durably before each SDK dispatch."""

    def __init__(self, limit: int, store: DurableRunStore, report: dict[str, Any]):
        if isinstance(limit, bool) or limit < 0:
            raise ValueError("turn budget must be a nonnegative integer")
        self.limit = int(limit)
        self.used = 0
        self.store = store
        self.report = report
        self._lock = asyncio.Lock()
        self._roles_by_slot: set[tuple[str, int, str]] = set()
        self.failed = False
        self._expected_roles = {
            "single_self_review": {"draft", "critique", "final"},
            "parallel_review": {"planner", "skeptic", "pi"},
        }

    async def before_dispatch(self, *, packet_id: str, repetition: int, arm: str,
                              role: str | None = None) -> int:
        async with self._lock:
            if self.failed:
                raise BudgetExhausted("durable parent budget/journal failed closed")
            key = (packet_id, repetition, arm)
            if arm not in self._expected_roles or role not in self._expected_roles[arm]:
                raise ValueError("unexpected SDK role for arm")
            role_key = (*key, role)
            if role_key in self._roles_by_slot:
                raise BudgetExhausted("SDK role slot already reserved; retry is forbidden")
            reserved_for_arm = sum(1 for item in self._roles_by_slot if item[:3] == key)
            if reserved_for_arm >= MAX_TURNS_PER_ARM:
                raise BudgetExhausted("per-arm three-turn budget exhausted")
            if self.used >= self.limit:
                raise BudgetExhausted("durable SDK-turn budget exhausted")
            next_used = self.used + 1
            # This fsynced event is the reservation. A crash afterwards keeps
            # the turn charged; no automatic recovery/retry is permitted.
            try:
                self.store.append("sdk_turn_reserved", {
                    "dispatch_number": next_used, "packet_id": packet_id,
                    "repetition": repetition, "arm": arm, "role": role,
                    "budget_limit": self.limit,
                })
                self.used = next_used
                self._roles_by_slot.add(role_key)
                self.report["sdk_turns_reserved"] = self.used
                self.store.checkpoint(self.report)
            except BaseException:
                self.failed = True
                raise
            return next_used


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    ix = round((len(sorted_values) - 1) * p)
    return sorted_values[ix]


def _aggregate_cases(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Reduce repeated arm rows to one paired row per packet."""
    corpus_cases = report.get("cases", [])
    groups = report.get("groups", [])
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    for group in groups:
        by_id.setdefault(str(group.get("case_id")), []).append(group)
    rows: list[dict[str, Any]] = []
    for case in corpus_cases:
        cid = str(case["id"])
        repetitions = by_id.get(cid, [])
        expected_repetitions = int(report.get("repetitions", REPETITIONS))
        rep_numbers = [group.get("repetition") for group in repetitions]
        row: dict[str, Any] = {"case_id": cid, "family": case["family"],
                               "pair_id": case["pair_id"], "variants": case["variant"],
                               "complete": len(repetitions) == expected_repetitions
                               and len(set(rep_numbers)) == expected_repetitions
                               and set(rep_numbers) == set(range(1, expected_repetitions + 1))}
        arm_values: dict[str, dict[str, list[float]]] = {
            arm: {"penalty": [], "observed": [], "utility": []} for arm in ARMS
        }
        for group in repetitions:
            for arm in ARMS:
                result = group.get("arms", {}).get(arm)
                if not isinstance(result, Mapping):
                    row["complete"] = False
                    continue
                if result.get("status") == "not_started":
                    row["complete"] = False
                    continue
                penalty = finite_number(result.get("deadline_penalty_seconds"))
                if penalty is not None:
                    arm_values[arm]["penalty"].append(penalty)
                observed = finite_number(result.get("observed_delivery_seconds"))
                if observed is not None and result.get("delivery_valid") is True:
                    arm_values[arm]["observed"].append(observed)
                utility = finite_number(result.get("structured_delivery_utility"))
                if utility is not None:
                    arm_values[arm]["utility"].append(utility)
        for arm in ARMS:
            vals = arm_values[arm]
            row[f"C_{arm}"] = sum(vals["penalty"]) / len(vals["penalty"]) if len(vals["penalty"]) == expected_repetitions else None
            row[f"T_{arm}"] = sum(vals["observed"]) / len(vals["observed"]) if len(vals["observed"]) == expected_repetitions else None
            row[f"U_{arm}"] = sum(vals["utility"]) / len(vals["utility"]) if len(vals["utility"]) == expected_repetitions else None
        row["pair_complete"] = row["complete"] and all(
            row[f"C_{arm}"] is not None and row[f"U_{arm}"] is not None for arm in ARMS
        )
        if row["pair_complete"]:
            single = row[f"C_{ARMS[0]}"]
            parallel = row[f"C_{ARMS[1]}"]
            row["relative_time_gain"] = (single - parallel) / single if single > 0 else None
            row["structured_utility_delta"] = row[f"U_{ARMS[1]}"] - row[f"U_{ARMS[0]}"]
        else:
            row["relative_time_gain"] = None
            row["structured_utility_delta"] = None
        rows.append(row)
    return rows


def stratified_pair_bootstrap(rows: list[Mapping[str, Any]], *, repeats: int = BOOTSTRAP_REPEATS,
                              seed: int = BOOTSTRAP_SEED, approved: bool) -> dict[str, Any] | None:
    """Descriptive family-stratified resampling, only after pair-dependence approval."""
    if not approved or not rows or any(not row.get("pair_complete") for row in rows):
        return None
    by_family: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    for row in rows:
        by_family.setdefault(str(row["family"]), {}).setdefault(str(row["pair_id"]), []).append(row)
    if len(by_family) != 6 or any(len(pairs) != 2 for pairs in by_family.values()):
        return None
    if any(len(members) != 2 or len({m.get("variants") for m in members}) != 2
           for pairs in by_family.values() for members in pairs.values()):
        return None
    rng = random.Random(seed)
    time_dist: list[float] = []
    utility_dist: list[float] = []
    family_names = sorted(by_family)
    for _ in range(repeats):
        sampled: list[Mapping[str, Any]] = []
        for family in family_names:
            pairs = by_family[family]
            pair_ids = sorted(pairs)
            chosen = [rng.choice(pair_ids) for _ in pair_ids]
            for pair_id in chosen:
                sampled.extend(pairs[pair_id])
        time_values = [float(row["relative_time_gain"]) for row in sampled]
        utility_values = [float(row["structured_utility_delta"]) for row in sampled]
        time_dist.append(sorted(time_values)[len(time_values) // 2] if len(time_values) % 2 else
                         (sorted(time_values)[len(time_values)//2 - 1] + sorted(time_values)[len(time_values)//2]) / 2)
        utility_dist.append(sum(utility_values) / len(utility_values))
    time_dist.sort()
    utility_dist.sort()
    return {
        "method": "descriptive_family_stratified_pair_resampling",
        "lower": {"relative_time_gain_median": _percentile(time_dist, .025),
                  "structured_utility_delta_mean": _percentile(utility_dist, .025)},
        "upper": {"relative_time_gain_median": _percentile(time_dist, .975),
                  "structured_utility_delta_mean": _percentile(utility_dist, .975)},
        "repeats": repeats, "seed": seed, "families": len(by_family),
        "pair_clusters_per_family": 2, "scope": "fixed_convenience_set_only",
        "inference": False,
    }


def summarize_report(report: dict[str, Any], *, dependency_audit_approved: bool) -> dict[str, Any]:
    rows = _aggregate_cases(report)
    report["case_summaries"] = rows
    complete = [row for row in rows if row.get("pair_complete")]
    attempted = sum(1 for group in report.get("groups", [])
                    if any(arm.get("status") != "not_started" for arm in group.get("arms", {}).values()))
    report["summary"] = {
        "cases_planned": len(rows), "paired_cases_complete": len(complete),
        "groups_attempted": attempted, "dependency_audit_approved": dependency_audit_approved,
        "blind_prose_review_status": "pending", "full_semantic_quality": None,
        "full_delivery_utility_delta": None,
        "structured_proxy_only": True,
        "all_planned_rows_complete": len(complete) == len(rows),
        "safety_claim": "pending_independent_content_review",
    }
    if report.get("stage") == "development":
        report["summary"].update({"structured_time_gain_median": None,
                                  "structured_utility_delta_mean": None,
                                  "primary_effect": None,
                                  "screening_status": "development_pipeline_only"})
        report["summary"]["descriptive_interval"] = None
        return report["summary"]
    if complete:
        gains = sorted(float(row["relative_time_gain"]) for row in complete)
        deltas = [float(row["structured_utility_delta"]) for row in complete]
        report["summary"]["structured_time_gain_median"] = (
            gains[len(gains)//2] if len(gains) % 2 else (gains[len(gains)//2-1] + gains[len(gains)//2]) / 2
        )
        report["summary"]["structured_utility_delta_mean"] = sum(deltas) / len(deltas)
    else:
        report["summary"]["structured_time_gain_median"] = None
        report["summary"]["structured_utility_delta_mean"] = None
    ci = stratified_pair_bootstrap(rows, approved=dependency_audit_approved)
    report["summary"]["descriptive_interval"] = ci
    no_failures = all(group.get("status") == "completed" for group in report.get("groups", []))
    can_screen = (dependency_audit_approved and ci is not None and len(complete) == len(rows)
                  and no_failures)
    report["summary"]["screening_status"] = "pending_blind_review" if can_screen else "incomplete_or_unapproved"
    return report["summary"]
