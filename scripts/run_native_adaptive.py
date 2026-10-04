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
import re
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
AGENT_FINALIZE = ROOT / "agents" / "adaptive-finalize.yaml"
AGENT_HOLDOUT = ROOT / "agents" / "adaptive-holdout.yaml"
SDK_PIN = "0.16.0"
DEFAULT_MODEL = "gpt-6-luna"
CONFIG_OVERRIDES = ("features.code_mode_host=true", "features.code_mode=false", 'web_search="disabled"')
HOST_PATH_ENV = "CODEX_CODE_MODE_HOST_PATH"
RUN_TIMEOUT_SECONDS = 720
MAX_FAILURE_EVENT_REFS = 64
MAX_TERMINAL_CAPTURE_BYTES = 16 * 1024
_FAILURE_REASONS = frozenset({"child_nonzero", "workflow_deadline"})
_SAFE_EVENT_REF = re.compile(
    r"^(?:NOVA-(?:[0-9a-f]{16}|FINAL-[0-9a-f]{16}|HOLDOUT-[0-9a-f]{16})|"
    r"nova-result-[0-9a-f]{64}|sha256:[0-9a-f]{64})$"
)
CHILD_MARKER = "NOVA_ADAPTIVE_TRUSTED_CHILD"
PARENT_PID_ENV = "NOVA_ADAPTIVE_PARENT_PID"
HOLDOUT_APPROVAL_ENV = "NOVA_NATIVE_HOLDOUT_APPROVED"
OWNER_PID_ENV = "NOVA_ADAPTIVE_OWNER_PID"
RUNTIME_BLOCKER = ("Omnigent Codex executes in a per-conversation harness process; live dispatch requires "
                   "the pinned guarded harness bootstrap and executor trace in that process")

_FAILURE_STAGE_EVENTS = {
    "native_adaptive_orchestration_started": "orchestration_started",
    "native_adaptive_options_registered": "planner_options_registered",
    "native_adaptive_review_submitted": "skeptic_review_submitted",
    "native_adaptive_choice_committed": "pi_choice_committed",
    "native_adaptive_choice_failed": "pi_choice_failed",
    "native_adaptive_runner_started": "runner_started",
    "native_adaptive_runner_result_returned": "runner_result_returned",
    "native_adaptive_runner_failed": "runner_failed",
    "native_adaptive_supervisor_returned": "supervisor_returned",
    "native_adaptive_final_review_submitted": "final_review_submitted",
    "native_adaptive_final_review_failed": "final_review_failed",
    "native_adaptive_final_protocol_frozen": "final_protocol_frozen",
    "native_adaptive_final_protocol_freeze_failed": "final_protocol_freeze_failed",
    "result": "result_recorded",
    "holdout_running": "holdout_running",
    "holdout_result": "holdout_result_recorded",
    "holdout_failed": "holdout_failed",
    "native_adaptive_holdout_failed": "holdout_failed_or_partial",
}
_FAILURE_SIDE_EFFECT_EVENTS = frozenset({
    "native_adaptive_runner_started", "native_adaptive_runner_result_returned",
    "native_adaptive_runner_failed", "result", "holdout_running", "holdout_result",
    "holdout_failed",
    "native_adaptive_holdout_failed",
})
_HOLDOUT_EXECUTION_EVENTS = frozenset({"holdout_running", "holdout_result", "holdout_failed",
                                       "native_adaptive_holdout_failed"})


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


def _check_async_dispatch_surface(path: Path) -> dict[str, Any]:
    """Validate the pinned SDK's real translated async/sub-agent tool surface."""
    from omnigent.inner.loader import load_agent_def_from_path
    from omnigent.spec.omnigent import agent_def_to_agent_spec
    from omnigent.tools.manager import ToolManager

    raw = _load_yaml(path)
    if raw.get("async") is not True:
        raise ValueError(f"{path.name} must explicitly enable async sub-agent completion delivery")
    definition = load_agent_def_from_path(str(path))
    spec = agent_def_to_agent_spec(definition, raw_yaml=raw)
    manager = ToolManager(spec, sandbox_enabled=False)
    tools = set(manager._tools)
    required_async = {"sys_call_async", "sys_read_inbox", "sys_cancel_async"}
    if spec.name != "nova-mat-native-adaptive-live" or spec.async_enabled is not True:
        raise RuntimeError("pinned Omnigent conversion did not preserve the native PI async surface")
    if not required_async.issubset(tools) or "sys_session_send" not in tools:
        raise RuntimeError("pinned Omnigent PI tool manager lacks async inbox or declared sub-agent dispatch tools")
    return {"async_enabled": True, "required_async_tools": sorted(required_async),
            "sub_agent_dispatch_tool": "sys_session_send"}


