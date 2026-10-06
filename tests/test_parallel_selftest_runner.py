from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pytest

from nova import benchmark_parallel_report as reportlib
from scripts import run_parallel_selftest as runner


def _fixture_store(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return reportlib.DurableRunStore(run_dir)


def test_finite_number_rejects_nonfinite_and_huge_ints():
    assert reportlib.finite_number(1.5) == 1.5
    assert reportlib.finite_number(float("nan")) is None
    assert reportlib.finite_number(float("inf")) is None
    assert reportlib.finite_number(10**10000) is None
    assert reportlib.finite_number(True) is None


def test_journal_reservation_is_durable_before_dispatch_and_duplicate_fails(tmp_path):
    store = _fixture_store(tmp_path)
    state = {"sdk_turns_reserved": 0}
    budget = reportlib.AtomicTurnBudget(3, store, state)

    async def exercise():
        assert await budget.before_dispatch(packet_id="x", repetition=1,
                                           arm="single_self_review", role="draft") == 1
        with pytest.raises(reportlib.BudgetExhausted):
            await budget.before_dispatch(packet_id="x", repetition=1,
                                         arm="single_self_review", role="draft")
        assert await budget.before_dispatch(packet_id="x", repetition=1,
                                           arm="single_self_review", role="critique") == 2
        assert await budget.before_dispatch(packet_id="x", repetition=1,
                                           arm="single_self_review", role="final") == 3
        with pytest.raises(reportlib.BudgetExhausted):
            await budget.before_dispatch(packet_id="x", repetition=1,
                                         arm="single_self_review", role="final")

    asyncio.run(exercise())
    records = store.read_journal(store.journal_path)
    assert [row["event"] for row in records] == ["sdk_turn_reserved"] * 3
    assert state["sdk_turns_reserved"] == 3
    store.close()


def test_budget_checkpoint_failure_fails_closed(tmp_path, monkeypatch):
    store = _fixture_store(tmp_path)
    state = {"sdk_turns_reserved": 0}
    budget = reportlib.AtomicTurnBudget(3, store, state)

    def fail(_):
        raise OSError("injected checkpoint failure")

    monkeypatch.setattr(store, "checkpoint", fail)

    async def exercise():
        with pytest.raises(OSError):
            await budget.before_dispatch(packet_id="x", repetition=1,
                                         arm="single_self_review", role="draft")
        with pytest.raises(reportlib.BudgetExhausted):
            await budget.before_dispatch(packet_id="x", repetition=1,
                                         arm="single_self_review", role="critique")

    asyncio.run(exercise())
    assert budget.used == 1  # the fsynced reservation remains charged
    assert len(store.read_journal(store.journal_path)) == 1
    store.close()


def test_parallel_initial_roles_reserve_atomically_under_concurrency(tmp_path):
    store = _fixture_store(tmp_path)
    state = {"sdk_turns_reserved": 0}
    budget = reportlib.AtomicTurnBudget(3, store, state)

    async def exercise():
        return await asyncio.gather(
            budget.before_dispatch(packet_id="x", repetition=1,
                                   arm="parallel_review", role="planner"),
            budget.before_dispatch(packet_id="x", repetition=1,
                                   arm="parallel_review", role="skeptic"),
        )

    numbers = asyncio.run(exercise())
    assert sorted(numbers) == [1, 2]
    records = store.read_journal(store.journal_path)
    assert {row["role"] for row in records} == {"planner", "skeptic"}
    with pytest.raises(reportlib.BudgetExhausted):
        asyncio.run(budget.before_dispatch(packet_id="x", repetition=1,
                                           arm="parallel_review", role="skeptic"))
    store.close()


def test_atomic_checkpoint_keeps_valid_old_or_new_report(tmp_path, monkeypatch):
    store = _fixture_store(tmp_path)
    store.checkpoint({"version": 1})
    original_replace = reportlib.os.replace

    def fail_replace(src, dst):
        raise OSError("injected crash before atomic rename")

    monkeypatch.setattr(reportlib.os, "replace", fail_replace)
    with pytest.raises(OSError):
        store.checkpoint({"version": 2})
    monkeypatch.setattr(reportlib.os, "replace", original_replace)
    assert json.loads(store.checkpoint_path.read_text()) == {"version": 1}
    store.checkpoint({"version": 3})
    assert json.loads(store.checkpoint_path.read_text()) == {"version": 3}
    store.close()


@pytest.mark.parametrize("fault", ["write", "file_fsync", "rename", "directory_fsync"])
def test_checkpoint_faults_leave_old_or_new_valid_json(tmp_path, monkeypatch, fault):
    store = _fixture_store(tmp_path)
    store.checkpoint({"version": 1})
    if fault == "write":
        original_fdopen = reportlib.os.fdopen

        class BrokenStream:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def write(self, _data):
                raise OSError("injected file write failure")
            def flush(self):
                return self.stream.flush()
            def fileno(self):
                return self.stream.fileno()

        monkeypatch.setattr(reportlib.os, "fdopen", lambda *a, **k: BrokenStream(original_fdopen(*a, **k)))
    elif fault == "file_fsync":
        original = reportlib.os.fsync
        calls = 0
        def fail_first(fd):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected checkpoint file fsync failure")
            return original(fd)
        monkeypatch.setattr(reportlib.os, "fsync", fail_first)
    elif fault == "rename":
        monkeypatch.setattr(reportlib.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("injected rename failure")))
    else:
        monkeypatch.setattr(reportlib, "_fsync_directory",
                            lambda *_: (_ for _ in ()).throw(OSError("injected directory fsync failure")))
    with pytest.raises(OSError):
        store.checkpoint({"version": 2})
    saved = json.loads(store.checkpoint_path.read_text())
    assert saved in ({"version": 1}, {"version": 2})
    store.close()


