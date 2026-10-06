"""Budget-gated, isolated Omnigent runtime for engineering self-tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable

_SECRET = re.compile(r"(?i)(?:bearer\s+|sk-|rk-|gh[pousr]_|xox[baprs]-)[A-Za-z0-9._-]{12,}")
_ARMS = {"single_self_review": ("draft", "critique", "final"),
         "parallel_review": ("planner", "skeptic", "pi")}
_WORKER = Path(__file__).resolve().parents[1] / "scripts" / "parallel_selftest_worker.py"


class FatalAuditError(RuntimeError):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: Any, limit: int = 200000) -> str:
    return _SECRET.sub("[redacted]", str(value)).replace("\x00", "")[:limit]


async def _ps_tree(root_pid: int) -> dict[int, tuple[int, int, str]] | None:
    """Return live process descendants while the worker still owns their PPIDs."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec("ps", "-axo", "pid=,ppid=,pgid=,stat=",
                                                    stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 0.5)
    except asyncio.TimeoutError:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        return None
    except Exception:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        return None
    if proc.returncode != 0:
        return None
    rows: dict[int, tuple[int, int, str]] = {}
    for line in out.decode(errors="replace").splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            rows[int(parts[0])] = (int(parts[1]), int(parts[2]), parts[3])
    descendants: dict[int, tuple[int, int, str]] = {}
    frontier = {root_pid}
    while frontier:
        found = {pid for pid, (ppid, _, stat) in rows.items() if ppid in frontier and "Z" not in stat}
        frontier = found - descendants.keys()
        for pid in frontier:
            descendants[pid] = rows[pid]
    return descendants


async def _monitor_tree(root_pid: int, seen: set[int], proc: asyncio.subprocess.Process,
                        verified: list[bool]) -> None:
    while proc.returncode is None:
        tree = await _ps_tree(root_pid)
        if tree is None:
            verified[0] = False
        else:
            seen.update(tree)
        await asyncio.sleep(0.1)


async def _drain_stderr(reader: asyncio.StreamReader) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


