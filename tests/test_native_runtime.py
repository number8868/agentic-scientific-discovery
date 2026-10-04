from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_cli_spawn_hook_rewrites_only_owned_server_and_runner(monkeypatch):
    from nova.native_adaptive_runtime import launch_cli_with_guarded_runner

    calls = []

    def fake_popen(command, *args, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    module = SimpleNamespace()

    def start_runner():
        return subprocess.Popen([sys.executable, "-P", "-m", "omnigent.runner._entry"], start_new_session=True)

    module._start_cli_runner_process = start_runner

    def cli_main(**_kwargs):
        subprocess.Popen(["unrelated-tool"], start_new_session=True)
        subprocess.Popen([sys.executable, "-m", "omnigent.cli", "server", "--port", "0"],
                         start_new_session=True)
        module._start_cli_runner_process()

    module.cli = SimpleNamespace(main=cli_main)
    launch_cli_with_guarded_runner(module, ["run"], ROOT, Path("/usr/bin/true"))
    assert len(calls) == 3
    assert calls[0][0] == ["unrelated-tool"]
    assert calls[0][1]["start_new_session"] is True
    assert calls[1][0][1:4] == ["-m", "omnigent.cli", "server"]
    assert calls[1][1]["start_new_session"] is False
    assert calls[2][0][1:3] == ["-P", "-c"]
    assert "bootstrap_runner" in calls[2][0][3]
    assert calls[2][1]["start_new_session"] is False


def test_executor_trace_verifier_requires_matching_guard_per_process(tmp_path):
    from nova.native_adaptive_runtime import CONFIG_OVERRIDES, verify_executor_trace

    path = tmp_path / "audit.jsonl"
    events = [
        {"event": "runner_bootstrap_installed", "pid": 101},
        {"event": "executor_guard_installed", "pid": 202,
         "details": {"native_tools_disabled": True, "web_search_disabled": True,
                     "skills": "none", "config_overrides": [*CONFIG_OVERRIDES, 'model_provider="openai"'],
                     "host_binary": "/opt/codex-code-mode-host"}},
        {"event": "executor_turn_started", "pid": 202},
        {"event": "turn_complete", "pid": 202},
    ]
    path.write_text("\n".join(json.dumps(row) for row in events) + "\n", encoding="utf-8")
    assert verify_executor_trace(path, Path("/opt/codex-code-mode-host"))["verified_executor_pids"] == [202]
    events[1]["details"]["config_overrides"].append("arbitrary_config=true")
    path.write_text("\n".join(json.dumps(row) for row in events) + "\n", encoding="utf-8")
    try:
        verify_executor_trace(path, Path("/opt/codex-code-mode-host"))
    except RuntimeError as exc:
        assert "guard record" in str(exc)
    else:
        raise AssertionError("arbitrary config override was accepted")
    events[1]["details"]["config_overrides"].pop()
    events[-1]["pid"] = 303
    path.write_text("\n".join(json.dumps(row) for row in events) + "\n", encoding="utf-8")
    try:
        verify_executor_trace(path, Path("/opt/codex-code-mode-host"))
    except RuntimeError as exc:
        assert "guard record" in str(exc)
    else:
        raise AssertionError("unguarded executor PID was accepted")


def test_native_function_result_decoder_handles_bounded_sdk_envelopes():
    from nova.native_adaptive_runtime import _decode_native_function_result

    assert _decode_native_function_result({"result": "{'stage': 'reviewed', 'ok': True}"}) == {
        "stage": "reviewed", "ok": True}
    assert _decode_native_function_result({"result": '{"stage":"frozen","ok":true}'}) == {
        "stage": "frozen", "ok": True}
    assert _decode_native_function_result({
        "content": [{"type": "text", "text": '{"stage":"reviewed"}'}], "isError": False,
    }) == {"stage": "reviewed"}
    assert _decode_native_function_result({"result": "__import__('os').system('true')"}) is None
    assert _decode_native_function_result({"result": '{"stage": true, "x": null}'}) == {
        "stage": True, "x": None}


def test_final_trace_verifier_matches_real_turn_hash_and_provider_guard(tmp_path):
    from nova.native_adaptive_runtime import verify_executor_trace
    from nova.adaptive_agent_tools import _valid_codex_config_overrides

    host = Path("/opt/codex-code-mode-host")
    response = "Frozen, unexecuted."
    digest = hashlib.sha256(response.encode()).hexdigest()
    turn_hash = hashlib.sha256(json.dumps(
        {"response_sha256": digest, "response_chars": len(response)},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    rows = [{"event": "runner_bootstrap_installed", "pid": 10}]
    for pid, role, tool, call_id in ((20, "skeptic", "record_adaptive_review", "primary-review-1"),
                                     (21, "skeptic", "submit_native_final_review", "review-1"),
                                     (22, "pi", "freeze_native_final_protocol", "freeze-1")):
        rows.extend([
            {"event": "executor_guard_installed", "pid": pid, "role": role,
             "details": {"native_tools_disabled": True, "web_search_disabled": True,
                         "skills": "none", "config_overrides": [
                             "features.code_mode_host=true", "features.code_mode=false",
                             'web_search="disabled"', 'model_provider="openai"'],
                         "host_binary": str(host)}},
            {"event": "executor_turn_started", "pid": pid, "role": role},
            {"event": "tool_request", "actor": "codex-model", "pid": pid, "role": role,
             "tool": tool, "call_id": call_id},
            {"event": "tool_complete", "actor": "omnigent-tool-dispatch", "pid": pid, "role": role,
             "tool": tool, "call_id": call_id, "status": "success", "structured_result_sha256": "a" * 64},
            {"event": "turn_complete", "actor": "codex-model", "pid": pid, "role": role,
             "result_sha256": turn_hash if role == "pi" else "b" * 64},
        ])
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert _valid_codex_config_overrides(rows[1]["details"]["config_overrides"])
    assert verify_executor_trace(path, host,
                                 required_tools=("record_adaptive_review", "submit_native_final_review", "freeze_native_final_protocol"),
                                 final_response=response)["completed_turns"] == 3
    try:
        verify_executor_trace(path, host,
                              required_tools=("submit_native_final_review", "freeze_native_final_protocol"),
                              final_response="different PI response")
    except RuntimeError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("mismatched final PI response was accepted")


def test_final_trace_verifier_binds_exact_finalization_text_after_retry_turn(tmp_path):
    from nova.native_adaptive_runtime import CONFIG_OVERRIDES, verify_executor_trace

    host = Path("/opt/codex-code-mode-host")
    final_response = (
        "Host confirmed `stage=frozen_unexecuted` for protocol `NOVA-FINAL-fixture`.\n\n"
        "Skeptic Final recorded one medium concern: sparse pass counts leave the contrast’s "
        "magnitude uncertain. Holdout `NOVA-HOLDOUT-fixture` remains unexecuted; findings "
        "remain limited to discovery snapshot evidence.\n\n"
        "The first freeze call was rejected for explanation length; the shortened retry succeeded."
    )

    def response_hash(text):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return hashlib.sha256(json.dumps(
            {"response_sha256": digest, "response_chars": len(text)},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()

    rows = [{"event": "runner_bootstrap_installed", "pid": 10}]

    def add_turn(pid, role, tool, call_id, *, structured_result="a" * 64,
                 status="success", response="role response"):
        rows.extend([
            {"event": "executor_guard_installed", "pid": pid, "role": role,
             "details": {"native_tools_disabled": True, "web_search_disabled": True,
                         "skills": "none", "config_overrides": [*CONFIG_OVERRIDES,
                                                                    'model_provider="openai"'],
                         "host_binary": str(host)}},
            {"event": "executor_turn_started", "pid": pid, "role": role},
            {"event": "tool_request", "actor": "codex-model", "pid": pid, "role": role,
             "tool": tool, "call_id": call_id},
            {"event": "tool_complete", "actor": "omnigent-tool-dispatch", "pid": pid,
             "role": role, "tool": tool, "call_id": call_id, "status": status,
             "structured_result_sha256": structured_result},
            {"event": "turn_complete", "actor": "codex-model", "pid": pid, "role": role,
             "result_sha256": response_hash(response)},
        ])

    add_turn(20, "skeptic", "record_adaptive_review", "primary-review")
    add_turn(21, "skeptic", "submit_native_final_review", "final-review")
    # The first PI attempt ends after a rejected overlong explanation.
    add_turn(22, "pi", "freeze_native_final_protocol", "freeze-retry-1",
             structured_result=None, status="error", response="Rejected explanation.")
    add_turn(22, "pi", "freeze_native_final_protocol", "freeze-retry-2",
             response=final_response)

    path = tmp_path / "multi-response-trace.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    required = ("record_adaptive_review", "submit_native_final_review",
                "freeze_native_final_protocol")
    response_record = {"schema_version": 1, "pid": 22, "role": "pi",
                       "freeze_call_id": "freeze-retry-2", "response_text": final_response,
                       "response_sha256": hashlib.sha256(final_response.encode()).hexdigest(),
                       "response_chars": len(final_response)}
    assert verify_executor_trace(path, host, required_tools=required,
                                 final_response=final_response,
                                 final_response_record=response_record)["completed_turns"] == 4

    for invalid_response in (
        "First discovery session reply.\n\n" + final_response,
        final_response.replace("shortened retry succeeded", "shortened retry failed"),
    ):
        try:
            verify_executor_trace(path, host, required_tools=required,
                                  final_response=invalid_response,
                                  final_response_record=response_record)
        except RuntimeError as exc:
            assert "does not match" in str(exc)
        else:
            raise AssertionError("aggregated or changed final PI response was accepted")

    for bad_record in ({**response_record, "pid": 23},
                       {**response_record, "freeze_call_id": "missing-freeze"}):
        try:
            verify_executor_trace(path, host, required_tools=required,
                                  final_response=final_response, final_response_record=bad_record)
        except RuntimeError:
            pass
        else:
            raise AssertionError("response record without the matching guarded freeze was accepted")


def test_final_pi_response_record_preserves_raw_text_and_rejects_tampering(tmp_path, monkeypatch):
    from nova import native_adaptive_runtime as runtime

    run_dir = tmp_path / "run-owned"
    run_dir.mkdir()
    trace = run_dir / "native-model-audit.jsonl"
    trace.write_text("{}\n", encoding="utf-8")
    trace.chmod(0o600)
    monkeypatch.setattr(runtime, "RUNS_ROOT", tmp_path)
    raw = "  Exact TurnComplete response.\n"
    runtime._write_final_pi_response(trace, pid=42, role="pi", freeze_call_id="freeze-1", response=raw)
    record = runtime.read_final_pi_response(trace)
    assert record["response_text"] == raw
    assert record["response_chars"] == len(raw)
    assert record["response_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(FileExistsError):
        runtime._write_final_pi_response(trace, pid=42, role="pi", freeze_call_id="freeze-1", response=raw)

    record_path = run_dir / "native-final-pi-response.json"
    tampered = json.loads(record_path.read_text(encoding="utf-8"))
    tampered["response_text"] = "changed"
    record_path.write_text(json.dumps(tampered), encoding="utf-8")
    record_path.chmod(0o600)
    with pytest.raises(RuntimeError, match="integrity"):
        runtime.read_final_pi_response(trace)


def test_executor_error_is_private_bounded_and_still_fails_trace_verification(tmp_path, monkeypatch):
    from nova import adaptive_agent_tools, native_adaptive_runtime as runtime
    from omnigent.inner.executor import ExecutorError

    run_dir = tmp_path / "runs" / "run-error"
    run_dir.mkdir(parents=True)
    trace = run_dir / "native-model-audit.jsonl"
    host = Path("/opt/codex-code-mode-host")
    trace.write_text("\n".join(json.dumps(row) for row in (
        {"event": "runner_bootstrap_installed", "pid": 1},
        {"event": "executor_guard_installed", "pid": 42, "role": "runner",
         "details": {"native_tools_disabled": True, "web_search_disabled": True, "skills": "none",
                     "config_overrides": ["features.code_mode_host=true", "features.code_mode=false",
                                          'web_search="disabled"'], "host_binary": str(host)}},
        {"event": "executor_turn_started", "pid": 42, "role": "runner"},
    )) + "\n", encoding="utf-8")
    trace.chmod(0o600)
    monkeypatch.setattr(runtime, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(adaptive_agent_tools, "ROOT", tmp_path)
    monkeypatch.setenv("NOVA_ADAPTIVE_TRACE_PATH", str(trace))
    message = "Provider turn failed with diagnostic token sk-sensitive-fixture"
    error = ExecutorError(message=message, retryable=True, usage={"input_tokens": 19})

    runtime._trace_executor_failure(trace, pid=42, role="runner", model="fixture", error=error)

    private_path = run_dir / "native-executor-errors.jsonl"
    assert private_path.stat().st_mode & 0o777 == 0o600
    private = json.loads(private_path.read_text(encoding="utf-8"))
    assert private["message"] == message
    assert private["full_message_sha256"] == hashlib.sha256(message.encode()).hexdigest()
    assert private["retryable"] is True
    assert private["usage"] == {"input_tokens": 19}
    public_line = trace.read_text(encoding="utf-8")
    assert message not in public_line and "sk-sensitive-fixture" not in public_line
    public = json.loads(public_line.splitlines()[-1])
    assert public["event"] == "turn_failed" and public["status"] == "error"
    assert public["details"] == {"error_category": "executor_error",
                                 "error_message_sha256": hashlib.sha256(message.encode()).hexdigest(),
                                 "retryable": True}
    with pytest.raises(RuntimeError, match="failed model turn"):
        runtime.verify_executor_trace(trace, host)


def test_spawned_sdk_bootstrap_guards_real_codex_executor_without_model_calls(tmp_path):
    audit_root = tmp_path / "audit-root"
    run_dir = audit_root / "runs" / "runtime-probe"
    run_dir.mkdir(parents=True)
    audit = run_dir / "native-model-audit.jsonl"
    audit.touch(mode=0o600)
    audit.chmod(0o600)

    code = r'''
import json, os, sys
from pathlib import Path
from nova import adaptive_agent_tools
adaptive_agent_tools.ROOT = Path(sys.argv[1])
os.environ["NOVA_ADAPTIVE_TRACE_PATH"] = sys.argv[2]
from nova.native_adaptive_runtime import bootstrap_runner, install_codex_guardrails
bootstrap_runner(sys.argv[3], "/usr/bin/true")
guard = install_codex_guardrails("/usr/bin/true")
from omnigent.runtime.harnesses import _HARNESS_MODULES
from omnigent.inner.codex_executor import CodexExecutor
executor = CodexExecutor(codex_path="/usr/bin/true", model="fixture-model", agent_name="fixture-agent")
assert _HARNESS_MODULES["codex"] == "nova.native_adaptive_harness"
assert executor._disable_native_tools is True
assert executor._enable_web_search is False
assert executor._skills_filter == "none"
assert executor._model_override == "fixture-model"
assert "features.code_mode_host=true" in executor._codex_config_overrides
assert "features.code_mode=false" in executor._codex_config_overrides
print(json.dumps({"guard": guard, "native_tools": executor._disable_native_tools,
                  "web_search": executor._enable_web_search, "skills": executor._skills_filter,
                  "model": executor._model_override}))
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(audit_root), str(audit), str(ROOT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout.strip().splitlines()[-1])
    assert state["native_tools"] is True
    assert state["web_search"] is False
    assert state["skills"] == "none"
    assert state["model"] == "fixture-model"
    records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert {row["event"] for row in records} >= {"runner_bootstrap_installed", "executor_guard_installed"}
    assert all(row["pid"] != __import__("os").getpid() for row in records)