def test_case_schedule_has_six_fixed_batches_and_randomized_case_order():
    from nova.benchmark_parallel_cases import load_corpus
    cases = load_corpus()["exploratory"]
    groups = runner._groups(cases, 2, seed=1729)
    batches = [groups[i:i + 8] for i in range(0, len(groups), 8)]
    assert len(groups) == 48
    assert len(batches) == 6
    assert all(len(batch) == 8 for batch in batches)
    assert all(len({g["repetition"] for g in batch}) == 1 for batch in batches)
    assert all(len({g["case_id"] for g in batch}) == 8 for batch in batches)
    assert len({g["case_id"] for g in groups[:24]}) == 24
    assert len({g["case_id"] for g in groups[24:]}) == 24


def _report_fixture(repetitions=2):
    cases = [{"id": f"c{i}", "family": "f", "pair_id": f"p{i}", "variant": i % 2}
             for i in range(2)]
    groups = []
    for rep in range(1, repetitions + 1):
        for case in cases:
            arms = {}
            for arm in reportlib.ARMS:
                arms[arm] = {"status": "completed", "delivery_valid": True,
                             "deadline_penalty_seconds": 10.0,
                             "observed_delivery_seconds": 10.0,
                             "structured_delivery_utility": 0.8}
            groups.append({"case_id": case["id"], "repetition": rep, "status": "completed", "arms": arms})
    return {"cases": cases, "groups": groups, "repetitions": repetitions}


def test_duplicate_or_missing_repetitions_nulls_pair_summary():
    payload = _report_fixture()
    payload["groups"][-1]["repetition"] = 1  # duplicate repetition; no inference by row count
    rows = reportlib._aggregate_cases(payload)
    assert not all(row["pair_complete"] for row in rows)
    assert reportlib.stratified_pair_bootstrap(rows, approved=True) is None

    missing = _report_fixture()
    missing["groups"].pop()
    assert not reportlib._aggregate_cases(missing)[-1]["pair_complete"]


def test_ci_requires_dependency_approval_and_exact_pair_shapes():
    rows = reportlib._aggregate_cases(_report_fixture())
    assert reportlib.stratified_pair_bootstrap(rows, approved=False) is None
    assert reportlib.stratified_pair_bootstrap(rows, approved=True) is None  # not six families/two pair clusters


def test_cli_offline_manifest_no_calls_and_private_exclusive_output(tmp_path, monkeypatch):
    target = tmp_path / "fresh-output"
    monkeypatch.setattr(runner, "create_run_directory", lambda requested: (target.mkdir(mode=0o700), target)[1])
    args = argparse.Namespace(stage="development", corpus=str(runner.DEFAULT_CORPUS), output=None,
                              model=runner.MODEL, reasoning_effort="medium", enable_model_calls=False,
                              dependency_audit_approved=False, offline_gold_fixture=False)
    result = asyncio.run(runner._run(args))
    assert result == 0
    payload = json.loads((target / "report.json").read_text())
    assert payload["sdk_turns_reserved"] == 0
    assert payload["limits"]["sdk_turns"] == 24
    assert payload["model_calls_enabled"] is False
    assert payload["runner_status"] == "offline_manifest_only"
    journal = reportlib.DurableRunStore.read_journal(target / "events.jsonl")
    assert all(event["event"] != "sdk_turn_reserved" for event in journal)


def test_offline_gold_is_explicitly_not_model_evidence(tmp_path, monkeypatch):
    target = tmp_path / "gold-output"
    monkeypatch.setattr(runner, "create_run_directory", lambda requested: (target.mkdir(mode=0o700), target)[1])
    args = argparse.Namespace(stage="development", corpus=str(runner.DEFAULT_CORPUS), output=None,
                              model=runner.MODEL, reasoning_effort="medium", enable_model_calls=False,
                              dependency_audit_approved=False, offline_gold_fixture=True)
    result = asyncio.run(runner._run(args))
    payload = json.loads((target / "report.json").read_text())
    assert result == 0
    assert payload["offline_gold_is_model_evidence"] is False
    assert payload["sdk_turns_reserved"] == 0
    assert payload["runner_status"] == "offline_gold_fixture"
