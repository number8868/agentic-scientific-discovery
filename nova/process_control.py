"""Small, trusted-host process boundary for registered callables.

This module deliberately exposes no shell, module import, or filesystem
execution primitive.  A host supplies an explicit name-to-callable registry;
the child can only invoke one of those registered callables.
"""

from __future__ import annotations

import math
import multiprocessing
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


class ProcessControlError(RuntimeError):
    """Base class for worker lifecycle failures."""


class WorkerTimeoutError(TimeoutError, ProcessControlError):
    """Raised when the hard wall-clock deadline is reached."""


class WorkerExecutionError(ProcessControlError):
    """Raised when a registered callable fails in the worker."""

    def __init__(self, remote_type: str, remote_message: str, remote_traceback: str):
        self.remote_type = remote_type
        self.remote_message = remote_message
        self.remote_traceback = remote_traceback
        super().__init__(f"worker raised {remote_type}: {remote_message}")


@dataclass(frozen=True)
class WorkerResult:
    """The value and worker identity from a successful invocation."""

    value: Any
    worker_pid: int


def _receive_message(conn: Any, result_queue: queue.Queue) -> None:
    try:
        result_queue.put((True, conn.recv()))
    except BaseException as exc:  # relay transport failures to the host thread
        result_queue.put((False, exc))
    finally:
        conn.close()


def _worker_entry(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any], conn: Any) -> None:
    try:
        value = fn(*args, **kwargs)
        conn.send(("ok", value))
    except BaseException as exc:  # transport remote failures without re-raising in child
        try:
            conn.send(("error", type(exc).__name__, str(exc), traceback.format_exc()))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        conn.close()


class ProcessController:
    """Execute only explicitly registered Python callables in a hard-bounded child.

    Callables must be importable/pickleable top-level functions when the spawn
    start method is used.  This is intentional: lambdas, closures, shell
    commands and paths are not accepted as an execution interface.
    """

    def __init__(self, registered: Mapping[str, Callable[..., Any]]):
        if not isinstance(registered, Mapping) or not registered:
            raise ValueError("registered must be a non-empty mapping")
        self._registered = dict(registered)
        for name, fn in self._registered.items():
            if not isinstance(name, str) or not name or not name.isidentifier():
                raise ValueError("callable names must be non-empty identifiers")
            if not callable(fn) or getattr(fn, "__name__", "") == "<lambda>":
                raise ValueError(f"registered callable {name!r} is not an allowed function")

    def run(
        self,
        name: str,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        *,
        deadline_seconds: float,
    ) -> WorkerResult:
        if name not in self._registered:
            raise KeyError(f"callable is not registered: {name}")
        if isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, (int, float)):
            raise ValueError("deadline_seconds must be a positive finite number")
        if not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be a positive finite number")
        if kwargs is not None and not isinstance(kwargs, Mapping):
            raise TypeError("kwargs must be a mapping")
        call_args = tuple(args)
        call_kwargs = dict(kwargs or {})
        parent, child = multiprocessing.Pipe(duplex=False)
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_worker_entry,
            args=(self._registered[name], call_args, call_kwargs, child),
            daemon=True,
        )
        receiver = None
        try:
            process.start()
            child.close()
            # Keep the existing contract: process creation is synchronous, so
            # the execution budget starts once start() has returned. From here
            # one deadline covers execution, pipe draining, and worker exit.
            deadline = time.monotonic() + float(deadline_seconds)

            # A dedicated reader continuously drains the pipe so large sends
            # cannot block the worker. The host thread waits on its queue with
            # the deadline, so recv() cannot extend the wall-clock budget.
            received = queue.Queue(maxsize=1)
            reader = threading.Thread(
                target=_receive_message, args=(parent, received), daemon=True
            )
            reader.start()
            receiver = reader
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkerTimeoutError(f"worker exceeded {deadline_seconds:g}s deadline")
            try:
                has_message, payload = received.get(timeout=remaining)
            except queue.Empty as exc:
                raise WorkerTimeoutError(
                    f"worker exceeded {deadline_seconds:g}s deadline"
                ) from exc
            if not has_message:
                process.join(0)
                if isinstance(payload, EOFError):
                    raise ProcessControlError(
                        f"worker exited without a result (exitcode={process.exitcode})"
                    ) from payload
                raise ProcessControlError(f"could not receive worker result: {payload}") from payload
            message = payload

            # Receiving an envelope can take time for a large value. Keep the
            # same wall-clock deadline for worker shutdown as for execution.
            if time.monotonic() >= deadline:
                raise WorkerTimeoutError(f"worker exceeded {deadline_seconds:g}s deadline")
            process.join(max(0.0, deadline - time.monotonic()))
            if process.is_alive():
                raise WorkerTimeoutError(f"worker exceeded {deadline_seconds:g}s deadline")
            if message[0] == "error":
                raise WorkerExecutionError(message[1], message[2], message[3])
            if message[0] != "ok":
                raise ProcessControlError("worker returned an invalid result envelope")
            return WorkerResult(value=message[1], worker_pid=process.pid or -1)
        finally:
            child.close()
            if receiver is None:
                parent.close()
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(1.0)
                if process.is_alive() and hasattr(process, "kill"):
                    process.kill()
                    process.join(1.0)
            if receiver is not None:
                receiver.join(0.1)


__all__ = [
    "ProcessController",
    "ProcessControlError",
    "WorkerExecutionError",
    "WorkerResult",
    "WorkerTimeoutError",
]
