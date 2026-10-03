"""Fail-closed launcher for the bounded open-source Omnigent run.

The Codex SDK's native-tool and web-search switches are process environment
controls in Omnigent 0.16; they are deliberately forced here and cannot be
overridden by the caller.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "agents" / "opensource-live.yaml"
OMNIGENT = ROOT / ".venv-omnigent" / "bin" / "omnigent"
PYTHON = ROOT / ".venv-omnigent" / "bin" / "python"
REQUIRED_ENV = {
    "HARNESS_CODEX_DISABLE_NATIVE_TOOLS": "1",
    "HARNESS_CODEX_ENABLE_WEB_SEARCH": "0",
}


def command() -> list[str]:
    """Return a fresh, non-resumable Omnigent invocation.

    A normal ``run`` may offer the most recent conversation (or resume it
    when the UI is driven non-interactively).  That can silently retain the
    model selected by an earlier session.  ``--no-session`` gives every
    bounded live attempt a new local store, so the YAML executor models are
    authoritative and the resulting audit cannot be attributed to a stale
    conversation.
    """
    return [str(OMNIGENT), "run", "--no-session", str(CONFIG)]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([], ["--check-only"]):
        print("launcher accepts only --check-only; use the fixed bounded config", file=sys.stderr)
        return 2
    if not PYTHON.is_file() or not OMNIGENT.is_file():
        print("missing .venv-omnigent; install open-source Omnigent first", file=sys.stderr)
        return 2
    check = subprocess.run(
        [str(PYTHON), str(ROOT / "scripts" / "check_live_config.py"), str(CONFIG)],
        cwd=ROOT,
        check=False,
    )
    if check.returncode:
        return check.returncode
    if args == ["--check-only"]:
        print("bounded open-source Omnigent launcher: check OK")
        return 0
    env = os.environ.copy()
    env.update(REQUIRED_ENV)
    return subprocess.run(command(), cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
