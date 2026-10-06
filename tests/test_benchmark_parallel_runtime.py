import asyncio
import builtins
from contextlib import redirect_stdout
from io import StringIO
import json
import os
import sys
import types
from pathlib import Path

import pytest

from nova import benchmark_parallel_runtime as runtime
from scripts import parallel_selftest_worker as worker


def _fake_sdk(monkeypatch):
    active = {"n": 0, "max": 0}
    calls = []

    class ExecutorConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class TurnComplete:
        def __init__(self, response):
            self.response = response
            self.usage = None

    class ExecutorError:
        message = "fake failure"

    class ToolCallRequest:
        pass

    class ToolCallComplete:
        pass

    class State:
        def __init__(self, thread_id):
            self.app_session = types.SimpleNamespace(thread_id=thread_id)

    class FakeExecutor:
        next_id = 0

        def __init__(self):
            type(self).next_id += 1
            self.ident = type(self).next_id
            self._session_states = {}

        async def run_turn(self, *, messages, tools, system_prompt, config):
            calls.append((self, messages[0], tools, system_prompt, config.kwargs))
            session = messages[0]["session_id"]
            self._session_states[session] = State("thread-" + session)
            if "TOOLREQUEST" in messages[0]["content"]:
                yield ToolCallRequest()
                return
            if "TOOLCOMPLETE" in messages[0]["content"]:
                yield ToolCallComplete()
                return
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            await asyncio.sleep(0.025)
            active["n"] -= 1
            yield TurnComplete("out-" + str(len(calls)))

        async def close(self):
            return None

    for name, attrs in {
        "omnigent": {}, "omnigent.inner": {},
        "omnigent.inner.executor": {"ExecutorConfig": ExecutorConfig,
            "ExecutorError": ExecutorError, "ToolCallRequest": ToolCallRequest,
            "ToolCallComplete": ToolCallComplete, "TurnComplete": TurnComplete},
    }.items():
        module = types.ModuleType(name)
        for key, val in attrs.items():
            setattr(module, key, val)
        monkeypatch.setitem(sys.modules, name, module)

    class Input:
        def __init__(self):
            self.lines = [json.dumps({"type": "grant", "allowed": True, "parent_at": "t"}) + "\n"] * 3

        def readline(self):
            return self.lines.pop(0)

    monkeypatch.setattr(worker.sys, "stdin", Input())
    emitted = []
    monkeypatch.setattr(worker, "_emit", emitted.append)
    return FakeExecutor, calls, active, emitted


def test_persistent_arm_reuses_same_sdk_session_and_constant_system_prompt(monkeypatch):
    FakeExecutor, calls, _, emitted = _fake_sdk(monkeypatch)
    result = asyncio.run(worker.run_payload({"packet": "packet bytes", "arm": "single_self_review",
        "model": "fake", "reasoning_effort": "low"}, executor_factory=FakeExecutor))
    assert result["status"] == "success"
    assert [turn["role"] for turn in result["turns"]] == ["draft", "critique", "final"]
    assert len({call[1]["session_id"] for call in calls}) == 1
    assert len({call[3] for call in calls}) == 1
    assert len({turn["thread_id"] for turn in result["turns"]}) == 1
    assert [event["turn"]["role"] for event in emitted if event.get("type") == "turn"] == ["draft", "critique", "final"]


def test_parallel_review_uses_independent_original_packet_and_overlaps(monkeypatch):
    FakeExecutor, calls, active, _ = _fake_sdk(monkeypatch)
    result = asyncio.run(worker.run_payload({"packet": "same packet", "arm": "parallel_review",
        "model": "fake", "reasoning_effort": "low"}, executor_factory=FakeExecutor))
    by_role = {turn["role"]: turn for turn in result["turns"]}
    assert result["status"] == "success"
    assert by_role["planner"]["session_id"] != by_role["skeptic"]["session_id"]
    planner_prompt, skeptic_prompt = (calls[0][1]["content"], calls[1][1]["content"])
    assert "same packet" in planner_prompt and "same packet" in skeptic_prompt
    assert "Planner output" not in planner_prompt and "Skeptic output" not in planner_prompt
    assert "Planner output" not in skeptic_prompt and "Skeptic output" not in skeptic_prompt
    pi_prompt = next(row[1]["content"] for row in calls if "Planner output" in row[1]["content"])
    assert "Planner output" in pi_prompt and "Skeptic output" in pi_prompt
    assert active["max"] == 2


@pytest.mark.parametrize("needle", ["TOOLREQUEST", "TOOLCOMPLETE"])
def test_tool_attempts_fail_closed_without_a_tool_call(monkeypatch, needle):
    FakeExecutor, calls, _, _ = _fake_sdk(monkeypatch)
    result = asyncio.run(worker.run_payload({"packet": needle, "arm": "single_self_review",
        "model": "fake", "reasoning_effort": "low"}, executor_factory=FakeExecutor))
    assert result["status"] == "unauthorized_tool_request"
    assert len(result["turns"]) == 1
    assert calls[0][2] == []