def _finalization_yaml() -> dict[str, Any]:
    """Validate the native finalization stage run after adaptive response persistence."""
    from omnigent.inner.loader import load_agent_def_from_path

    base = _validate_agent(AGENT)
    fragment = _load_yaml(AGENT_FINALIZE)
    load_agent_def_from_path(str(AGENT_FINALIZE))
    if fragment.get("name") != base.get("name"):
        raise ValueError("finalization YAML must retain the native PI agent identity")
    expected = {
        "skeptic_final": {"type": "agent", "executor": {"harness": "codex"},
                          "tools": {"read_finalization_state": "nova.native_finalization_tools.read_finalization_state",
                                    "submit_native_final_review": "nova.native_finalization_tools.submit_native_final_review"}},
        "read_finalization_state": {"type": "function", "callable": "nova.native_finalization_tools.read_finalization_state"},
        "freeze_native_final_protocol": {"type": "function", "callable": "nova.native_finalization_tools.freeze_native_final_protocol"},
    }
    tools = fragment.get("tools")
    if not isinstance(tools, dict) or set(tools) != set(expected):
        raise ValueError("finalization YAML tool set differs from the bounded host contract")
    for name, contract in expected.items():
        item = tools[name]
        for key, value in contract.items():
            if key == "tools":
                actual = item.get("tools", {})
                if {tool_name: spec.get("callable") for tool_name, spec in actual.items()} != value:
                    raise ValueError("final Skeptic tool allowlist differs from host contract")
                if any(spec.get("type") != "function" for spec in actual.values()):
                    raise ValueError("final Skeptic may expose only the bounded native functions")
            elif key == "executor":
                executor = item.get("executor", {})
                model_name = executor.get("model")
                if (executor.get("harness") != value["harness"] or not isinstance(model_name, str) or
                        not model_name.strip() or len(model_name) > 120):
                    raise ValueError("final Skeptic must use a configurable Codex model")
            elif item.get(key) != value:
                raise ValueError(f"finalization tool {name} differs from its native host binding")
    if not getattr(load_agent_def_from_path(str(AGENT_FINALIZE)), "tools", None):
        raise ValueError("Omnigent parsed no tools from the finalization YAML")
    return fragment


def _holdout_yaml() -> dict[str, Any]:
    """Validate the isolated post-freeze Runner's parsed role and one-ID tool."""
    from omnigent.inner.loader import load_agent_def_from_path

    fragment = _load_yaml(AGENT_HOLDOUT)
    parsed = load_agent_def_from_path(str(AGENT_HOLDOUT))
    tools = fragment.get("tools")
    if (fragment.get("name") != _load_yaml().get("name") or not isinstance(tools, dict) or
            set(tools) != {"holdout_runner"}):
        raise ValueError("holdout YAML must retain PI identity and expose only holdout_runner")
    runner = tools["holdout_runner"]
    if runner.get("type") != "agent":
        raise ValueError("frozen holdout executor must be a distinct agent role")
    functions = runner.get("tools")
    expected = {"execute_frozen_native_holdout": "nova.native_holdout_tools.execute_frozen_native_holdout"}
    if (not isinstance(functions, dict) or
            {key: value.get("callable") for key, value in functions.items()} != expected or
            any(value.get("type") != "function" for value in functions.values())):
        raise ValueError("holdout Runner function allowlist differs from the one-ID host contract")
    schema = functions["execute_frozen_native_holdout"].get("parameters")
    if (not isinstance(schema, dict) or schema.get("required") != ["experiment_id"] or
            schema.get("additionalProperties") is not False or
            set(schema.get("properties", {})) != {"experiment_id"} or
            schema["properties"]["experiment_id"].get("type") != "string"):
        raise ValueError("holdout tool schema must accept only one experiment_id string")
    if not getattr(parsed, "tools", None):
        raise ValueError("Omnigent parsed no tools from the holdout YAML")
    return fragment


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


