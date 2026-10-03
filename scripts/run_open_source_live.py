"""Fail-closed launcher for the bounded open-source Omnigent run.

The Codex SDK's native-tool and web-search switches are process environment
controls in Omnigent 0.16; they are deliberately forced here and cannot be
overridden by the caller.
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "agents" / "opensource-live.yaml"
OMNIGENT = ROOT / ".venv-omnigent" / "bin" / "omnigent"
PYTHON = ROOT / ".venv-omnigent" / "bin" / "python"
REQUIRED_ENV = {
    "HARNESS_CODEX_DISABLE_NATIVE_TOOLS": "1",
    "HARNESS_CODEX_ENABLE_WEB_SEARCH": "0",
}


def root_model(config: Path = CONFIG) -> str:
    """Read the top-level executor model without consulting Codex defaults.

    Keeping this deliberately small avoids accepting a model from an argv
    override or from the user's config.  YAML is parsed with the installed
    PyYAML used by Omnigent; the extra shape checks make a malformed profile
    fail before credentials are staged.
    """
    try:
        import yaml

        document = yaml.safe_load(config.read_text())
    except Exception as exc:
        raise ValueError(f"cannot parse live YAML: {exc}") from exc
    executor = document.get("executor") if isinstance(document, dict) else None
    model = executor.get("model") if isinstance(executor, dict) else None
    if not isinstance(model, str) or not model.strip() or any(c in model for c in "\r\n\x00"):
        raise ValueError("live YAML must name a non-empty root executor model")
    return model.strip()


def prepare_isolated_codex_home(config: Path = CONFIG) -> Path:
    """Create a private, short-lived Codex home with explicit model routing.

    Only ``auth.json`` is referenced from the user's home after a regular-file
    and private-mode check; no user config, history, plugins, or credentials
    are inherited.  The generated
    config pins both model and the subscription provider, preventing a stale
    global provider/default from replacing an explicit YAML model.
    """
    source_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    if not source_home.is_dir():
        raise RuntimeError(f"Codex home does not exist: {source_home}")
    target = Path(tempfile.mkdtemp(prefix="nova-codex-home-"))
    os.chmod(target, 0o700)
    try:
        auth = source_home / "auth.json"
        if not auth.is_file() or auth.is_symlink():
            raise RuntimeError("a regular ~/.codex/auth.json is required")
        if auth.stat().st_mode & 0o077:
            raise RuntimeError("auth.json must not be group/world-readable")
        (target / "auth.json").symlink_to(auth)
        model = root_model(config)
        (target / "config.toml").write_text(
            f"model = {json.dumps(model)}\nmodel_provider = \"openai\"\n"
        )
        os.chmod(target / "config.toml", 0o600)
        return target
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise


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
    isolated_home = prepare_isolated_codex_home()
    env["CODEX_HOME"] = str(isolated_home)
    try:
        return subprocess.run(command(), cwd=ROOT, env=env, check=False).returncode
    finally:
        shutil.rmtree(isolated_home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