async def _reap(proc: asyncio.subprocess.Process, seen: set[int], grace: float = 3.0) -> bool:
    """Close worker then signal only tracked descendants plus its own process group."""
    deadline = time.monotonic() + grace
    current = await _ps_tree(proc.pid)
    verified = current is not None
    if current is not None:
        seen.update(current)
    # Graceful shutdown gives SDK close hooks a chance; then target tracked
    # detached descendants before killing the worker group.
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for pid in sorted(seen, reverse=True):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(proc.wait(), max(0.05, deadline - time.monotonic()))
    except asyncio.TimeoutError:
        pass
    for pid in sorted(seen, reverse=True):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.returncode is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), max(0.05, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            return False
    remaining = await _ps_tree(proc.pid)
    if remaining is None or remaining:
        return False
    # Detached descendants can be reparented as soon as the worker exits;
    # verify every remembered PID too, and accept only gone or zombie entries.
    for pid in seen:
        try:
            probe = await asyncio.create_subprocess_exec("ps", "-o", "stat=", "-p", str(pid),
                                                         stdout=asyncio.subprocess.PIPE,
                                                         stderr=asyncio.subprocess.PIPE)
            output, probe_error = await asyncio.wait_for(probe.communicate(), 0.25)
            if probe.returncode != 0 and (output.strip() or probe_error.strip()):
                verified = False
                continue
            if output.decode().strip() and "Z" not in output.decode().strip():
                return False
        except Exception:
            verified = False
    return verified and proc.returncode is not None


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or hasattr(value, "__await__"):
        return await value
    return value


async def _child(payload: dict[str, Any], expected_roles: str | tuple[str, ...],
                 before_dispatch: Callable[[str], Any], cwd: str,
                 absolute_deadline: float) -> tuple[dict[str, Any], bool]:
    """Run one child process; parallel specialist roles always have distinct envs."""
    remaining = absolute_deadline - time.monotonic()
    if remaining <= 4:
        return {"status": "arm_timeout", "error": "cleanup reserve reached", "turns": []}, True
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(_WORKER.parents[1]),
           "HARNESS_CODEX_MINIMAL_CONFIG": "1"}
    if os.environ.get("HOME"):
        env["HOME"] = os.environ["HOME"]
    host_path = os.environ.get("CODEX_CODE_MODE_HOST_PATH")
    if host_path:
        env["CODEX_CODE_MODE_HOST_PATH"] = host_path
    turn_deadline = time.monotonic() + float(payload.get("turn_timeout", 45))
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(_WORKER), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=cwd, env=env, start_new_session=True)
    descendants: set[int] = set()
    process_tree_verified = [True]
    monitor = asyncio.create_task(_monitor_tree(proc.pid, descendants, proc, process_tree_verified))
    drain = asyncio.create_task(_drain_stderr(proc.stderr))
    fatal_audit = False
    child_result: dict[str, Any] = {}
    turn_records: list[dict[str, Any]] = []
    granted_roles: list[str] = []
    dispatch_attempts: list[dict[str, Any]] = []
    completed_roles: set[str] = set()
    seen_roles: list[str] = []
    try:
        assert proc.stdin and proc.stdout
        proc.stdin.write((json.dumps({"type": "start", "payload": payload}) + "\n").encode())
        await proc.stdin.drain()

        async def exchange() -> dict[str, Any]:
            nonlocal fatal_audit, turn_deadline
            while True:
                descendants.update(await _ps_tree(proc.pid))
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(),
                                                  max(0.01, min(absolute_deadline - time.monotonic() - 4,
                                                                turn_deadline - time.monotonic())))
                except asyncio.TimeoutError:
                    raise
                if not line:
                    raise RuntimeError("worker closed protocol before result")
                if len(line) > 1_000_000:
                    raise RuntimeError("worker protocol line exceeded one megabyte")
                message = json.loads(line)
                if message.get("type") == "turn":
                    turn = message.get("turn")
                    if not isinstance(turn, dict):
                        raise RuntimeError("invalid turn trace")
                    idx = len(turn_records)
                    expected = ((expected_roles[idx] if idx < len(expected_roles) else None)
                                if isinstance(expected_roles, tuple) else
                                (expected_roles if idx == 0 else None))
                    if expected is None or turn.get("role") != expected or expected not in seen_roles or expected in completed_roles:
                        raise RuntimeError("worker emitted an unexpected, duplicate, or undispatched turn trace")
                    if turn.get("status") == "success" and not turn.get("thread_id"):
                        raise RuntimeError("SDK turn completed without native thread identity")
                    raw = turn.get("raw", "")
                    if len(raw) > 200000:
                        turn.update(status="raw_overflow", error="sanitized model output exceeded 200 KB", raw="", response="")
                    turn_records.append(turn)
                    completed_roles.add(expected)
                    turn_deadline = time.monotonic() + float(payload.get("turn_timeout", 45))
                    continue
                if message.get("type") == "dispatch":
                    role = str(message.get("role", ""))
                    expected = ((expected_roles[len(seen_roles)] if len(seen_roles) < len(expected_roles)
                                 else None) if isinstance(expected_roles, tuple) else
                                (expected_roles if not seen_roles else None))
                    if role != expected:
                        raise RuntimeError("worker requested an unexpected or duplicate SDK dispatch")
                    seen_roles.append(role)
                    try:
                        authorization = await asyncio.wait_for(
                            _maybe_await(before_dispatch(role)),
                            max(0.01, min(turn_deadline - time.monotonic(), absolute_deadline - time.monotonic() - 4)))
                    except Exception as exc:
                        fatal_audit = True
                        dispatch_attempts.append({"role": role,
                            "worker_requested_at": message.get("worker_requested_at"),
                            "status": "audit_error", "parent_at": _stamp()})
                        raise FatalAuditError("trusted dispatch audit failed") from exc
                    if authorization is False:
                        dispatch_attempts.append({"role": role,
                            "worker_requested_at": message.get("worker_requested_at"),
                            "status": "denied", "parent_at": _stamp()})
                        proc.stdin.write((json.dumps({"type": "grant", "allowed": False,
                                                      "parent_at": _stamp()}) + "\n").encode())
                        await proc.stdin.drain()
                        continue
                    proc.stdin.write((json.dumps({"type": "grant", "allowed": True,
                                                  "parent_at": _stamp()}) + "\n").encode())
                    await proc.stdin.drain()
                    granted_roles.append(role)
                    dispatch_attempts.append({"role": role,
                        "worker_requested_at": message.get("worker_requested_at"),
                        "status": "authorized", "parent_at": _stamp()})
                elif message.get("type") == "result":
                    return message
                else:
                    raise RuntimeError("invalid child protocol message")

        turn_cap = float(payload.get("turn_timeout", 45))
        max_child_time = (turn_cap * len(expected_roles) if isinstance(expected_roles, tuple) else turn_cap) + 2
        time_left = min(max_child_time, absolute_deadline - time.monotonic() - 4)
        result = await asyncio.wait_for(exchange(), max(0.01, time_left))
        expected_count = len(expected_roles) if isinstance(expected_roles, tuple) else 1
        if (not seen_roles or (result.get("status") == "success" and len(seen_roles) != expected_count)):
            raise RuntimeError("worker completed without an authorized SDK dispatch")
        if result.get("status") == "success":
            if len(turn_records) != expected_count or len(completed_roles) != expected_count:
                raise RuntimeError("successful result has missing SDK turn traces")
            final_raw = result.get("final_raw", "")
            if not turn_records or final_raw != turn_records[-1].get("raw", ""):
                raise RuntimeError("final answer does not match the last SDK turn")
        if any(turn.get("status") == "raw_overflow" for turn in turn_records):
            result.update(status="raw_overflow", final_raw="", error="sanitized model output exceeded 200 KB")
        result["turns"] = turn_records
        result["dispatched_roles"] = list(seen_roles)
        result["granted_roles"] = list(granted_roles)
        result["dispatch_attempts"] = dispatch_attempts
        child_result = result
        return result, fatal_audit
    except FatalAuditError:
        child_result = {"status": "fatal_audit_error", "error": "trusted dispatch audit failed",
                        "turns": turn_records, "dispatched_roles": list(seen_roles),
                        "granted_roles": list(granted_roles),
                        "dispatch_attempts": dispatch_attempts,
                        "unknown_turns": [role for role in granted_roles if role not in completed_roles]}
        return child_result, True
    except asyncio.TimeoutError:
        child_result = {"status": "turn_timeout", "error": "turn deadline exceeded",
                        "turns": turn_records, "dispatched_roles": list(seen_roles),
                        "granted_roles": list(granted_roles),
                        "dispatch_attempts": dispatch_attempts,
                        "unknown_turns": [role for role in granted_roles if role not in completed_roles]}
        return child_result, fatal_audit
    except Exception as exc:
        child_result = {"status": "worker_error", "error": _safe(type(exc).__name__ + ": " + str(exc), 500),
                        "turns": turn_records, "dispatched_roles": list(seen_roles),
                        "granted_roles": list(granted_roles),
                        "dispatch_attempts": dispatch_attempts,
                        "unknown_turns": [role for role in granted_roles if role not in completed_roles]}
        return child_result, fatal_audit
    finally:
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass
        descendants.update(await _ps_tree(proc.pid))
        if proc.stdin and not proc.stdin.is_closing():
            proc.stdin.close()
            try:
                await asyncio.wait_for(proc.stdin.wait_closed(), 0.2)
            except Exception:
                pass
        cleanup_ok = await _reap(proc, descendants)
        cleanup_ok = cleanup_ok and process_tree_verified[0]
        try:
            stderr_hash = await asyncio.wait_for(drain, 0.1)
        except Exception:
            drain.cancel()
            stderr_hash = None
        child_result["cleanup_ok"] = cleanup_ok
        child_result["stderr_sha256"] = stderr_hash


