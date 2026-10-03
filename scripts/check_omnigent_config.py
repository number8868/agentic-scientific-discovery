#!/usr/bin/env python3
"""Dependency-free safety checks and local profile rendering for Omnigent YAML."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "agents" / "databricks.yaml"
CALLABLE = "nova.omnigent_bridge.execute_fixture_registered_experiment"


def _section(text, name):
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == name + ":"), None)
    if start is None:
        return []
    out = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("\t") and line.strip() and not line.lstrip().startswith("#"):
            break
        out.append(line)
    return out


def validate(path):
    text = Path(path).read_text(encoding="utf-8")
    errors = []
    lowered = text.lower()
    if "os_env:" in lowered or "shell" in lowered or "terminal" in lowered:
        errors.append("OS/shell access is not allowed in the Databricks route")
    if re.search(r"(?:token|api[_-]?key|secret|password)\s*:\s*[^#\s]+", text, re.I):
        errors.append("possible credential value in YAML")
    if re.search(r"https?://[^ <#]+", text, re.I):
        errors.append("workspace URL must not be committed")
    if "executor:" not in text or "auth:" not in text or "type: databricks" not in text:
        errors.append("executor.auth.type must be databricks")
    if not re.search(r"^\s+profile:\s*[A-Za-z0-9_.-]+\s*(?:#.*)?$", text, re.M):
        errors.append("executor.auth.profile is required")
    tools = _section(text, "tools")
    if not any(re.match(r"^  runner:\s*$", line) for line in tools):
        errors.append("tools must contain a runner mapping")
    runner_start = next((i for i, line in enumerate(tools) if line.strip() == "runner:"), None)
    if runner_start is not None:
        runner = []
        for line in tools[runner_start + 1 :]:
            if line.startswith("  ") and not line.startswith("    ") and line.strip():
                break
            runner.append(line)
        funcs = [line for line in runner if re.match(r"^ {6}[A-Za-z0-9_-]+:\s*$", line)]
        if funcs != ["      execute_registered_experiment:"]:
            errors.append("Runner must expose exactly one function tool")
        if runner.count("        type: function") != 1:
            errors.append("Runner function tool must have type function")
        if runner.count("        callable: " + CALLABLE) != 1:
            errors.append("Runner callable must be " + CALLABLE)
    policies = _section(text, "policies")
    if not policies or not any(re.match(r"^  [A-Za-z0-9_-]+:\s*$", line) for line in policies):
        errors.append("policies must be a named mapping")
    if errors:
        raise ValueError("; ".join(errors))
    return True


def render_local(template=TEMPLATE, output=None, profile=None):
    """Render a local profile-only copy; credentials remain in user config."""
    profile = profile or os.environ.get("OMNIGENT_DATABRICKS_PROFILE")
    if not profile or not re.fullmatch(r"[A-Za-z0-9_.-]+", profile):
        raise ValueError("set OMNIGENT_DATABRICKS_PROFILE to a safe profile name")
    destination = Path(output) if output else Path("/tmp/nova-mat-databricks.yaml")
    text = Path(template).read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s+profile:)\s*[^#\n]+", r"\1 " + profile, text, count=1)
    destination.write_text(text, encoding="utf-8")
    validate(destination)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=str(TEMPLATE))
    parser.add_argument("--generate", metavar="PATH", help="write a local profile-rendered copy")
    args = parser.parse_args(argv)
    if args.generate:
        print(render_local(output=args.generate))
    else:
        validate(args.path)
        print("OK:", args.path)


if __name__ == "__main__":
    main()
