#!/usr/bin/env python3
"""Offline environment smoke checks for the repository-local Omnigent install."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OMNIGENT = ROOT / ".venv-omnigent" / "bin" / "omnigent"


def _command(exe, *args):
    try:
        result = subprocess.run([str(exe)] + list(args), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=20,
                                env={"PATH": os.environ.get("PATH", "")})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__}
    return {"ok": result.returncode == 0, "returncode": result.returncode,
            "output_prefix": result.stdout[:160]}


def _offline_yaml_check(path):
    """Check required textual structure without importing a YAML dependency."""
    text = Path(path).read_text(encoding="utf-8")
    required = ["name:", "executor:", "tools:", "policies:"]
    missing = [key for key in required if key not in text]
    forbidden = [key for key in ("os_env:", "shell:", "terminal:") if key in text]
    return {"ok": not missing and not forbidden,
            "missing": missing, "forbidden": forbidden,
            "has_databricks_auth": "type: databricks" in text,
            "has_runner_callable": bool(re.search(r"callable:\s+nova\.", text))}


def inspect_environment(omnigent=DEFAULT_OMNIGENT, yaml_path=None):
    result = {
        "python": sys.version.split()[0],
        "omnigent_executable": str(omnigent),
        "version": _command(omnigent, "--version") if Path(omnigent).exists() else {"ok": False, "error": "missing"},
        "help": _command(omnigent, "--help") if Path(omnigent).exists() else {"ok": False, "error": "missing"},
        "provider_call": "not attempted",
    }
    if yaml_path:
        result["yaml"] = _offline_yaml_check(yaml_path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--omnigent", default=str(DEFAULT_OMNIGENT))
    parser.add_argument("--yaml", dest="yaml_path")
    args = parser.parse_args(argv)
    print(json.dumps(inspect_environment(args.omnigent, args.yaml_path), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
