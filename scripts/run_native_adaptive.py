#!/usr/bin/env python3
"""Run a native Omnigent adaptive PI workflow through the guarded 0.16.0 harness.

Live model and science dispatch requires explicit ``--enable-native-live``;
``--check-only`` validates configuration and the installed bootstrap route only.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import hashlib
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = ROOT / "agents" / "adaptive-live.yaml"
SDK_PIN = "0.16.0"
DEFAULT_MODEL = "gpt-6-luna"
CONFIG_OVERRIDES = ("features.code_mode_host=true", "features.code_mode=false", 'web_search="disabled"')
HOST_PATH_ENV = "CODEX_CODE_MODE_HOST_PATH"
RUN_TIMEOUT_SECONDS = 720
CHILD_MARKER = "NOVA_ADAPTIVE_TRUSTED_CHILD"
PARENT_PID_ENV = "NOVA_ADAPTIVE_PARENT_PID"
RUNTIME_BLOCKER = ("Omnigent Codex executes in a per-conversation harness process; live dispatch requires "
                   "the pinned guarded harness bootstrap and executor trace in that process")


def _load_yaml(path: Path = AGENT) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("native adaptive YAML root must be a mapping")
    return data


def _validate_agent(path: Path = AGENT) -> dict[str, Any]:
    from omnigent.inner.loader import load_agent_def_from_path

    agent = load_agent_def_from_path(str(path))
    raw = _load_yaml(path)
    tools = raw.get("tools")
    if not isinstance(tools, dict) or set(tools) != {"planner", "skeptic", "runner", "commit_adaptive_choice"}:
        raise ValueError("native adaptive YAML must declare PI, Planner, Skeptic, and Runner tools")
    required = {
        "planner": {"get_adaptive_options": "nova.adaptive_agent_tools.get_adaptive_options"},
        "skeptic": {"read_adaptive_evidence": "nova.adaptive_agent_tools.read_adaptive_evidence",
                    "record_adaptive_review": "nova.adaptive_agent_tools.record_adaptive_review"},
        "runner": {"execute_selected_adaptive": "nova.adaptive_agent_tools.execute_selected_adaptive"},
    }
    for role, functions in required.items():
        role_tools = tools[role].get("tools")
        if not isinstance(role_tools, dict) or {name: item.get("callable") for name, item in role_tools.items()} != functions:
            raise ValueError(f"{role} function allowlist differs from the checked contract")
        if any(item.get("type") != "function" for item in role_tools.values()):
            raise ValueError(f"{role} may expose only its listed functions")
    pi = tools["commit_adaptive_choice"]
    if pi.get("type") != "function" or pi.get("callable") != "nova.adaptive_agent_tools.commit_adaptive_choice":
        raise ValueError("PI choice function is not host-bound")
    # Parsing by Omnigent proves the real installed 0.16 YAML loader accepts
    # the fields; inspect the parsed tree for the actual agent/subagent types.
    if not getattr(agent, "tools", None):
        raise ValueError("Omnigent parsed no tools from the native adaptive YAML")
    return raw


def _codex_binaries(*, require_host: bool) -> tuple[Path | None, Path | None]:
    codex = shutil.which("codex")
    if not codex:
        if require_host:
            raise ValueError("Codex CLI is not available on PATH")
        return None, None
    host_value = os.environ.get(HOST_PATH_ENV)
    host = Path(host_value).expanduser() if host_value else Path(codex).resolve().with_name("codex-code-mode-host")
    if not host.is_file() or (os.name != "nt" and not os.access(host, os.X_OK)):
        if require_host:
            raise ValueError(f"matching executable codex-code-mode-host is required; set {HOST_PATH_ENV}")
        return Path(codex).resolve(), None
    return Path(codex).resolve(), host.resolve()


def check_only() -> dict[str, Any]:
    version = importlib.metadata.version("omnigent")
    if version != SDK_PIN:
        raise RuntimeError(f"native security bootstrap is pinned to omnigent=={SDK_PIN}, found {version}")
    _validate_agent()
    codex, host = _codex_binaries(require_host=False)
    route_available = False
    if host is not None:
        try:
            _verify_runtime_route()
            route_available = True
        except (ImportError, RuntimeError, ValueError, TypeError):
            route_available = False
    return {"status": "configuration_validated", "runtime_ready": False,
            "bootstrap_route_available": route_available,
            "live_execution_enabled": False, "guardrail_verified": False,
            "guardrail_status": "requested_unverified_not_effective", "runtime_blocker": RUNTIME_BLOCKER,
            "omnigent_version": version,
            "agent_yaml": str(AGENT.relative_to(ROOT)), "codex_cli": str(codex) if codex else None,
            "codex_code_mode_host": str(host) if host else None, "native_agent_tools": True,
            "model_calls": False, "science_calls": False}


def _verify_runtime_route() -> None:
    if importlib.metadata.version("omnigent") != SDK_PIN:
        raise RuntimeError("unsupported Omnigent version")
    from omnigent.inner import codex_executor
    from omnigent.runtime.harnesses import _HARNESS_MODULES

    init_parameters = __import__("inspect").signature(codex_executor.CodexExecutor.__init__).parameters
    turn_parameters = __import__("inspect").signature(codex_executor.CodexExecutor.run_turn).parameters
    if (not {"enable_web_search", "disable_native_tools", "skills_filter"}.issubset(init_parameters) or
            "config" not in turn_parameters or
            _HARNESS_MODULES.get("codex") != "omnigent.inner.codex_harness"):
        raise RuntimeError("pinned Codex constructor, turn, or harness registry API changed")


def _require_runtime_ready(check: dict[str, Any], *, enable_native_live: bool) -> None:
    """Check the pinned direct runner-to-harness bootstrap before touching context."""
    if not enable_native_live:
        raise RuntimeError("native adaptive live execution requires --enable-native-live")
    if not check.get("bootstrap_route_available"):
        raise RuntimeError("native adaptive live execution is disabled: " + RUNTIME_BLOCKER)


def _model_yaml(document: dict[str, Any], model: str | None) -> dict[str, Any]:
    """Return a temporary run spec with the requested model for every role."""
    import copy

    result = copy.deepcopy(document)
    if model is not None:
        result.setdefault("executor", {})["model"] = model
        for tool in result.get("tools", {}).values():
            if isinstance(tool, dict) and tool.get("type") == "agent":
                tool.setdefault("executor", {})["model"] = model
    return result


def _record(event_type: str, payload_ref: str | None = None) -> None:
    from nova.contracts import Mode
    from nova.live_bridge import _read_context
    from nova.storage import Storage

    _db, run_id = _read_context()
    Storage(_db).initialize().append_event(run_id, event_type, actor="host", mode=Mode.LIVE,
                                           payload_ref=payload_ref)


def _require_trusted_child() -> float:
    if os.environ.get(CHILD_MARKER) != "1" or os.environ.get(PARENT_PID_ENV) != str(os.getppid()):
        raise RuntimeError("trusted native child must be launched by the bounded parent entrypoint")
    raw_deadline = os.environ.get("NOVA_ADAPTIVE_BUDGET_DEADLINE")
    try:
        deadline = float(raw_deadline) if raw_deadline is not None else float("nan")
    except ValueError:
        deadline = float("nan")
    remaining = deadline - time.monotonic()
    if not math.isfinite(deadline) or not math.isfinite(remaining) or not 0 < remaining <= RUN_TIMEOUT_SECONDS:
        raise RuntimeError("trusted native child has no valid finite parent deadline")
    return remaining


def _create_native_audit(database: Path, run_id: str, model: str | None) -> Path:
    runs_root = (ROOT / "runs").resolve()
    run_dir = database.parent.resolve()
    if not run_dir.is_relative_to(runs_root) or not run_dir.is_dir() or database.is_symlink():
        raise ValueError("native trace requires an existing run-owned directory under runs/")
    path = run_dir / "native-model-audit.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    header = {"at": datetime.now(timezone.utc).isoformat(), "schema_version": 1,
              "event": "native_adaptive_trace_started", "run_id": run_id,
              "omnigent_version": SDK_PIN, "requested_model": model or "yaml-configured",
              "native_tools_policy_requested": "disabled",
              "web_search_policy_requested": "disabled",
              "guardrail_verification": "requested_unverified_not_effective",
              "skills": "none", "config_overrides": list(CONFIG_OVERRIDES)}
    try:
        os.write(fd, (json.dumps(header, sort_keys=True, separators=(",", ":")) + "\n").encode())
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return path


def _create_runtime_manifest(database: Path, run_id: str, model: str | None,
                             document: dict[str, Any]) -> Path:
    """Persist the effective, non-secret role configuration before dispatch."""
    run_dir = database.parent.resolve()
    path = run_dir / "native-runtime-manifest.json"
    roles = {"pi": document.get("executor", {}).get("model")}
    for name in ("planner", "skeptic", "runner"):
        item = document.get("tools", {}).get(name, {})
        roles[name] = item.get("executor", {}).get("model") if isinstance(item, dict) else None
    from nova import native_adaptive_runtime, native_adaptive_harness
    from omnigent.inner import codex_executor

    source_hashes = {}
    for label, source in (("runtime", Path(native_adaptive_runtime.__file__)),
                          ("harness", Path(native_adaptive_harness.__file__)),
                          ("codex_executor", Path(codex_executor.__file__))):
        source_hashes[label] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {"schema_version": 1, "run_id": run_id, "omnigent_version": SDK_PIN,
                "model_override": model, "effective_role_models": roles,
                "native_tools_policy_requested": "disabled",
                "web_search_policy_requested": "disabled",
                "guardrail_verification": "requested_unverified_not_effective",
                "skills": "none", "config_overrides": list(CONFIG_OVERRIDES),
                "guarded_runtime_source_sha256": source_hashes,
                "host_binary_env": HOST_PATH_ENV}
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, encoded)
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return path


def _run_native_adaptive_child(*, model: str | None = None, remaining_seconds: float = 600,
                               enable_native_live: bool = False) -> int:
    actual_remaining = _require_trusted_child()
    if model is not None and (not model or len(model) > 120):
        raise ValueError("model must be a nonempty configurable model name")
    if (isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or
            not math.isfinite(float(remaining_seconds)) or remaining_seconds <= 0 or remaining_seconds > RUN_TIMEOUT_SECONDS):
        raise ValueError(f"remaining_seconds must be in (0,{RUN_TIMEOUT_SECONDS}]")
    checked = check_only()
    if enable_native_live:
        _require_runtime_ready(checked, enable_native_live=True)
    else:
        _require_runtime_ready(checked)
    from nova.live_bridge import _read_context
    from nova.adaptive_agent_tools import _assert_fresh_followup, _parent

    expected_db = os.environ.get("NOVA_ADAPTIVE_EXPECTED_DATABASE")
    expected_run = os.environ.get("NOVA_ADAPTIVE_EXPECTED_RUN_ID")
    if not expected_db or not expected_run:
        raise RuntimeError("trusted child is missing its bound live context")
    db, run_id, store, _result, _spec = _parent()
    if db.resolve() != Path(expected_db).resolve() or run_id != expected_run:
        raise RuntimeError("native adaptive context differs from trusted parent binding")
    _assert_fresh_followup(db, run_id, store)
    import yaml
    rendered = _model_yaml(_load_yaml(), model)
    codex_host = Path(checked["codex_code_mode_host"])
    audit_path = _create_native_audit(db, run_id, model)
    _create_runtime_manifest(db, run_id, model, rendered)
    os.environ["NOVA_ADAPTIVE_TRACE_PATH"] = str(audit_path)
    os.environ["NOVA_ADAPTIVE_REMAINING_SECONDS"] = str(actual_remaining)
    import omnigent.cli as cli_module
    prompt = (
        "Begin the native adaptive workflow on the current host-owned live context. "
        "Dispatch Planner, then Skeptic, commit one feasible option or stop, and if an ID is returned "
        "dispatch Runner with exactly that ID. Return the actual tool Result summary."
    )
    with tempfile.TemporaryDirectory(prefix="nova-native-adaptive-") as temp_dir:
        agent_path = Path(temp_dir) / "adaptive-live.yaml"
        agent_path.write_text(yaml.safe_dump(rendered, sort_keys=False), encoding="utf-8")
        stdout = io.StringIO()
        try:
            cli_args = ["run", str(agent_path), "--no-session"]
            if model is not None:
                cli_args.extend(["--model", model])
            cli_args.extend(["-p", prompt])
            from nova.native_adaptive_runtime import launch_cli_with_guarded_runner
            with redirect_stdout(stdout):
                launch_cli_with_guarded_runner(cli_module, cli_args, ROOT, codex_host)
            transcript = stdout.getvalue().strip()
        except BaseException:
            _record("native_adaptive_orchestration_failed")
            raise
    if transcript:
        print(transcript)
    if not transcript:
        _record("native_adaptive_orchestration_failed")
        raise RuntimeError("Omnigent native CLI returned no supervisor response")
    from nova.native_adaptive_runtime import verify_executor_trace
    executor_verification = verify_executor_trace(audit_path, codex_host)
    from nova.adaptive_agent_tools import record_supervisor_response
    record_supervisor_response(transcript)
    # A concise manifest event intentionally records no prompt, credentials,
    # or model transcript; Planner/Skeptic/PI/Runner tool packets and Result
    # references are run-owned in SQLite.
    _record("native_adaptive_orchestration_completed")
    print(json.dumps({"status": "completed", "run_id": run_id, "model": model or "yaml-configured",
                      "omnigent_version": checked["omnigent_version"],
                      "guardrail_verified": True,
                      **executor_verification}, sort_keys=True))
    return 0


def run_native_adaptive(*, model: str | None = None, remaining_seconds: float = 600,
                        enable_native_live: bool = False) -> int:
    """Run the isolated native CLI child under one hard whole-run deadline."""
    if model is not None and (not model or len(model) > 120):
        raise ValueError("model must be a nonempty configurable model name")
    if (isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or
            not math.isfinite(float(remaining_seconds)) or not 0 < remaining_seconds <= RUN_TIMEOUT_SECONDS):
        raise ValueError(f"remaining_seconds must be in (0,{RUN_TIMEOUT_SECONDS}]")
    checked = check_only()
    if enable_native_live:
        _require_runtime_ready(checked, enable_native_live=True)
    else:
        _require_runtime_ready(checked)
    from nova.live_bridge import _read_context
    from nova.adaptive_agent_tools import _assert_fresh_followup, _parent

    database, run_id = _read_context()
    checked_db, checked_run, store, _result, _spec = _parent()
    if database.resolve() != checked_db.resolve() or run_id != checked_run:
        raise ValueError("native adaptive context changed during preflight")
    _assert_fresh_followup(database, run_id, store)
    _record("native_adaptive_orchestration_started")
    deadline = time.monotonic() + min(float(remaining_seconds), RUN_TIMEOUT_SECONDS)
    child_env = dict(os.environ)
    child_env["NOVA_ADAPTIVE_BUDGET_DEADLINE"] = str(deadline)
    child_env["NOVA_ADAPTIVE_REMAINING_SECONDS"] = str(float(remaining_seconds))
    child_env[CHILD_MARKER] = "1"
    child_env[PARENT_PID_ENV] = str(os.getpid())
    child_env["NOVA_ADAPTIVE_EXPECTED_RUN_ID"] = checked_run
    child_env["NOVA_ADAPTIVE_EXPECTED_DATABASE"] = str(checked_db.resolve())
    command = [sys.executable, str(Path(__file__).resolve()), "--_trusted-child",
               "--remaining-seconds", str(float(remaining_seconds))]
    if model is not None:
        command.extend(["--model", model])
    if enable_native_live:
        command.append("--enable-native-live")
    process = subprocess.Popen(command, cwd=ROOT, env=child_env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               start_new_session=(os.name == "posix"))
    try:
        output, _ = process.communicate(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait(timeout=2)
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        _record("native_adaptive_orchestration_failed")
        raise TimeoutError("native adaptive workflow exceeded its whole-run deadline") from None
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if process.returncode != 0:
        _record("native_adaptive_orchestration_failed")
        raise RuntimeError(f"Omnigent native adaptive CLI exited with status {process.returncode}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="validate installed CLI/YAML without model or science calls")
    parser.add_argument("--model", help="optional model override for PI and every specialist; defaults to YAML")
    parser.add_argument("--remaining-seconds", type=float, default=600)
    parser.add_argument("--enable-native-live", action="store_true",
                        help="authorize native model and science dispatch through the guarded Omnigent harness")
    parser.add_argument("--_trusted-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check_only:
        print(json.dumps(check_only(), sort_keys=True))
        return 0
    if args._trusted_child:
        return _run_native_adaptive_child(model=args.model, remaining_seconds=args.remaining_seconds,
                                          enable_native_live=args.enable_native_live)
    return run_native_adaptive(model=args.model, remaining_seconds=args.remaining_seconds,
                               enable_native_live=args.enable_native_live)


if __name__ == "__main__":
    raise SystemExit(main())