def check_only(*, finalize_discovery: bool = False, execute_frozen_holdout: bool = False) -> dict[str, Any]:
    version = importlib.metadata.version("omnigent")
    if version != SDK_PIN:
        raise RuntimeError(f"native security bootstrap is pinned to omnigent=={SDK_PIN}, found {version}")
    _validate_agent()
    async_dispatch_surface = _check_async_dispatch_surface(AGENT)
    if finalize_discovery:
        _finalization_yaml()
        _check_async_dispatch_surface(AGENT_FINALIZE)
    if execute_frozen_holdout:
        if not finalize_discovery:
            raise ValueError("--execute-frozen-holdout requires --finalize-discovery")
        _holdout_yaml()
        _check_async_dispatch_surface(AGENT_HOLDOUT)
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
            "agent_yaml": ([str(AGENT.relative_to(ROOT)), str(AGENT_FINALIZE.relative_to(ROOT))] +
                           ([str(AGENT_HOLDOUT.relative_to(ROOT))] if execute_frozen_holdout else [])
                           if finalize_discovery else str(AGENT.relative_to(ROOT))),
            "finalize_discovery": finalize_discovery,
            "execute_frozen_holdout": execute_frozen_holdout,
            "async_dispatch_surface": async_dispatch_surface,
            "codex_cli": str(codex) if codex else None,
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


def _require_runtime_ready(check: dict[str, Any], *, enable_native_live: bool = False) -> None:
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


