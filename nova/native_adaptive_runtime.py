"""Pinned Omnigent 0.16.0 runner and Codex harness bootstrap.

The CLI runner and each harness are separate processes. The CLI installs the
runner bootstrap; the runner redirects only the ``codex`` registry entry to
the guarded native harness below. These hooks intentionally fail closed when
the pinned internal interfaces move.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import runpy
import stat
import sys
from pathlib import Path
from typing import Any

SDK_PIN = "0.16.0"
RUNS_ROOT = Path(__file__).resolve().parents[1] / "runs"
HOST_PATH_ENV = "CODEX_CODE_MODE_HOST_PATH"
CONFIG_OVERRIDES = ("features.code_mode_host=true", "features.code_mode=false", 'web_search="disabled"')


def _trace(event: str, **fields: Any) -> None:
    from nova.adaptive_agent_tools import record_native_trace

    status = fields.pop("status", None)
    model = fields.pop("model", None)
    pid = fields.pop("pid", None)
    role = fields.pop("role", None)
    record_native_trace(event, actor="native-adaptive-runtime", model=model, status=status,
                        pid=pid, role=role, details=fields)


def _record_private_executor_error(trace_path: Path, *, pid: int, role: str | None,
                                  error: Any) -> dict[str, Any]:
    """Append bounded provider diagnostics privately; return only safe summary fields."""
    message = error.message if isinstance(getattr(error, "message", None), str) else ""
    summary = {"error_category": "executor_error",
               "error_message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
               "retryable": bool(getattr(error, "retryable", False))}
    run_dir = trace_path.parent.resolve()
    runs_root = RUNS_ROOT.resolve()
    if (not run_dir.is_relative_to(runs_root) or trace_path.name != "native-model-audit.jsonl" or
            trace_path.is_symlink() or not trace_path.is_file()):
        raise ValueError("executor error trace is outside the run-owned evidence directory")
    raw_usage = getattr(error, "usage", None)
    usage = {}
    if isinstance(raw_usage, dict):
        for key, value in list(raw_usage.items())[:32]:
            if isinstance(key, str) and isinstance(value, (str, int, float, bool, type(None))):
                usage[key[:100]] = value[:500] if isinstance(value, str) else value
    record = {"schema_version": 1, "pid": pid, "role": role,
              "message": message[:4096], "message_truncated": len(message) > 4096,
              "full_message_sha256": summary["error_message_sha256"],
              "retryable": summary["retryable"], "usage": usage}
    path = run_dir / "native-executor-errors.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) |
                 getattr(os, "O_NONBLOCK", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("executor error log is not a regular file")
        os.fchmod(fd, 0o600)
        body = (json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        if os.write(fd, body) != len(body):
            raise OSError("short write while recording executor error")
    finally:
        os.close(fd)
    return summary


def _trace_executor_failure(trace_path: Path, *, pid: int, role: str | None,
                            model: str | None, error: Any) -> None:
    try:
        summary = _record_private_executor_error(trace_path, pid=pid, role=role, error=error)
    except Exception:
        summary = {"error_category": "executor_error",
                   "retryable": bool(getattr(error, "retryable", False))}
    from nova.adaptive_agent_tools import record_native_trace

    record_native_trace("turn_failed", actor="codex-model", model=model, pid=pid,
                        role=role, status="error", details=summary)


def _write_final_pi_response(trace_path: Path, *, pid: int, role: str,
                             freeze_call_id: str, response: str) -> Path:
    """Write the exact post-freeze TurnComplete response once beside its trace."""
    run_dir = trace_path.parent.resolve()
    runs_root = RUNS_ROOT.resolve()
    if (not run_dir.is_relative_to(runs_root) or trace_path.name != "native-model-audit.jsonl" or
            trace_path.is_symlink() or not trace_path.is_file()):
        raise ValueError("final PI response trace is outside the run-owned evidence directory")
    if (pid < 1 or role != "pi" or not freeze_call_id or len(freeze_call_id) > 120 or
            not isinstance(response, str) or not response.strip() or len(response) > 20_000):
        raise ValueError("final PI response record fields are invalid")
    record = {"schema_version": 1, "pid": pid, "role": role,
              "freeze_call_id": freeze_call_id, "response_text": response,
              "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
              "response_chars": len(response)}
    path = run_dir / "native-final-pi-response.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        body = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if os.write(fd, body) != len(body):
            raise OSError("short write while storing final PI response")
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return path


def _write_holdout_result_once(trace_path: Path, *, pid: int, call_id: str,
                               result: dict[str, Any]) -> dict[str, Any]:
    """Persist the host tool's actual Result mapping, bound to its native call."""
    run_dir = trace_path.parent.resolve()
    if (not run_dir.is_relative_to(RUNS_ROOT.resolve()) or trace_path.name != "native-model-audit.jsonl" or
            trace_path.is_symlink() or not trace_path.is_file() or
            not isinstance(result, dict) or len(call_id) > 120):
        raise ValueError("holdout Result is outside the bounded run-owned evidence contract")
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False, default=str).encode("utf-8")
    if len(encoded) > 1_000_000:
        raise ValueError("holdout Result exceeds the private evidence size bound")
    digest = hashlib.sha256(encoded).hexdigest()
    record = {"schema_version": 1, "pid": pid, "role": "holdout_runner",
              "tool": "execute_frozen_native_holdout", "call_id": call_id,
              "result_sha256": digest, "result": result}
    body = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=str).encode("utf-8")
    path = run_dir / "native-holdout-result.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.write(fd, body) != len(body):
            raise OSError("short write while storing native holdout Result")
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return {"result_sha256": digest, "result_id": result.get("result_id"),
            "execution_status": result.get("execution_status") or result.get("status")}


