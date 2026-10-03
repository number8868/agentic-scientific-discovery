"""Small, trusted-host process boundary for registered callables.

This module deliberately exposes no shell, module import, or filesystem
execution primitive.  A host supplies an explicit name-to-callable registry;
the child can only invoke one of those registered callables.
"""

from __future__ import annotations

import math
import multiprocessing
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
        process.start()
        child.close()
        try:
            process.join(float(deadline_seconds))
            if process.is_alive():
                process.terminate()
                process.join(1.0)
                if process.is_alive() and hasattr(process, "kill"):
                    process.kill()
                    process.join(1.0)
                raise WorkerTimeoutError(f"worker exceeded {deadline_seconds:g}s deadline")
            if parent.poll(0.2):
                message = parent.recv()
            else:
                raise ProcessControlError(f"worker exited without a result (exitcode={process.exitcode})")
            if message[0] == "error":
                raise WorkerExecutionError(message[1], message[2], message[3])
            if message[0] != "ok":
                raise ProcessControlError("worker returned an invalid result envelope")
            return WorkerResult(value=message[1], worker_pid=process.pid or -1)
        finally:
            parent.close()
            if process.is_alive():
                process.terminate()
                process.join(1.0)


__all__ = [
    "ProcessController",
    "ProcessControlError",
    "WorkerExecutionError",
    "WorkerResult",
    "WorkerTimeoutError",
]
