from __future__ import annotations

import pytest


def test_decision_tool_context_rejects_swapped_run_or_database(monkeypatch, tmp_path):
    from nova import decision_tools

    expected_db = tmp_path / "expected.sqlite"
    other_db = tmp_path / "other.sqlite"
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID", "expected-run")
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_DATABASE", str(expected_db))
    monkeypatch.setattr(decision_tools, "_bridge_read_context",
                        lambda: (expected_db, "expected-run"))
    assert decision_tools._read_context() == (expected_db, "expected-run")

    monkeypatch.setattr(decision_tools, "_bridge_read_context",
                        lambda: (other_db, "other-run"))
    with pytest.raises(ValueError, match="trusted adaptive run binding"):
        decision_tools._read_context()


@pytest.mark.parametrize("present", [
    {"NOVA_ADAPTIVE_EXPECTED_RUN_ID": "expected-run"},
    {"NOVA_ADAPTIVE_EXPECTED_DATABASE": "/tmp/expected.sqlite"},
])
def test_decision_tool_context_rejects_incomplete_binding(monkeypatch, present):
    from nova import decision_tools

    monkeypatch.delenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID", raising=False)
    monkeypatch.delenv("NOVA_ADAPTIVE_EXPECTED_DATABASE", raising=False)
    for key, value in present.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(decision_tools, "_bridge_read_context",
                        lambda: ("/tmp/expected.sqlite", "expected-run"))
    with pytest.raises(ValueError, match="trusted adaptive run binding"):
        decision_tools._read_context()


def test_finalization_write_fails_closed_after_shared_deadline(monkeypatch, tmp_path):
    import time

    from nova import adaptive_agent_tools, native_finalization_tools

    db_path = tmp_path / "run.sqlite"
    run_id = "deadline-run"
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID", run_id)
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_DATABASE", str(db_path))
    monkeypatch.setenv("NOVA_ADAPTIVE_BUDGET_DEADLINE", str(time.monotonic() - 1))
    monkeypatch.setattr(adaptive_agent_tools, "_read_bound_context",
                        lambda: (db_path, run_id))

    with pytest.raises(TimeoutError, match="deadline has expired"):
        native_finalization_tools._context(write=True)


def test_finalization_stage_hash_rejects_tampered_persisted_packet():
    import hashlib
    import json

    from nova import native_finalization_tools as finalization

    packet = {"stage": "reviewed", "review": {"reason": "bounded limitation"}}
    raw = finalization._canonical(packet)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert finalization._decode_stage_record(raw, digest) == packet

    tampered = json.dumps({"stage": "reviewed", "review": {"reason": "changed"}},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with pytest.raises(ValueError, match="hash is invalid"):
        finalization._decode_stage_record(tampered, digest)


def test_finalization_trace_requires_matching_tool_result_and_same_pid_turn(monkeypatch):
    import hashlib

    from nova import native_finalization_tools as finalization

    monkeypatch.setattr(finalization, "_has_guard",
                        lambda _records, _pid, _role, _before: True)
    args = {"concern": "The finite snapshot limits generalization."}
    returned = {"review": {"reason": args["concern"]}, "stage": "reviewed"}
    request = {"event": "tool_request", "actor": "codex-model",
               "tool": "submit_native_final_review", "role": "skeptic",
               "pid": 101, "call_id": "review-call",
               "args_sha256": finalization._args_hash(args)}
    complete = {"event": "tool_complete", "actor": "omnigent-tool-dispatch",
                "tool": "submit_native_final_review", "role": "skeptic",
                "pid": 101, "call_id": "review-call", "status": "success",
                "structured_result_sha256": hashlib.sha256(
                    finalization._canonical(returned).encode("utf-8")).hexdigest()}
    turn = {"event": "turn_complete", "actor": "codex-model", "role": "skeptic",
            "pid": 101, "status": "completed"}

    assert not finalization._tool_call([], tool="submit_native_final_review", args=args,
                                       role="skeptic", result=returned)
    assert not finalization._tool_call([request, {**complete, "pid": 102}, turn],
                                       tool="submit_native_final_review", args=args,
                                       role="skeptic", result=returned)
    wrong_return = {**complete, "structured_result_sha256": "0" * 64}
    assert not finalization._tool_call([request, wrong_return, turn],
                                       tool="submit_native_final_review", args=args,
                                       role="skeptic", result=returned)
    assert finalization._tool_call([request, complete, turn],
                                   tool="submit_native_final_review", args=args,
                                   role="skeptic", result=returned)


def test_final_freeze_detects_existing_result_by_experiment_id():
    from types import SimpleNamespace

    from nova import native_finalization_tools as finalization

    class Store:
        def list_results(self):
            return [SimpleNamespace(experiment_id="registered-holdout")]

    assert finalization._has_result_for_experiment(Store(), "registered-holdout")
    assert not finalization._has_result_for_experiment(Store(), "different-experiment")


@pytest.mark.parametrize(
    "selection,status,reason_code",
    [
        ({"choice": "method_sensitivity"}, "completed", "unsupported_method_audit"),
        ({"choice": "threshold_sensitivity"}, "running", "runner_not_completed"),
    ],
)
def test_finalization_rejects_unsupported_method_or_incomplete_runner(
        monkeypatch, tmp_path, selection, status, reason_code):
    import json

    from nova import native_finalization_tools as finalization

    db_path = tmp_path / "run.sqlite"
    monkeypatch.setattr(finalization, "_context", lambda **_kwargs: (db_path, "run-x", object()))
    monkeypatch.setattr(finalization, "_state_row", lambda *_args: (
        "parent-result", json.dumps(selection), "registered-id",
        "audit_id" if selection["choice"] == "method_sensitivity" else "experiment_id", status))

    state = finalization._resolve_followup()
    assert state["supported"] is False
    assert state["reason_code"] == reason_code
