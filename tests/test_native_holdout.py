import time
import hashlib
import json

import pytest


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=str)


def test_final_pi_response_must_match_completed_freeze_turn():
    from nova import native_holdout_tools as tools

    class Finalization:
        _canonical = staticmethod(_canonical)
        _args_hash = staticmethod(lambda value: hashlib.sha256(_canonical(value).encode()).hexdigest())
        _has_guard = staticmethod(lambda *_args: True)
        _tool_call = staticmethod(lambda *args, **kwargs: True)

    frozen = {"stage": "frozen_unexecuted", "holdout_experiment_id": "H1",
              "frozen_protocol_id": "F1", "explanation": "approved"}
    response_text = "Freeze complete: F1"
    response = {"role": "pi", "pid": 44, "freeze_call_id": "c1",
                "response_text": response_text,
                "response_sha256": hashlib.sha256(response_text.encode()).hexdigest(),
                "response_chars": len(response_text)}
    response_meta = {"response_sha256": response["response_sha256"],
                     "response_chars": response["response_chars"]}
    records = [
        {"event": "tool_request", "actor": "codex-model", "tool": "freeze_native_final_protocol",
         "role": "pi", "pid": 44, "call_id": "c1",
         "args_sha256": Finalization._args_hash({"explanation": "approved"})},
        {"event": "tool_complete", "actor": "omnigent-tool-dispatch", "tool": "freeze_native_final_protocol",
         "role": "pi", "pid": 44, "call_id": "c1", "status": "success",
         "structured_result_sha256": hashlib.sha256(_canonical(frozen).encode()).hexdigest()},
        {"event": "turn_complete", "actor": "codex-model", "role": "pi", "pid": 44,
         "result_sha256": hashlib.sha256(_canonical(response_meta).encode()).hexdigest()},
    ]
    tools._verify_finalization_proof(Finalization, records, frozen, response, "H1")
    altered = dict(response, response_text="tampered", response_sha256=hashlib.sha256(b"tampered").hexdigest(),
                   response_chars=len("tampered"))
    with pytest.raises(ValueError, match="freeze turn"):
        tools._verify_finalization_proof(Finalization, records, frozen, altered, "H1")
    with pytest.raises(ValueError, match="freeze turn"):
        tools._verify_finalization_proof(Finalization, records, frozen,
                                         dict(response, pid=45), "H1")
    mismatched = [dict(record, call_id="different") if record.get("event") == "tool_complete" else record
                  for record in records]
    with pytest.raises(ValueError, match="freeze turn"):
        tools._verify_finalization_proof(Finalization, mismatched, frozen, response, "H1")


def test_holdout_requires_explicit_parent_approval(monkeypatch):
    from nova import native_holdout_tools as tools

    monkeypatch.delenv("NOVA_NATIVE_HOLDOUT_APPROVED", raising=False)
    with pytest.raises(PermissionError, match="not explicitly approved"):
        tools._trusted_scope("NOVA-HOLDOUT-1234567890abcdef")


def test_holdout_rejects_nonfinite_original_deadline(monkeypatch, tmp_path):
    from nova import adaptive_agent_tools, native_holdout_tools

    monkeypatch.setenv("NOVA_NATIVE_HOLDOUT_APPROVED", "1")
    monkeypatch.setattr(native_holdout_tools, "_verify_trusted_descendant", lambda: (200, 100))
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_RUN_ID", "run")
    monkeypatch.setenv("NOVA_ADAPTIVE_EXPECTED_DATABASE", str(tmp_path / "db"))
    monkeypatch.setenv("NOVA_ADAPTIVE_BUDGET_DEADLINE", "inf")
    monkeypatch.setattr(adaptive_agent_tools, "_read_bound_context",
                        lambda: (tmp_path / "db", "run"))
    with pytest.raises(TimeoutError, match="deadline"):
        native_holdout_tools._trusted_scope("NOVA-HOLDOUT-1234567890abcdef")


