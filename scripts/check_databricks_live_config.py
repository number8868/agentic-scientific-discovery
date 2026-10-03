#!/usr/bin/env python3
"""Offline, fail-closed preflight for the Databricks Omnigent live route."""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path
import re
import shutil
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "agents" / "databricks-live.yaml"
PROFILE_RE = re.compile(r"^\s+profile:\s*([A-Za-z0-9_.-]+)\s*$", re.M)
FORBIDDEN_RE = re.compile(r"(?:^|\n)\s*(?:os_env|shell|terminal|path|dataset_path|data_path|cache_dir)\s*:", re.I)
SECRET_RE = re.compile(r"(?:token|api[_-]?key|secret|password)\s*:\s*[^#\s]+", re.I)


def validate_config(path: str | Path = CONFIG) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    errors: list[str] = []
    if "executor:" not in text or "harness: claude-sdk" not in text:
        errors.append("executor must use the claude-sdk harness")
    if "model: databricks-claude-sonnet-4-6" not in text:
        errors.append("approved Databricks model is required")
    if "type: databricks" not in text or not PROFILE_RE.search(text):
        errors.append("executor.auth.type=databricks and a profile are required")
    if "async: false" not in text:
        errors.append("async must be false")
    if FORBIDDEN_RE.search(text):
        errors.append("shell, arbitrary path, or inherited environment access is forbidden")
    if SECRET_RE.search(text) or re.search(r"https?://", text, re.I):
        errors.append("credentials and workspace URLs must not be tracked")
    if "nova.omnigent_bridge.execute_fixture" in text:
        errors.append("fixture bridge is not allowed on the live route")
    required = (
        "nova.decision_tools.submit_final_review",
        "nova.decision_tools.freeze_final",
        "holdout_experiment_id",
        "Do not execute a holdout",
    )
    errors.extend(f"required finalization control missing: {item}" for item in required if item not in text)
    for callable_name in re.findall(r"callable:\s*([^\s]+)", text):
        if not callable_name.startswith("nova."):
            errors.append("all callable tools must be repository-owned nova modules")
    return {"ok": not errors, "errors": errors}


def _profile_present(config_file: Path, profile: str) -> bool:
    if not config_file.is_file():
        return False
    parser = configparser.ConfigParser()
    try:
        parser.read(config_file, encoding="utf-8")
    except (OSError, configparser.Error):
        return False
    return profile in parser.sections()


def preflight(config_path: str | Path = CONFIG, *, root: str | Path = ROOT,
              environ: Mapping[str, str] | None = None,
              home: str | Path | None = None) -> dict:
    """Return safe diagnostics; false ``ok`` means a prerequisite is absent."""
    env = dict(os.environ if environ is None else environ)
    root = Path(root)
    static = validate_config(config_path)
    text = Path(config_path).read_text(encoding="utf-8")
    profile_match = PROFILE_RE.search(text)
    profile = profile_match.group(1) if profile_match else ""
    cli = shutil.which("databricks", path=env.get("PATH"))
    cfg = Path(env.get("DATABRICKS_CONFIG_FILE", "")) if env.get("DATABRICKS_CONFIG_FILE") else Path(home or Path.home()) / ".databrickscfg"
    omnigent = env.get("OMNIGENT_BIN") or shutil.which("omnigent", path=env.get("PATH"))
    data_root = Path(env.get("NOVA_SCIENCE_DATA_ROOT", root / "data"))
    manifest = data_root / "manifest.json"
    protocol = data_root / "protocol.json"
    data_ok = False
    if manifest.is_file() and protocol.is_file():
        try:
            data_ok = json.loads(manifest.read_text(encoding="utf-8")).get("dataset") == "dft_3d"
        except (OSError, ValueError, AttributeError):
            data_ok = False
    checks = {
        "config": static["ok"],
        "databricks_cli": bool(cli),
        "profile_configured": _profile_present(cfg, profile) if profile else False,
        "omnigent": bool(omnigent and Path(omnigent).is_file() and os.access(omnigent, os.X_OK)),
        "science_data": data_ok,
    }
    errors = list(static["errors"])
    errors += [f"{name} is unavailable" for name, present in checks.items() if not present]
    return {"ok": not errors, "checks": checks, "errors": errors, "provider_call": "not attempted"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=str(CONFIG))
    args = parser.parse_args(argv)
    result = preflight(args.path)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