def _record_finalization_response(database: Path, run_id: str, transcript: str) -> str:
    """Persist the bounded final PI reply separately from the adaptive response.

    This records the guarded TurnComplete response. It does not establish that the
    executor trace or final response hash has been verified, or that the run
    completed successfully.
    """
    from nova.contracts import Mode
    from nova.storage import Storage

    if not transcript.strip() or len(transcript) > 20_000:
        raise ValueError("native finalization PI response must contain 1-20000 characters")
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    store = Storage(database).initialize()
    if any(event.event_type == "native_finalization_supervisor_response" and event.actor == "pi"
           for event in store.list_events(run_id)):
        raise ValueError("a native finalization PI response is already persisted")
    import sqlite3
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS native_finalization_supervisor_results (
                     run_id TEXT PRIMARY KEY, response_text TEXT NOT NULL, response_sha256 TEXT NOT NULL)""")
        db.execute("INSERT INTO native_finalization_supervisor_results VALUES(?,?,?)",
                   (run_id, transcript, digest))
    store.append_event(run_id, "native_finalization_supervisor_response", actor="pi", mode=Mode.LIVE,
                       payload_ref=f"sha256:{digest}")
    return digest


def _capture_finalization_response_before_verification(
    database: Path, run_id: str, transcript: str, verifier: Any,
) -> str:
    """Persist the CLI reply before host verification, even when verification fails."""
    digest = _record_finalization_response(database, run_id, transcript)
    verifier()
    return digest


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
                             document: dict[str, Any], *, finalize_discovery: bool = False,
                             finalization_document: dict[str, Any] | None = None,
                             holdout_document: dict[str, Any] | None = None) -> Path:
    """Persist the effective, non-secret role configuration before dispatch."""
    run_dir = database.parent.resolve()
    path = run_dir / "native-runtime-manifest.json"
    roles = {"pi": document.get("executor", {}).get("model")}
    for name, item in document.get("tools", {}).items():
        if isinstance(item, dict) and item.get("type") == "agent":
            roles[name] = item.get("executor", {}).get("model")
    if finalization_document:
        for name, item in finalization_document.get("tools", {}).items():
            if isinstance(item, dict) and item.get("type") == "agent":
                roles[name] = item.get("executor", {}).get("model")
    if holdout_document:
        for name, item in holdout_document.get("tools", {}).items():
            if isinstance(item, dict) and item.get("type") == "agent":
                roles[name] = item.get("executor", {}).get("model")
    from nova import native_adaptive_runtime, native_adaptive_harness
    from omnigent.inner import codex_executor

    source_hashes = {}
    for label, source in (("runtime", Path(native_adaptive_runtime.__file__)),
                          ("harness", Path(native_adaptive_harness.__file__)),
                          ("codex_executor", Path(codex_executor.__file__))):
        source_hashes[label] = hashlib.sha256(source.read_bytes()).hexdigest()
    import yaml
    selected_yaml = yaml.safe_dump(document, sort_keys=False).encode()
    finalization_sha = None
    if finalize_discovery and finalization_document is not None:
        finalization_bytes = yaml.safe_dump(finalization_document, sort_keys=False).encode()
        selected_yaml += b"\0" + finalization_bytes
        from nova import native_finalization_tools
        source_hashes["native_finalization_tools"] = hashlib.sha256(
            Path(native_finalization_tools.__file__).read_bytes()).hexdigest()
        finalization_sha = hashlib.sha256(finalization_bytes).hexdigest()
    holdout_sha = None
    if holdout_document is not None:
        holdout_bytes = yaml.safe_dump(holdout_document, sort_keys=False).encode()
        selected_yaml += b"\0" + holdout_bytes
        holdout_sha = hashlib.sha256(holdout_bytes).hexdigest()
        from nova import native_holdout_tools
        from scripts import export_native_holdout_evidence
        source_hashes["native_holdout_tools"] = hashlib.sha256(
            Path(native_holdout_tools.__file__).read_bytes()).hexdigest()
        source_hashes["holdout_evidence_exporter"] = hashlib.sha256(
            Path(export_native_holdout_evidence.__file__).read_bytes()).hexdigest()
    manifest = {"schema_version": 1, "run_id": run_id, "omnigent_version": SDK_PIN,
                "model_override": model, "effective_role_models": roles,
                "finalize_discovery": finalize_discovery,
                "selected_yaml_sha256": hashlib.sha256(selected_yaml).hexdigest(),
                "base_yaml_sha256": hashlib.sha256(AGENT.read_bytes()).hexdigest(),
                "finalization_yaml_sha256": finalization_sha,
                "execute_frozen_holdout": holdout_document is not None,
                "holdout_yaml_sha256": holdout_sha,
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


def _failure_event_summary(database: Path, run_id: str) -> dict[str, Any]:
    """Summarize canonical run events without reading Specs, Results, or protocols."""
    from nova.storage import Storage

    events = Storage(database).list_events(run_id)
    relevant = [event for event in events if event.event_type in _FAILURE_STAGE_EVENTS]
    side_effects = [event for event in events if event.event_type in _FAILURE_SIDE_EFFECT_EVENTS]
    holdout_events = [event for event in relevant if event.event_type in _HOLDOUT_EXECUTION_EVENTS]
    bounded_refs = [
        {"event": event.event_type,
         "payload_ref": (event.payload_ref if isinstance(event.payload_ref, str) and
                         _SAFE_EVENT_REF.fullmatch(event.payload_ref) else "redacted")}
        for event in side_effects[-MAX_FAILURE_EVENT_REFS:]
    ]
    last_confirmed_stage = _FAILURE_STAGE_EVENTS[relevant[-1].event_type] if relevant else "unknown"
    return {
        "last_confirmed_stage": last_confirmed_stage,
        "scientific_tool_side_effects": {
            "observed_run_event_count": len(side_effects),
            "events": bounded_refs,
            "truncated": len(side_effects) > MAX_FAILURE_EVENT_REFS,
        },
        "final_protocol_frozen": any(
            event.event_type == "native_adaptive_final_protocol_frozen" for event in events
        ),
        # Event absence is not evidence that no other execution occurred.
        "holdout_execution_attestation": "observed" if holdout_events else "not_attested",
        "holdout_events": [
            {"event": event.event_type,
             "payload_ref": (event.payload_ref if isinstance(event.payload_ref, str) and
                             _SAFE_EVENT_REF.fullmatch(event.payload_ref) else "redacted")}
            for event in holdout_events[-MAX_FAILURE_EVENT_REFS:]
        ],
    }


def _write_failure_feedback(database: Path, run_id: str, *, reason_category: str,
                            original_exit_code: int | None, timeout: bool,
                            terminal_output: str | bytes | None) -> None:
    """Best-effort, private parent-side failure handoff; never inspect result payloads."""
    import os

    run_dir = database.parent.resolve(strict=True)
    runs_root = (ROOT / "runs").resolve(strict=True)
    if (database.is_symlink() or not run_dir.is_dir() or run_dir == runs_root or
            not run_dir.is_relative_to(runs_root)):
        raise ValueError("failure feedback requires the bound run database directory")
    if reason_category not in _FAILURE_REASONS:
        raise ValueError("failure reason category is not allowlisted")
    artifact_path = run_dir / "failure-feedback.json"
    if artifact_path.exists():
        raise FileExistsError("failure feedback already exists for this run directory")

    output_bytes: bytes | None
    if terminal_output is None:
        output_bytes = None
        output_chars = None
        output_sha256 = None
    elif isinstance(terminal_output, bytes):
        output_bytes = terminal_output
        output_chars = len(terminal_output.decode("utf-8", errors="replace"))
        output_sha256 = hashlib.sha256(terminal_output).hexdigest()
    else:
        output_bytes = terminal_output.encode("utf-8", errors="replace")
        output_chars = len(terminal_output)
        output_sha256 = hashlib.sha256(output_bytes).hexdigest()

    capture_name = None
    capture_truncated = False
    if output_bytes is not None and output_bytes:
        capture_path = run_dir / "terminal-capture.txt"
        captured = output_bytes[:MAX_TERMINAL_CAPTURE_BYTES]
        capture_truncated = len(output_bytes) > len(captured)
        fd = os.open(capture_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(captured)
        finally:
            os.close(fd)
        capture_name = capture_path.name

    summary = {
        "schema": "nova.native_failure_feedback",
        "schema_version": 1,
        "run_id": run_id,
        **_failure_event_summary(database, run_id),
        "original_exit_code": original_exit_code,
        "timeout": timeout,
        "outcome": "failed",
        "reason_category": reason_category,
        "terminal_output_sha256": output_sha256,
        "terminal_output_chars": output_chars,
        "terminal_capture_file": capture_name,
        "terminal_capture_truncated": capture_truncated,
        "safe_next_action": "Inspect bounded event refs and private capture; use mock/offline diagnosis before any newly authorized run. Never retry this run in place.",
    }
    encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    fd = os.open(artifact_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(encoded)
    finally:
        os.close(fd)


def _best_effort_failure_feedback(database: Path, run_id: str, **kwargs: Any) -> None:
    """Do not let diagnostic artifact failures replace the original child error."""
    try:
        _write_failure_feedback(database, run_id, **kwargs)
    except Exception:
        return


def _run_omnigent_cli_session(cli_module: Any, document: dict[str, Any], *, prompt: str,
                              model: str | None, codex_host: Path, prefix: str) -> str:
    import yaml
    from nova.native_adaptive_runtime import launch_cli_with_guarded_runner

    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
        agent_path = Path(temp_dir) / "adaptive-agent.yaml"
        agent_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        stdout = io.StringIO()
        cli_args = ["run", str(agent_path), "--no-session"]
        if model is not None:
            cli_args.extend(["--model", model])
        cli_args.extend(["-p", prompt])
        with redirect_stdout(stdout):
            launch_cli_with_guarded_runner(cli_module, cli_args, ROOT, codex_host)
        return stdout.getvalue().strip()


def _run_native_adaptive_child(*, model: str | None = None, remaining_seconds: float = 600,
                               enable_native_live: bool = False,
                               finalize_discovery: bool = False,
                               execute_frozen_holdout: bool = False) -> int:
    if execute_frozen_holdout:
        if not finalize_discovery or not enable_native_live or os.environ.get(HOLDOUT_APPROVAL_ENV) != "1":
            raise RuntimeError("frozen holdout requires trusted opt-in, finalization, and native live")
    actual_remaining = _require_trusted_child()
    # Omnigent sessions/tools run in descendants of this child. Bind host calls
    # to this owner's process group instead of requiring an incorrect direct parent.
    os.environ[OWNER_PID_ENV] = str(os.getpid())
    if model is not None and (not model or len(model) > 120):
        raise ValueError("model must be a nonempty configurable model name")
    if (isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or
            not math.isfinite(float(remaining_seconds)) or remaining_seconds <= 0 or remaining_seconds > RUN_TIMEOUT_SECONDS):
        raise ValueError(f"remaining_seconds must be in (0,{RUN_TIMEOUT_SECONDS}]")
    checked = check_only(finalize_discovery=finalize_discovery,
                         execute_frozen_holdout=execute_frozen_holdout)
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
    rendered = _model_yaml(_load_yaml(), model)
    finalization_document = _model_yaml(_finalization_yaml(), model) if finalize_discovery else None
    holdout_document = _model_yaml(_holdout_yaml(), model) if execute_frozen_holdout else None
    codex_host = Path(checked["codex_code_mode_host"])
    audit_path = _create_native_audit(db, run_id, model)
    _create_runtime_manifest(db, run_id, model, rendered, finalize_discovery=finalize_discovery,
                             finalization_document=finalization_document,
                             holdout_document=holdout_document)
    os.environ["NOVA_ADAPTIVE_TRACE_PATH"] = str(audit_path)
    os.environ["NOVA_ADAPTIVE_REMAINING_SECONDS"] = str(actual_remaining)
    import omnigent.cli as cli_module
    prompt = (
        "Begin the native adaptive workflow on the current host-owned live context. "
        "Dispatch Planner, then Skeptic, commit one feasible option or stop, and if an ID is returned "
        "dispatch Runner with exactly that ID. Return the actual tool Result summary."
    )
    try:
        transcript = _run_omnigent_cli_session(cli_module, rendered, prompt=prompt, model=model,
                                               codex_host=codex_host, prefix="nova-native-adaptive-")
    except BaseException:
        _record("native_adaptive_orchestration_failed")
        raise
    if not transcript:
        _record("native_adaptive_orchestration_failed")
        raise RuntimeError("Omnigent native CLI returned no supervisor response")
    print(transcript, flush=True)
    from nova.adaptive_agent_tools import record_supervisor_response
    record_supervisor_response(transcript)

    finalization_transcript = ""
    finalization_response_record = None
    finalization_response_sha256 = None
    finalization_status = None
    holdout_execution: dict[str, Any] | None = None
    if finalize_discovery:
        from nova.native_finalization_tools import read_finalization_state

        initial_finalization_state = read_finalization_state()
        if not isinstance(initial_finalization_state, dict):
            raise RuntimeError("native finalization state is not a host-owned mapping")
        if initial_finalization_state.get("supported") is False:
            reason = initial_finalization_state.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise RuntimeError("unsupported finalization state omitted its reason")
            finalization_status = {"status": "not_supported", "reason": reason}
        else:
            if initial_finalization_state.get("stage") != "ready":
                raise RuntimeError("native finalization is not ready after the adaptive response")
            followup = initial_finalization_state.get("followup_result")
            followup_result = followup.get("result") if isinstance(followup, dict) else None
            followup_result_id = followup_result.get("result_id") if isinstance(followup_result, dict) else None
            if not isinstance(followup_result_id, str) or not followup_result_id:
                raise RuntimeError("native finalization has no bound follow-up Result ID")
            try:
                finalization_display = _run_omnigent_cli_session(
                    cli_module, finalization_document, prompt=finalization_document["prompt"],
                    model=model, codex_host=codex_host, prefix="nova-native-finalize-")
            except BaseException:
                _record("native_adaptive_orchestration_failed")
                raise
            if not finalization_display:
                raise RuntimeError("Omnigent finalization CLI returned no PI response")
            print("Omnigent CLI display (not used as the PI reply):", flush=True)
            print(finalization_display, flush=True)
            from nova.native_adaptive_runtime import read_final_pi_response, verify_executor_trace
            finalization_response_record = read_final_pi_response(audit_path)
            finalization_transcript = finalization_response_record["response_text"]
            finalization_response_sha256 = _capture_finalization_response_before_verification(
                db, run_id, finalization_transcript,
                lambda: verify_executor_trace(
                    audit_path, codex_host,
                    required_tools=("record_adaptive_review", "submit_native_final_review",
                                    "freeze_native_final_protocol"),
                    final_response=finalization_transcript,
                    final_response_record=finalization_response_record,
                ),
            )
            from nova.contracts import Mode
            from nova.storage import Storage
            Storage(db).initialize().append_event(
                run_id, "native_adaptive_finalization_supervisor_returned", actor="host",
                mode=Mode.LIVE, payload_ref=followup_result_id)
            persisted = read_finalization_state()
            final_protocol = persisted.get("final_protocol") if isinstance(persisted, dict) else None
            if (not isinstance(persisted, dict) or persisted.get("supported") is not True or
                    persisted.get("stage") != "frozen_unexecuted" or not persisted.get("final_review") or
                    not isinstance(final_protocol, dict) or
                    not isinstance(final_protocol.get("holdout_experiment_id"), str) or
                    not isinstance(final_protocol.get("protocol_sha256"), str)):
                raise RuntimeError("host did not persist the requested unexecuted final protocol")
            finalization_status = {"status": "frozen_unexecuted",
                                   "holdout_experiment_id": final_protocol["holdout_experiment_id"],
                                   "protocol_sha256": final_protocol["protocol_sha256"]}
    required_final_tools = ("record_adaptive_review", "submit_native_final_review",
                            "freeze_native_final_protocol") if finalization_transcript else ()
    executor_verification = verify_executor_trace(audit_path, codex_host,
                                                 required_tools=required_final_tools,
                                                 final_response=finalization_transcript or None,
                                                 final_response_record=(finalization_response_record
                                                                        if finalization_transcript else None))
    if execute_frozen_holdout and finalization_status and finalization_status.get("status") == "frozen_unexecuted":
        from nova.native_finalization_tools import read_finalization_state

        state = read_finalization_state()
        protocol = state.get("final_protocol") if isinstance(state, dict) else None
        holdout_id = protocol.get("holdout_experiment_id") if isinstance(protocol, dict) else None
        if (state.get("supported") is not True or state.get("stage") != "frozen_unexecuted" or
                holdout_id != finalization_status["holdout_experiment_id"]):
            raise RuntimeError("frozen holdout host state changed before post-freeze dispatch")
        holdout_prompt = ("The host verified frozen holdout experiment ID is " + holdout_id +
                          ". Dispatch holdout_runner once with this ID only, return the actual Result mapping, "
                          "and make no scientific interpretation.")
        try:
            _run_omnigent_cli_session(cli_module, holdout_document, prompt=holdout_prompt,
                                      model=model, codex_host=codex_host, prefix="nova-native-holdout-")
            holdout_trace = verify_executor_trace(audit_path, codex_host,
                                                  required_tools=("execute_frozen_native_holdout",),
                                                  expected_holdout_id=holdout_id)
            from nova.native_adaptive_runtime import read_native_holdout_result
            result_record = read_native_holdout_result(audit_path)
            result = result_record["result"]
            if result.get("experiment_id") != holdout_id:
                raise RuntimeError("native holdout Result does not belong to the frozen ID")
            from scripts.export_native_holdout_evidence import export_native_holdout_evidence
            evidence_dir = export_native_holdout_evidence(db, run_id, result["result_id"],
                                                          float(os.environ["NOVA_ADAPTIVE_BUDGET_DEADLINE"]))
            holdout_execution = {"status": result.get("execution_status") or result.get("status"),
                                 "experiment_id": holdout_id, "result_id": result["result_id"],
                                 "records": result.get("records", result.get("groups_summary")),
                                 "result_sha256": result_record["result_sha256"],
                                 "evidence_directory": str(evidence_dir), "executor_trace": holdout_trace}
            finalization_status = {**finalization_status, "status": "holdout_result_returned"}
        except Exception as exc:
            # A successful science Result can survive an export or trace failure.
            # Keep its private record and report the uncertainty without retrying.
            try:
                from nova.contracts import Mode
                from nova.storage import Storage
                Storage(db).initialize().append_event(run_id, "native_adaptive_holdout_failed", actor="host",
                                                      mode=Mode.LIVE, payload_ref=holdout_id)
            except Exception:
                pass
            partial_result = None
            try:
                from nova.native_adaptive_runtime import read_native_holdout_result
                partial_result = read_native_holdout_result(audit_path)["result"]
            except Exception:
                pass
            holdout_execution = {"status": "failed_or_partial", "experiment_id": holdout_id,
                                 "result_id": partial_result.get("result_id") if partial_result else None,
                                 "records": partial_result.get("records", partial_result.get("groups_summary",
                                         "unknown_or_partial")) if partial_result else "unknown_or_partial",
                                 "result_sha256": (hashlib.sha256(json.dumps(
                                     partial_result, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False, default=str).encode()).hexdigest()
                                     if partial_result else None),
                                 "failure_category": type(exc).__name__}
            finalization_status = {**finalization_status, "status": "holdout_failed_or_partial"}
            print(json.dumps({"status": "holdout_failed_or_partial", "run_id": run_id,
                              "finalization": finalization_status,
                              "holdout_execution": holdout_execution}, sort_keys=True), flush=True)
            raise
    elif execute_frozen_holdout:
        holdout_execution = {"status": "not_supported", "result_id": None,
                             "records": "unknown_or_partial"}
        finalization_status = {**(finalization_status or {}), "status": "holdout_not_supported"}
        print(json.dumps({"status": "holdout_not_supported", "run_id": run_id,
                          "finalization": finalization_status,
                          "holdout_execution": holdout_execution}, sort_keys=True), flush=True)
        raise RuntimeError("frozen holdout opt-in cannot proceed because finalization was not supported")
    # A concise manifest event intentionally records no prompt, credentials,
    # or model transcript; Planner/Skeptic/PI/Runner tool packets and Result
    # references are run-owned in SQLite.
    _record("native_adaptive_orchestration_completed")
    summary = {"status": "completed", "run_id": run_id, "model": model or "yaml-configured",
                      "omnigent_version": checked["omnigent_version"],
                      "guardrail_verified": True,
                      "finalization": finalization_status,
                      "holdout_execution": holdout_execution,
                      "finalization_response_sha256": finalization_response_sha256,
                      **executor_verification}
    if finalization_status and finalization_status["status"] == "not_supported":
        summary["status"] = "discovery_completed_finalization_not_supported"
    print(json.dumps(summary, sort_keys=True))
    return 0


def run_native_adaptive(*, model: str | None = None, remaining_seconds: float = 600,
                        enable_native_live: bool = False,
                        finalize_discovery: bool = False,
                        execute_frozen_holdout: bool = False) -> int:
    """Run the isolated native CLI child under one hard whole-run deadline."""
    if model is not None and (not model or len(model) > 120):
        raise ValueError("model must be a nonempty configurable model name")
    if (isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or
            not math.isfinite(float(remaining_seconds)) or not 0 < remaining_seconds <= RUN_TIMEOUT_SECONDS):
        raise ValueError(f"remaining_seconds must be in (0,{RUN_TIMEOUT_SECONDS}]")
    if execute_frozen_holdout and (not finalize_discovery or not enable_native_live):
        raise ValueError("--execute-frozen-holdout requires --finalize-discovery and --enable-native-live")
    checked = check_only(finalize_discovery=finalize_discovery,
                         execute_frozen_holdout=execute_frozen_holdout)
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
    child_env.pop(HOLDOUT_APPROVAL_ENV, None)
    child_env.pop(OWNER_PID_ENV, None)
    child_env["NOVA_ADAPTIVE_BUDGET_DEADLINE"] = str(deadline)
    child_env["NOVA_ADAPTIVE_REMAINING_SECONDS"] = str(float(remaining_seconds))
    child_env[CHILD_MARKER] = "1"
    if execute_frozen_holdout:
        child_env[HOLDOUT_APPROVAL_ENV] = "1"
    child_env[PARENT_PID_ENV] = str(os.getpid())
    child_env["NOVA_ADAPTIVE_EXPECTED_RUN_ID"] = checked_run
    child_env["NOVA_ADAPTIVE_EXPECTED_DATABASE"] = str(checked_db.resolve())
    command = [sys.executable, str(Path(__file__).resolve()), "--_trusted-child",
               "--remaining-seconds", str(float(remaining_seconds))]
    if model is not None:
        command.extend(["--model", model])
    if enable_native_live:
        command.append("--enable-native-live")
    if finalize_discovery:
        command.append("--finalize-discovery")
    if execute_frozen_holdout:
        command.append("--execute-frozen-holdout")
    process = subprocess.Popen(command, cwd=ROOT, env=child_env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               start_new_session=(os.name == "posix"))
    try:
        output, _ = process.communicate(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as timeout_error:
        captured_output = timeout_error.output
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
            completed_output, _ = process.communicate(timeout=2)
            if completed_output is not None:
                captured_output = completed_output
        except subprocess.TimeoutExpired as final_timeout:
            if final_timeout.output is not None:
                captured_output = final_timeout.output
        except Exception:
            pass
        try:
            _record("native_adaptive_orchestration_failed")
        except Exception:
            pass
        _best_effort_failure_feedback(database, checked_run,
                                      reason_category="workflow_deadline",
                                      original_exit_code=None, timeout=True,
                                      terminal_output=captured_output)
        raise TimeoutError("native adaptive workflow exceeded its whole-run deadline") from None
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if process.returncode != 0:
        try:
            _record("native_adaptive_orchestration_failed")
        except Exception:
            pass
        _best_effort_failure_feedback(database, checked_run,
                                      reason_category="child_nonzero",
                                      original_exit_code=process.returncode, timeout=False,
                                      terminal_output=output)
        raise RuntimeError(f"Omnigent native adaptive CLI exited with status {process.returncode}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="validate installed CLI/YAML without model or science calls")
    parser.add_argument("--model", help="optional model override for PI and every specialist; defaults to YAML")
    parser.add_argument("--remaining-seconds", type=float, default=600)
    parser.add_argument("--enable-native-live", action="store_true",
                        help="authorize native model and science dispatch through the guarded Omnigent harness")
    parser.add_argument("--finalize-discovery", action="store_true",
                        help="after the adaptive Runner response, perform bounded final review and protocol freeze")
    parser.add_argument("--execute-frozen-holdout", action="store_true",
                        help="opt in to one bounded post-freeze holdout attempt; requires finalization and live mode")
    parser.add_argument("--_trusted-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check_only:
        print(json.dumps(check_only(finalize_discovery=args.finalize_discovery,
                                    execute_frozen_holdout=args.execute_frozen_holdout), sort_keys=True))
        return 0
    if args._trusted_child:
        return _run_native_adaptive_child(model=args.model, remaining_seconds=args.remaining_seconds,
                                          enable_native_live=args.enable_native_live,
                                          finalize_discovery=args.finalize_discovery,
                                          execute_frozen_holdout=args.execute_frozen_holdout)
    return run_native_adaptive(model=args.model, remaining_seconds=args.remaining_seconds,
                               enable_native_live=args.enable_native_live,
                               finalize_discovery=args.finalize_discovery,
                               execute_frozen_holdout=args.execute_frozen_holdout)


if __name__ == "__main__":
    raise SystemExit(main())