def read_final_pi_response(trace_path: Path) -> dict[str, Any]:
    """Read and validate the unique private response file for this run trace."""
    run_dir = trace_path.parent.resolve()
    runs_root = RUNS_ROOT.resolve()
    if (not run_dir.is_relative_to(runs_root) or trace_path.name != "native-model-audit.jsonl" or
            trace_path.is_symlink() or not trace_path.is_file()):
        raise RuntimeError("final PI response trace is outside the run-owned evidence directory")
    path = run_dir / "native-final-pi-response.json"
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 100_000:
            raise ValueError
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            record = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise RuntimeError("final PI response record is missing or unsafe") from None
    finally:
        if "fd" in locals() and isinstance(fd, int) and fd >= 0:
            os.close(fd)
    if (not isinstance(record, dict) or set(record) != {"schema_version", "pid", "role", "freeze_call_id",
            "response_text", "response_sha256", "response_chars"} or record.get("schema_version") != 1 or
            isinstance(record.get("pid"), bool) or not isinstance(record.get("pid"), int) or
            record.get("pid") < 1 or record.get("role") != "pi" or
            not isinstance(record.get("freeze_call_id"), str) or not record["freeze_call_id"] or
            not isinstance(record.get("response_text"), str) or not record["response_text"].strip() or
            len(record["response_text"]) > 20_000 or record.get("response_chars") != len(record["response_text"]) or
            record.get("response_sha256") != hashlib.sha256(record["response_text"].encode("utf-8")).hexdigest()):
        raise RuntimeError("final PI response record failed integrity validation")
    return record