def test_run_arm_worker_protocol_budget_denial_and_persistent_trace(tmp_path, monkeypatch):
    fake = tmp_path / "fake_worker.py"
    fake.write_text("""
import json, sys, time
request = json.loads(sys.stdin.readline())['payload']
roles = ['draft','critique','final'] if request.get('arm') == 'single_self_review' else [request['role']]
turns = []
for role in roles:
 print(json.dumps({'type':'dispatch','role':role}), flush=True)
 grant = json.loads(sys.stdin.readline())
 if not grant.get('allowed'):
  print(json.dumps({'type':'result','status':'budget_denied','turns':turns,'final_raw':''}), flush=True); raise SystemExit
 turns.append({'role':role,'status':'success','raw':'safe-'+role,'response':'safe-'+role,'session_id':'one','thread_id':'native1'})
 print(json.dumps({'type':'turn','turn':turns[-1]}), flush=True)
print(json.dumps({'type':'result','status':'success','turns':turns,'final_raw':'safe-final'}), flush=True)
""")
    monkeypatch.setattr(runtime, "_WORKER", fake)
    seen = []

    async def allow(role):
        seen.append(role)
        return 17

    success = asyncio.run(runtime.run_arm("packet", "single_self_review", "fake", "low", allow,
                                          turn_timeout=2, arm_timeout=8))
    assert success["status"] == "success"
    assert seen == ["draft", "critique", "final"]
    assert [turn["thread_id"] for turn in success["turns"]] == ["native1"] * 3
    assert success["cleanup_ok"] is True

    async def deny(role):
        return False

    denied = asyncio.run(runtime.run_arm("packet", "single_self_review", "fake", "low", deny,
                                         turn_timeout=2, arm_timeout=8))
    assert denied["status"] == "budget_denied"
    assert len(denied["turns"]) == 0
    assert denied["cleanup_ok"] is True


def test_run_arm_parallel_children_are_distinct_processes_and_audit_failure_stops(tmp_path, monkeypatch):
    fake = tmp_path / "fake_worker.py"
    fake.write_text("""
import json, os, sys, time
payload = json.loads(sys.stdin.readline())['payload']
role = payload['role']
start = time.monotonic()
print(json.dumps({'type':'dispatch','role':role}), flush=True)
grant = json.loads(sys.stdin.readline())
if not grant.get('allowed'):
 print(json.dumps({'type':'result','status':'budget_denied','turns':[]}), flush=True); raise SystemExit
if role in ('planner','skeptic'): time.sleep(0.12)
content = payload.get('content', {})
turn = {'role':role,'status':'success','raw':role,'response':role,'input':content,'pid':os.getpid(),'start':start,'end':time.monotonic(),'session_id':payload['session_id'],'thread_id':str(os.getpid())}
print(json.dumps({'type':'turn','turn':turn}), flush=True)
print(json.dumps({'type':'result','status':'success','turns':[turn],'final_raw':role}), flush=True)
""")
    monkeypatch.setattr(runtime, "_WORKER", fake)
    seen = []

    async def ok(role):
        await asyncio.sleep(0.01)
        seen.append(role)

    result = asyncio.run(runtime.run_arm("original", "parallel_review", "fake", "low", ok,
                                         turn_timeout=2, arm_timeout=8))
    assert result["status"] == "success"
    assert set(seen) == {"planner", "skeptic", "pi"}
    trace = {turn["role"]: turn for turn in result["turns"]}
    assert trace["planner"]["thread_id"] != trace["skeptic"]["thread_id"]
    assert len(result["turns"]) == 3
    assert trace["planner"]["input"] == {"packet": "original"}
    assert trace["skeptic"]["input"] == {"packet": "original"}
    assert trace["planner"]["start"] < trace["skeptic"]["end"]
    assert trace["skeptic"]["start"] < trace["planner"]["end"]
    assert trace["pi"]["input"] == {"packet": "original", "planner": "planner", "skeptic": "skeptic"}

    async def broken(_role):
        raise OSError("journal unavailable")

    failed = asyncio.run(runtime.run_arm("original", "parallel_review", "fake", "low", broken,
                                         turn_timeout=2, arm_timeout=8))
    assert failed["status"] == "fatal_audit_error"
    assert failed["fatal_audit"] is True
    assert len([role for role in seen if role == "pi"]) == 1


def test_forbidden_science_modules_are_not_imported_by_worker(monkeypatch):
    forbidden = ("nova.storage", "nova.experiments", "nova.native", "nova.holdout")
    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden), name
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert worker.SYSTEM_PROMPT


def test_child_protocol_stdout_survives_sdk_diagnostic_redirect(monkeypatch):
    protocol = StringIO()
    diagnostics = StringIO()
    monkeypatch.setattr(worker, "PROTOCOL_OUT", protocol)
    with redirect_stdout(diagnostics):
        worker._emit({"type": "result", "status": "success"})
        print("fake SDK diagnostic")
    assert json.loads(protocol.getvalue()) == {"type": "result", "status": "success"}
    assert diagnostics.getvalue() == "fake SDK diagnostic\n"


def test_worker_startup_timeout_and_detached_descendant_are_cleaned(tmp_path, monkeypatch):
    fake = tmp_path / "fake_worker.py"
    pid_file = tmp_path / "descendant.pid"
    fake.write_text(f"""
import json, subprocess, sys, time
payload = json.loads(sys.stdin.readline())['payload']
print(json.dumps({{'type':'dispatch','role':payload['role']}}), flush=True)
grant = json.loads(sys.stdin.readline())
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
open({str(pid_file)!r}, 'w').write(str(child.pid))
time.sleep(30)
""")
    monkeypatch.setattr(runtime, "_WORKER", fake)

    async def allow(_role):
        return None

    result = asyncio.run(runtime.run_arm("packet", "parallel_review", "fake", "low", allow,
                                         turn_timeout=0.4, arm_timeout=8))
    assert result["status"] in {"turn_timeout", "worker_error"}
    assert result["cleanup_ok"] is True
    child_pid = int(pid_file.read_text())
    status = os.popen(f"ps -o stat= -p {child_pid}").read().strip()
    assert not status or "Z" in status
