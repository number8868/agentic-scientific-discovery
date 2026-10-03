import os
import time

import pytest

from nova.process_control import (
    ProcessController,
    WorkerExecutionError,
    WorkerTimeoutError,
)

SPAWN_DEADLINE_SECONDS = 30


def add(a, b):
    return a + b


def large_payload(size):
    return b"x" * size


def fail():
    raise ValueError("expected failure")


def sleepy(pid_file, seconds):
    with open(pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    time.sleep(seconds)
    return "late"


def test_registered_callable_returns_value():
    # Spawn imports can be slow on a cold Windows/WSL filesystem.
    result = ProcessController({"add": add}).run(
        "add", (2, 3), deadline_seconds=SPAWN_DEADLINE_SECONDS
    )
    assert result.value == 5
    assert result.worker_pid > 0


def test_large_result_does_not_deadlock_pipe():
    size = 8 * 1024 * 1024
    result = ProcessController({"large_payload": large_payload}).run(
        "large_payload", (size,), deadline_seconds=SPAWN_DEADLINE_SECONDS
    )
    assert result.value == b"x" * size


def test_worker_exception_is_distinguishable():
    with pytest.raises(WorkerExecutionError) as caught:
        ProcessController({"fail": fail}).run(
            "fail", deadline_seconds=SPAWN_DEADLINE_SECONDS
        )
    assert caught.value.remote_type == "ValueError"
    assert "expected failure" in caught.value.remote_traceback


def test_hard_timeout_reaps_worker(tmp_path):
    # Warm the spawn path first so the short execution timeout measures the
    # worker, rather than an arbitrary cold import delay before it creates its
    # PID marker.
    warmup = ProcessController({"add": add}).run(
        "add", (1, 1), deadline_seconds=SPAWN_DEADLINE_SECONDS
    )
    assert warmup.value == 2

    pid_file = tmp_path / "worker.pid"
    with pytest.raises(WorkerTimeoutError):
        ProcessController({"sleepy": sleepy}).run(
            "sleepy", (str(pid_file), 60), deadline_seconds=20
        )
    assert pid_file.exists()
    pid = int(pid_file.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_unknown_and_invalid_callables_are_rejected():
    controller = ProcessController({"add": add})
    with pytest.raises(KeyError):
        controller.run("missing", deadline_seconds=1)
    with pytest.raises(ValueError):
        ProcessController({"bad-name": add})
    with pytest.raises(ValueError):
        ProcessController({"closure": lambda: None})