def test_trusted_process_group_accepts_sdk_descendant_and_rejects_mismatch(monkeypatch):
    from nova import native_holdout_tools as tools

    monkeypatch.setattr(tools.os, "name", "posix")
    monkeypatch.setenv("NOVA_ADAPTIVE_TRUSTED_CHILD", "1")
    monkeypatch.setenv("NOVA_ADAPTIVE_OWNER_PID", "200")
    monkeypatch.setenv("NOVA_ADAPTIVE_PARENT_PID", "100")
    monkeypatch.setattr(tools.os, "getpgrp", lambda: 200)
    checked = []
    monkeypatch.setattr(tools.os, "kill", lambda pid, signal: checked.append(pid))
    assert tools._verify_trusted_descendant() == (200, 100)
    assert checked == [200, 100]

    monkeypatch.setattr(tools.os, "getpgrp", lambda: 201)
    with pytest.raises(PermissionError, match="outside the trusted parent's process group"):
        tools._verify_trusted_descendant()


def test_expired_before_claim_does_not_claim_and_restores_gate(monkeypatch, tmp_path):
    from nova import adaptive_agent_tools, holdout_bridge, native_holdout_tools

    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(native_holdout_tools, "_trusted_scope",
                        lambda _id: (db, "run", time.monotonic() - 1, tmp_path / "trace"))
    monkeypatch.setattr(adaptive_agent_tools, "_read_bound_context", lambda: (db, "run"))
    claims = []
    monkeypatch.setattr(holdout_bridge, "_claim", lambda *a, **k: claims.append(a))
    with pytest.raises(TimeoutError, match="deadline"):
        native_holdout_tools.execute_frozen_native_holdout("NOVA-HOLDOUT-1234567890abcdef")
    assert claims == []


def test_bounded_controller_uses_original_remaining_deadline(monkeypatch, tmp_path):
    from nova import adaptive_agent_tools, holdout_bridge, native_holdout_tools

    db = tmp_path / "db.sqlite"
    deadline = time.monotonic() + 2
    monkeypatch.setattr(native_holdout_tools, "_trusted_scope",
                        lambda _id: (db, "run", deadline, tmp_path / "trace"))
    monkeypatch.setattr(adaptive_agent_tools, "_read_bound_context", lambda: (db, "run"))
    monkeypatch.setattr(adaptive_agent_tools, "record_native_trace", lambda *a, **k: None)
    observed = []

    class Controller:
        def run(self, name, args=(), kwargs=None, *, deadline_seconds):
            observed.append(deadline_seconds)
            return "ok"

    class Result:
        def to_dict(self):
            return {"result_id": "synthetic"}

    original_claim = holdout_bridge._claim
    patched_factory = lambda _r: Controller()
    original_persist = holdout_bridge._persist_success
    def gate(_experiment_id):
        controller = holdout_bridge._controller_factory({})
        controller.run("synthetic", deadline_seconds=90)
        return Result()

    monkeypatch.setattr(holdout_bridge, "execute_live_registered_holdout", gate)
    monkeypatch.setattr(holdout_bridge, "_controller_factory", patched_factory)
    result = native_holdout_tools.execute_frozen_native_holdout("NOVA-HOLDOUT-1234567890abcdef")
    assert result == {"result_id": "synthetic"}
    assert 0 < observed[0] <= 2
    assert holdout_bridge._claim is original_claim
    assert holdout_bridge._controller_factory is patched_factory
    assert holdout_bridge._persist_success is original_persist


def _install_synthetic_adapter(monkeypatch, tmp_path, *, deadline):
    from nova import adaptive_agent_tools, holdout_bridge, native_holdout_tools

    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(native_holdout_tools, "_trusted_scope",
                        lambda _id: (db, "run", deadline, tmp_path / "trace"))
    monkeypatch.setattr(adaptive_agent_tools, "_read_bound_context", lambda: (db, "run"))
    monkeypatch.setattr(adaptive_agent_tools, "record_native_trace", lambda *a, **k: None)
    return holdout_bridge, native_holdout_tools