async def run_arm(packet: str, arm: str, model: str, reasoning_effort: str,
                  before_dispatch: Callable[[str], Any], turn_timeout: float = 45,
                  arm_timeout: float = 150) -> dict[str, Any]:
    """Run one frozen three-turn arm with parent-owned dispatch reservations.

    The callback is invoked exactly before each SDK turn is granted. Its return
    may be any value except literal ``False``; durable-audit exceptions escape
    as a fatal error and stop the arm.
    """
    started = time.monotonic()
    answer = {"final_raw": None, "turns": [], "wall_seconds": None,
              "status": "worker_error", "error": None, "cleanup_ok": False,
              "usage": None, "fatal_audit": False, "dispatch_attempts": [],
              "unknown_turns": []}
    if arm not in _ARMS:
        answer["error"] = f"unsupported arm: {arm}"
        answer["wall_seconds"] = time.monotonic() - started
        return answer
    roles = _ARMS[arm]
    with tempfile.TemporaryDirectory(prefix="nova-selftest-") as scratch:
        deadline = started + arm_timeout
        turns: list[dict[str, Any]] = []
        try:
            if arm == "single_self_review":
                child_payload = {"packet": packet, "arm": arm, "model": model,
                                 "reasoning_effort": reasoning_effort, "turn_timeout": turn_timeout}
                # This worker owns one persistent session, so it makes three
                # gated dispatch requests and returns three trace records.
                child_result, fatal = await _child(child_payload, roles, before_dispatch,
                                                   scratch, deadline)
                turns = child_result.get("turns", [])
                answer["dispatch_attempts"].extend(child_result.get("dispatch_attempts", []))
                answer["unknown_turns"].extend(child_result.get("unknown_turns", []))
                answer.update(final_raw=_safe(child_result.get("final_raw", "")),
                              status=child_result.get("status", "worker_error"),
                              error=_safe(child_result.get("error", ""), 500) or None,
                              fatal_audit=fatal,
                              cleanup_ok=child_result.get("cleanup_ok", False))
            else:
                async def one(role: str, content: dict[str, str]):
                    payload = {"role": role, "content": content,
                               "session_id": role + "-" + os.urandom(12).hex(),
                               "model": model, "reasoning_effort": reasoning_effort,
                               "turn_timeout": turn_timeout}
                    isolated_cwd = Path(scratch) / role
                    isolated_cwd.mkdir()
                    return await _child(payload, role, before_dispatch, str(isolated_cwd), deadline)
                initial = await asyncio.gather(one("planner", {"packet": packet}),
                                               one("skeptic", {"packet": packet}))
                turns.extend(turn for response, _ in initial for turn in response.get("turns", []))
                for response, _ in initial:
                    answer["dispatch_attempts"].extend(response.get("dispatch_attempts", []))
                    answer["unknown_turns"].extend(response.get("unknown_turns", []))
                fatal = any(is_fatal for _, is_fatal in initial)
                if fatal:
                    answer.update(status="fatal_audit_error", error="trusted dispatch audit failed",
                                  fatal_audit=True,
                                  cleanup_ok=all(r.get("cleanup_ok", False) for r, _ in initial))
                elif all(response.get("status") == "success" for response, _ in initial):
                    planner_turn = initial[0][0]["turns"][0]
                    skeptic_turn = initial[1][0]["turns"][0]
                    pi, pi_fatal = await one("pi", {"packet": packet,
                                                     "planner": planner_turn.get("raw", ""),
                                                     "skeptic": skeptic_turn.get("raw", "")})
                    turns.extend(pi.get("turns", []))
                    answer["dispatch_attempts"].extend(pi.get("dispatch_attempts", []))
                    answer["unknown_turns"].extend(pi.get("unknown_turns", []))
                    answer.update(final_raw=_safe(pi.get("final_raw", "")),
                                  status=pi.get("status", "worker_error"),
                                  error=_safe(pi.get("error", ""), 500) or None,
                                  fatal_audit=pi_fatal,
                                  cleanup_ok=all(response.get("cleanup_ok", False) for response, _ in initial)
                                  and pi.get("cleanup_ok", False))
                else:
                    answer.update(status=next((r.get("status") for r, _ in initial
                                               if r.get("status") != "success"), "worker_error"),
                                  error="planner or skeptic worker failed",
                                  cleanup_ok=all(r.get("cleanup_ok", False) for r, _ in initial))
            answer["turns"] = turns
        except Exception as exc:
            fatal = isinstance(exc, FatalAuditError) or "trusted dispatch audit failed" in str(exc)
            answer.update(status="fatal_audit_error" if fatal else "worker_error",
                          fatal_audit=fatal,
                          error=_safe(type(exc).__name__ + ": " + str(exc), 500))
        finally:
            answer["wall_seconds"] = time.monotonic() - started
    if time.monotonic() > deadline and answer["status"] == "success":
        answer.update(status="arm_timeout", error="arm deadline exceeded", final_raw=None)
    if not answer["cleanup_ok"]:
        answer.update(status="cleanup_failed", error="worker descendants were not confirmed reaped", final_raw=None)
    return answer
