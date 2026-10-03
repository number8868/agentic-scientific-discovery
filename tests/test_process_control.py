import os
import time

import pytest

from nova.process_control import (
    ProcessController,
    WorkerExecutionError,
    WorkerTimeoutError,
)


def add(a, b):
    return a + b


def fail():
    raise ValueError("expected failure")


def sleepy(pid_file, seconds):
    with open(pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    time.sleep(seconds)
    return "late"


def test_registered_callable_returns_value():
    result = ProcessController({"add": add}).run("add", (2, 3), deadline_seconds=2)
    assert result.value == 5
    assert result.worker_pid > 0


def test_worker_exception_is_distinguishable():
    with pytest.raises(WorkerExecutionError) as caught:
        ProcessController({"fail": fail}).run("fail", deadline_seconds=2)
    assert caught.value.remote_type == "ValueError"
    assert "expected failure" in caught.value.remote_traceback


def test_hard_timeout_reaps_worker(tmp_path):
    pid_file = tmp_path / "worker.pid"
    with pytest.raises(WorkerTimeoutError):
        ProcessController({"sleepy": sleepy}).run(
            "sleepy", (str(pid_file), 10), deadline_seconds=0.1
        )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not pid_file.exists():
        time.sleep(0.01)
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