def test_deadline_expiring_after_worker_return_prevents_result_persistence(monkeypatch, tmp_path):
    deadline = 1000.0
    gate, tools = _install_synthetic_adapter(monkeypatch, tmp_path, deadline=deadline)
    times = iter([0.0, 1.0, 1001.0])  # adapter entry, worker entry, worker return
    monkeypatch.setattr(tools.time, "monotonic", lambda: next(times))
    persist_calls = []
    def fake_persist(*args, **kwargs):
        persist_calls.append(args)

    monkeypatch.setattr(gate, "_persist_success", fake_persist)

    class Controller:
        def run(self, name, args=(), kwargs=None, *, deadline_seconds):
            return "completed worker result"

    original_claim = gate._claim
    patched_factory = lambda _r: Controller()
    monkeypatch.setattr(gate, "_controller_factory", patched_factory)

    def fake_gate(_experiment_id):
        gate._controller_factory({}).run("science", deadline_seconds=120)
        gate._persist_success("db", "run", None, None)
        return {"result_id": "should-not-return"}

    monkeypatch.setattr(gate, "execute_live_registered_holdout", fake_gate)
    with pytest.raises(TimeoutError, match="deadline"):
        tools.execute_frozen_native_holdout("H1")
    assert persist_calls == []
    assert gate._claim is original_claim
    assert gate._controller_factory is patched_factory
    assert gate._persist_success is fake_persist


def test_deadline_expiring_immediately_before_persist_rejects_result(monkeypatch, tmp_path):
    deadline = 1000.0
    gate, tools = _install_synthetic_adapter(monkeypatch, tmp_path, deadline=deadline)
    times = iter([0.0, 1.0, 2.0, 1001.0])  # entry, worker start/return, pre-persist
    monkeypatch.setattr(tools.time, "monotonic", lambda: next(times))

    class Controller:
        def run(self, name, args=(), kwargs=None, *, deadline_seconds):
            return "completed worker result"

    original_claim = gate._claim
    patched_factory = lambda _r: Controller()
    monkeypatch.setattr(gate, "_controller_factory", patched_factory)
    persist_calls = []

    def real_gate_prefix(_experiment_id):
        gate._controller_factory({}).run("science", deadline_seconds=120)
        gate._persist_success("db", "run", None, None)

    fake_persist = lambda *a, **k: persist_calls.append(a)
    monkeypatch.setattr(gate, "_persist_success", fake_persist)
    monkeypatch.setattr(gate, "execute_live_registered_holdout", real_gate_prefix)
    with pytest.raises(TimeoutError, match="deadline"):
        tools.execute_frozen_native_holdout("H1")
    assert persist_calls == []
    assert gate._claim is original_claim
    assert gate._controller_factory is patched_factory
    assert gate._persist_success is fake_persist


def test_context_mismatch_and_exception_restore_gate(monkeypatch, tmp_path):
    from nova import adaptive_agent_tools, holdout_bridge, native_holdout_tools

    db = tmp_path / "db.sqlite"
    monkeypatch.setattr(native_holdout_tools, "_trusted_scope",
                        lambda _id: (db, "run", time.monotonic() + 60, tmp_path / "trace"))
    monkeypatch.setattr(adaptive_agent_tools, "_read_bound_context", lambda: (db, "other-run"))
    originals = (holdout_bridge._claim, holdout_bridge._controller_factory, holdout_bridge._persist_success)
    with pytest.raises(ValueError, match="context changed"):
        native_holdout_tools.execute_frozen_native_holdout("NOVA-HOLDOUT-1234567890abcdef")
    assert originals == (holdout_bridge._claim, holdout_bridge._controller_factory,
                         holdout_bridge._persist_success)

    monkeypatch.setattr(adaptive_agent_tools, "_read_bound_context", lambda: (db, "run"))
    monkeypatch.setattr(adaptive_agent_tools, "record_native_trace", lambda *a, **k: None)
    monkeypatch.setattr(holdout_bridge, "execute_live_registered_holdout",
                        lambda _id: (_ for _ in ()).throw(RuntimeError("synthetic")))
    with pytest.raises(RuntimeError, match="synthetic"):
        native_holdout_tools.execute_frozen_native_holdout("NOVA-HOLDOUT-1234567890abcdef")
    assert originals == (holdout_bridge._claim, holdout_bridge._controller_factory,
                         holdout_bridge._persist_success)
