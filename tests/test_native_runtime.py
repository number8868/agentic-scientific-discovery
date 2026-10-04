from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


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