def read_native_holdout_result(trace_path: Path) -> dict[str, Any]:
    """Read the single full Result captured from the successful host tool return."""
    run_dir = trace_path.parent.resolve()
    if (not run_dir.is_relative_to(RUNS_ROOT.resolve()) or trace_path.name != "native-model-audit.jsonl" or
            trace_path.is_symlink() or not trace_path.is_file()):
        raise RuntimeError("native holdout Result trace is outside the run evidence directory")
    path = run_dir / "native-holdout-result.json"
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 1_100_000:
            raise ValueError
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            record = json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise RuntimeError("native holdout Result record is missing or unsafe") from None
    finally:
        if "fd" in locals() and isinstance(fd, int) and fd >= 0:
            os.close(fd)
    if (not isinstance(record, dict) or set(record) != {"schema_version", "pid", "role", "tool", "call_id",
            "result_sha256", "result"} or record.get("schema_version") != 1 or record.get("role") != "holdout_runner" or
            record.get("tool") != "execute_frozen_native_holdout" or not isinstance(record.get("pid"), int) or
            isinstance(record.get("pid"), bool) or not isinstance(record.get("call_id"), str) or
            not isinstance(record.get("result"), dict)):
        raise RuntimeError("native holdout Result record fields are invalid")
    encoded = json.dumps(record["result"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False, default=str).encode("utf-8")
    if record["result_sha256"] != hashlib.sha256(encoded).hexdigest():
        raise RuntimeError("native holdout Result record failed integrity validation")
    return record


def _decode_native_function_result(value: Any) -> dict[str, Any] | None:
    """Decode a bounded native tool result without evaluating executable text."""
    candidate = value
    if isinstance(candidate, dict) and set(candidate) == {"result"}:
        candidate = candidate["result"]
    if isinstance(candidate, str):
        raw_candidate = candidate
        if len(raw_candidate.encode("utf-8")) > 256_000:
            return None
        try:
            import ast

            parsed = ast.parse(raw_candidate, mode="eval")
            stack = [(parsed, 0)]
            count = 0
            while stack:
                node, depth = stack.pop()
                count += 1
                if count > 20_000 or depth > 80:
                    return None
                stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
            candidate = ast.literal_eval(parsed)
        except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
            try:
                candidate = json.loads(raw_candidate)
            except (json.JSONDecodeError, TypeError):
                return None
    if isinstance(candidate, dict) and set(candidate) <= {"content", "isError"} and "content" in candidate:
        content = candidate.get("content")
        if candidate.get("isError", False) is not False or not isinstance(content, list) or len(content) != 1:
            return None
        block = content[0]
        if not isinstance(block, dict) or set(block) != {"type", "text"} or block.get("type") != "text":
            return None
        try:
            candidate = json.loads(block["text"])
        except (json.JSONDecodeError, TypeError):
            return None
    return dict(candidate) if isinstance(candidate, dict) else None


def install_codex_guardrails(host_path: str | Path) -> dict[str, Any]:
    """Install pinned constructor enforcement and prompt-free turn tracing."""
    if importlib.metadata.version("omnigent") != SDK_PIN:
        raise RuntimeError("refusing native adaptive Codex bootstrap against an unverified Omnigent version")
    from omnigent.inner import codex_executor
    from omnigent.inner.executor import ExecutorError, ToolCallComplete, ToolCallRequest, TurnComplete
    from nova.adaptive_agent_tools import record_native_trace

    cls = codex_executor.CodexExecutor
    original_init = cls.__init__
    original_turn = cls.run_turn
    original_spawn = codex_executor._create_subprocess_exec
    if getattr(cls, "_nova_native_adaptive_guarded", False):
        return {"constructor_patched": True, "turn_trace_patched": True, "already_installed": True}

    def guarded_init(self, *args, **kwargs):
        kwargs["enable_web_search"] = False
        kwargs["disable_native_tools"] = True
        kwargs["skills_filter"] = "none"
        original_init(self, *args, **kwargs)
        if not isinstance(getattr(self, "_env", None), dict) or not isinstance(getattr(self, "_codex_config_overrides", None), list):
            raise RuntimeError("pinned Omnigent Codex guard fields changed")
        for item in CONFIG_OVERRIDES:
            if item not in self._codex_config_overrides:
                self._codex_config_overrides.append(item)
        host = Path(host_path)
        if not host.is_file() or (os.name != "nt" and not os.access(host, os.X_OK)):
            raise RuntimeError("verified codex-code-mode-host binary is unavailable")
        self._env[HOST_PATH_ENV] = str(host.resolve())
        if self._enable_web_search is not False or self._disable_native_tools is not True or self._skills_filter != "none":
            raise RuntimeError("Codex executor guard values did not take effect")
        model = getattr(self, "_model_override", None)
        if model:
            os.environ["NOVA_ADAPTIVE_MODEL"] = str(model)[:120]
        agent_name = getattr(self, "_agent_name", None)
        role = None
        if isinstance(agent_name, str):
            normalized = agent_name.strip().lower()
            roles = {"planner", "skeptic", "runner", "holdout_runner"}
            role = "pi" if normalized == "nova-mat-native-adaptive-live" else normalized
            if role == "skeptic_final":
                role = "skeptic"
            if role in roles | {"pi"}:
                os.environ["NOVA_ADAPTIVE_ROLE"] = role
            else:
                role = None
        _trace("executor_guard_installed", agent=getattr(self, "_agent_name", None),
               model=model, pid=os.getpid(), role=role, native_tools_disabled=True,
               web_search_disabled=True, skills="none", host_binary=str(host.resolve()),
               config_overrides=list(self._codex_config_overrides))

    async def traced_turn(self, *args, **kwargs):
        config = kwargs.get("config")
        model = getattr(config, "model", None) or getattr(self, "_model_override", None)
        role = os.environ.get("NOVA_ADAPTIVE_ROLE")
        _trace("executor_turn_started", agent=getattr(self, "_agent_name", None), model=model,
               pid=os.getpid(), role=role)
        runner_ids: dict[str, str] = {}
        successful_freeze_call_id: str | None = None
        async for event in original_turn(self, *args, **kwargs):
            if isinstance(event, ToolCallRequest):
                md = event.metadata if isinstance(event.metadata, dict) else {}
                call_id = str(md.get("call_id") or md.get("id") or "")[:120] or None
                args_map = event.args if isinstance(event.args, dict) else {}
                if event.name == "execute_selected_adaptive":
                    registered_id = args_map.get("registered_id")
                    if isinstance(registered_id, str):
                        runner_ids[call_id or ""] = registered_id
                record_native_trace("tool_request", actor="codex-model", tool=event.name,
                                    call_id=call_id, args=event.args, model=model, pid=os.getpid(), role=role)
            elif isinstance(event, ToolCallComplete):
                md = event.metadata if isinstance(event.metadata, dict) else {}
                call_id = str(md.get("call_id") or md.get("id") or "")[:120] or None
                structured_result = None
                if event.name == "execute_selected_adaptive":
                    from nova.adaptive_agent_tools import _decode_native_runner_tool_result

                    registered_id = runner_ids.get(call_id or "")
                    if registered_id is None:
                        raise RuntimeError("Runner completion has no matching registered-ID request")
                    structured_result = _decode_native_runner_tool_result(event.result, registered_id)
                elif event.name in {"record_adaptive_review", "submit_native_final_review", "freeze_native_final_protocol"}:
                    structured_result = _decode_native_function_result(event.result)
                elif event.name == "execute_frozen_native_holdout":
                    structured_result = _decode_native_function_result(event.result)
                record_native_trace("tool_complete", actor="omnigent-tool-dispatch", tool=event.name,
                                    call_id=call_id,
                                    result=event.result, model=model, pid=os.getpid(),
                                    role=role,
                                    structured_result=structured_result,
                                    status=getattr(event.status, "value", str(event.status)))
                if (event.name == "execute_frozen_native_holdout" and role == "holdout_runner" and
                        structured_result is not None and call_id and
                        str(getattr(event.status, "value", event.status)).lower() in
                        {"success", "toolcallstatus.success"}):
                    _write_holdout_result_once(Path(os.environ["NOVA_ADAPTIVE_TRACE_PATH"]),
                                               pid=os.getpid(), call_id=call_id,
                                               result=structured_result)
                if (event.name == "freeze_native_final_protocol" and role == "pi" and
                        structured_result is not None and
                        str(getattr(event.status, "value", event.status)).lower() in
                        {"success", "toolcallstatus.success"} and call_id):
                    successful_freeze_call_id = call_id
            elif isinstance(event, TurnComplete):
                response = event.response or ""
                record_native_trace("turn_complete", actor="codex-model", model=model, pid=os.getpid(),
                                    role=role,
                                    result={"response_sha256": hashlib.sha256(response.encode()).hexdigest(),
                                            "response_chars": len(response)},
                                    usage=dict(event.usage) if isinstance(event.usage, dict) else None,
                                    status="completed")
                if successful_freeze_call_id is not None:
                    trace_path = Path(os.environ["NOVA_ADAPTIVE_TRACE_PATH"])
                    _write_final_pi_response(trace_path, pid=os.getpid(), role=role or "",
                                             freeze_call_id=successful_freeze_call_id,
                                             response=response)
            elif isinstance(event, ExecutorError):
                _trace_executor_failure(Path(os.environ["NOVA_ADAPTIVE_TRACE_PATH"]), pid=os.getpid(),
                                        role=role, model=model, error=event)
            yield event

    cls.__init__ = guarded_init
    cls.run_turn = traced_turn
    async def same_group_spawn(*args, **kwargs):
        kwargs["start_new_session"] = False
        return await original_spawn(*args, **kwargs)

    codex_executor._create_subprocess_exec = same_group_spawn
    cls._nova_native_adaptive_guarded = True
    return {"constructor_patched": True, "turn_trace_patched": True, "already_installed": False}


def bootstrap_runner(root: str, host_path: str) -> None:
    """Redirect the runner's real Codex harness registry before session dispatch."""
    if importlib.metadata.version("omnigent") != SDK_PIN:
        raise RuntimeError("unsupported Omnigent runner version")
    if root not in sys.path:
        sys.path.insert(0, root)
    from omnigent.runtime.harnesses import _HARNESS_MODULES

    module = "nova.native_adaptive_harness"
    if _HARNESS_MODULES.get("codex") != "omnigent.inner.codex_harness":
        raise RuntimeError("Omnigent Codex harness registry changed")
    os.environ["NOVA_ADAPTIVE_CODEX_HOST_PATH"] = str(Path(host_path).resolve())
    os.environ["HARNESS_CODEX_MINIMAL_CONFIG"] = "1"
    os.environ["HARNESS_CODEX_DISABLE_NATIVE_TOOLS"] = "1"
    os.environ["HARNESS_CODEX_ENABLE_WEB_SEARCH"] = "0"
    os.environ["HARNESS_CODEX_SKILLS_FILTER"] = json.dumps("none")
    current_path = os.environ.get("PYTHONPATH", "")
    path_parts = current_path.split(os.pathsep) if current_path else []
    if root not in path_parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([root, *path_parts])
    _HARNESS_MODULES["codex"] = module
    _trace("runner_bootstrap_installed", pid=os.getpid(), harness_module=module,
           omnigent_version=SDK_PIN)


def runner_command(root: str, host_path: str) -> list[str]:
    """Return the exact isolated runner command with this repo's bootstrap."""
    code = (
        "import sys,runpy;"
        f"sys.path.insert(0,{root!r});"
        "from nova.native_adaptive_runtime import bootstrap_runner;"
        f"bootstrap_runner({root!r},{host_path!r});"
        "runpy.run_module('omnigent.runner._entry',run_name='__main__')"
    )
    return [sys.executable, "-P", "-c", code]


def launch_cli_with_guarded_runner(cli_module: Any, args: list[str], root: Path, host_path: Path) -> None:
    """Run Omnigent CLI, rewriting only its exact dedicated runner spawn."""
    import subprocess

    original_start = cli_module._start_cli_runner_process
    original_popen = subprocess.Popen
    rewrites = 0

    def guarded_start(**kwargs):
        return original_start(**kwargs)

    def targeted_popen(command, *popen_args, **popen_kwargs):
        nonlocal rewrites
        if command == [sys.executable, "-P", "-m", "omnigent.runner._entry"]:
            command = runner_command(str(root), str(host_path))
            rewrites += 1
            popen_kwargs["start_new_session"] = False
        elif (isinstance(command, (list, tuple)) and len(command) >= 4 and
              command[0] == sys.executable and list(command[1:4]) == ["-m", "omnigent.cli", "server"]):
            rewrites += 1
            popen_kwargs["start_new_session"] = False
        return original_popen(command, *popen_args, **popen_kwargs)

    cli_module._start_cli_runner_process = guarded_start
    subprocess.Popen = targeted_popen
    try:
        cli_module.cli.main(args=args, prog_name="omnigent", standalone_mode=False)
        if rewrites != 2:
            raise RuntimeError(f"expected one owned Omnigent server and runner spawn, observed {rewrites}")
    finally:
        subprocess.Popen = original_popen
        cli_module._start_cli_runner_process = original_start


def verify_executor_trace(path: Path, host_path: Path, *,
                          required_tools: tuple[str, ...] = (),
                          expected_holdout_id: str | None = None,
                          final_response: str | None = None,
                          final_response_record: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verify that every traced executor turn belongs to a guarded process."""
    from nova.adaptive_agent_tools import _valid_codex_config_overrides

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not any(row.get("event") == "runner_bootstrap_installed" for row in records):
        raise RuntimeError("native runner bootstrap did not produce child-process evidence")
    guards = {row.get("pid"): row for row in records if row.get("event") == "executor_guard_installed"}
    starts: dict[int, int] = {}
    ends: dict[int, int] = {}
    used: set[int] = set()
    for row in records:
        pid, event = row.get("pid"), row.get("event")
        if event in {"executor_turn_started", "tool_request", "tool_complete", "turn_complete", "turn_failed"}:
            if not isinstance(pid, int):
                raise RuntimeError("native executor trace omitted process identity")
            used.add(pid)
        if event == "executor_turn_started":
            starts[pid] = starts.get(pid, 0) + 1
        elif event in {"turn_complete", "turn_failed"}:
            ends[pid] = ends.get(pid, 0) + 1
        if event == "turn_failed":
            raise RuntimeError("native executor reported a failed model turn")
    if not used:
        raise RuntimeError("native executor process produced no model-turn trace")
    for pid in used:
        details = (guards.get(pid) or {}).get("details")
        if (not isinstance(details, dict) or details.get("native_tools_disabled") is not True or
                details.get("web_search_disabled") is not True or details.get("skills") != "none" or
                not _valid_codex_config_overrides(details.get("config_overrides")) or
                details.get("host_binary") != str(host_path.resolve())):
            raise RuntimeError("native executor PID has no matching verified guard record")
    for pid in used:
        if starts.get(pid, 0) != ends.get(pid, 0):
            raise RuntimeError("native executor has an incomplete or unmatched model turn")
    if not any(row.get("event") == "turn_complete" for row in records):
        raise RuntimeError("native run has no completed model turn")
    required_roles = {"record_adaptive_review": "skeptic",
                      "submit_native_final_review": "skeptic",
                      "freeze_native_final_protocol": "pi",
                      "execute_frozen_native_holdout": "holdout_runner"}
    for tool in required_tools:
        role = required_roles.get(tool)
        found = False
        for request_index, request in enumerate(records):
            pid, call_id = request.get("pid"), request.get("call_id")
            if (request.get("event") != "tool_request" or request.get("actor") != "codex-model" or
                    request.get("tool") != tool or request.get("role") != role or not call_id):
                continue
            if tool == "execute_frozen_native_holdout" and request.get("arg_names") != ["experiment_id"]:
                continue
            if (tool == "execute_frozen_native_holdout" and expected_holdout_id is not None and
                    request.get("args_sha256") != hashlib.sha256(json.dumps(
                        {"experiment_id": expected_holdout_id}, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")).hexdigest()):
                continue
            if not _has_trace_guard(records, pid, role, request_index):
                continue
            for complete_index in range(request_index + 1, len(records)):
                complete = records[complete_index]
                if (complete.get("event") != "tool_complete" or complete.get("actor") != "omnigent-tool-dispatch" or
                        complete.get("tool") != tool or complete.get("call_id") != call_id or
                        complete.get("pid") != pid or complete.get("role") != role or
                        str(complete.get("status", "")).lower() not in {"success", "toolcallstatus.success"} or
                        not complete.get("structured_result_sha256")):
                    continue
                if any(later.get("event") == "turn_complete" and later.get("actor") == "codex-model" and
                       later.get("pid") == pid and later.get("role") == role
                       for later in records[complete_index + 1:]):
                    found = True
                    break
            if found:
                break
        if not found:
            raise RuntimeError(f"native finalization tool {tool} lacks a guarded successful turn trace")
    if "execute_frozen_native_holdout" in required_tools:
        result_record = read_native_holdout_result(path)
        result = result_record["result"]
        if (not isinstance(result.get("result_id"), str) or not result.get("result_id") or
                not isinstance(result.get("execution_status"), str) or not result.get("execution_status")):
            raise RuntimeError("native holdout host return omitted Result ID or execution status")
        if expected_holdout_id is not None and result.get("experiment_id") != expected_holdout_id:
            raise RuntimeError("native holdout host return differs from the frozen experiment ID")
        if not any(row.get("event") == "tool_complete" and row.get("tool") == "execute_frozen_native_holdout" and
                   row.get("role") == "holdout_runner" and row.get("call_id") == result_record["call_id"] and
                   row.get("pid") == result_record["pid"] and
                   row.get("structured_result_sha256") == result_record["result_sha256"] and
                   str(row.get("status", "")).lower() in {"success", "toolcallstatus.success"}
                   for row in records):
            raise RuntimeError("native holdout Result is not bound to its guarded successful tool return")
    if final_response_record is not None and final_response is None:
        raise RuntimeError("final PI response record requires its exact response text")
    if final_response is not None:
        digest = hashlib.sha256(final_response.encode("utf-8")).hexdigest()
        response_record_hash = hashlib.sha256(json.dumps(
            {"response_sha256": digest, "response_chars": len(final_response)},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        freeze_completions = [i for i, row in enumerate(records)
                              if row.get("event") == "tool_complete" and row.get("tool") == "freeze_native_final_protocol"
                              and row.get("role") == "pi" and row.get("structured_result_sha256")]
        if final_response_record is not None:
            record = final_response_record
            if (record.get("schema_version") != 1 or record.get("role") != "pi" or
                    record.get("response_text") != final_response or
                    not isinstance(record.get("pid"), int) or isinstance(record.get("pid"), bool) or
                    record.get("response_chars") != len(final_response) or
                    record.get("response_sha256") != hashlib.sha256(final_response.encode("utf-8")).hexdigest() or
                    not isinstance(record.get("freeze_call_id"), str) or not record["freeze_call_id"]):
                raise RuntimeError("final PI response record does not match the captured response")
            freeze_completions = [i for i in freeze_completions
                                  if records[i].get("pid") == record["pid"] and
                                  records[i].get("call_id") == record.get("freeze_call_id") and
                                  records[i].get("actor") == "omnigent-tool-dispatch" and
                                  str(records[i].get("status", "")).lower() in
                                  {"success", "toolcallstatus.success"} and
                                  any(request.get("event") == "tool_request" and
                                      request.get("actor") == "codex-model" and
                                      request.get("tool") == "freeze_native_final_protocol" and
                                      request.get("call_id") == record.get("freeze_call_id") and
                                      request.get("pid") == record["pid"] and request.get("role") == "pi" and
                                      _has_trace_guard(records, record["pid"], "pi", request_index)
                                      for request_index, request in enumerate(records[:i]))]
        if not any(any(later.get("event") == "turn_complete" and later.get("role") == "pi" and
                       later.get("pid") == records[i].get("pid") and
                       later.get("actor") == "codex-model" and
                       (final_response_record is None or later.get("pid") == final_response_record["pid"]) and
                       later.get("result_sha256") == response_record_hash
                       for later in records[i + 1:]) for i in freeze_completions):
            raise RuntimeError("final PI response does not match the guarded freeze turn completion")
    return {"verified_executor_pids": sorted(used), "completed_turns": sum(ends.values())}


def _has_trace_guard(records: list[dict[str, Any]], pid: int, role: str | None, before: int) -> bool:
    from nova.adaptive_agent_tools import _valid_codex_config_overrides

    for row in records[:before]:
        details = row.get("details")
        if (row.get("event") == "executor_guard_installed" and row.get("pid") == pid and
                row.get("role") == role and isinstance(details, dict) and
                details.get("native_tools_disabled") is True and details.get("web_search_disabled") is True and
                details.get("skills") == "none" and _valid_codex_config_overrides(details.get("config_overrides")) and
                str(details.get("host_binary", "")).endswith("codex-code-mode-host")):
            return True
    return False
