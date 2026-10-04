#!/usr/bin/env python3
"""Bootstrap a fresh live run with the deterministic primary baseline.

The primary family_screen is host-seeded, not selected by an autonomous model.
After its result exists, run_adaptive_followup.py asks Omnigent to choose the
next registered discovery action. This script never runs a model or holdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
BASELINE_REASON = "host-seeded baseline, not autonomous selection"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _context_path() -> Path:
    from scripts import prepare_live_run

    return Path(prepare_live_run.LIVE_CONTEXT_PATH)


def _default_api() -> dict[str, Callable[..., Any]]:
    from nova import decision_tools, live_bridge
    from scripts.prepare_live_run import prepare_live_run

    return {
        "prepare_live_run": prepare_live_run,
        "register_initial_plan": decision_tools.register_initial_plan,
        "commit_initial_spec": decision_tools.commit_initial_spec,
        "execute_live_registered_experiment": live_bridge.execute_live_registered_experiment,
    }


def prepare_adaptive_run(database: str | Path, run_id: str, *,
                         api: Mapping[str, Callable[..., Any]] | None = None) -> dict[str, Any]:
    """Create a fresh discovery run and execute its host-seeded family screen."""
    if not isinstance(run_id, str) or not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run-id must contain only safe identifier characters")
    runs_root = (ROOT / "runs").resolve()
    requested = Path(database).expanduser()
    if requested.is_symlink():
        raise ValueError("database target must not be a symlink")
    target = requested.resolve()
    if target == runs_root or not target.is_relative_to(runs_root):
        raise ValueError("database must be located under the repository runs directory")
    if target.exists():
        raise ValueError("database already exists")
    context_path = _context_path()
    if context_path.exists() or context_path.is_symlink():
        raise ValueError("live context already exists; finish or explicitly archive that run first")

    functions = dict(api or _default_api())
    required = {"prepare_live_run", "register_initial_plan", "commit_initial_spec",
                "execute_live_registered_experiment"}
    if set(functions) != required or any(not callable(functions[name]) for name in required):
        raise ValueError("adaptive bootstrap API is invalid")

    prepared = functions["prepare_live_run"](target, run_id)
    if (not isinstance(prepared, dict) or prepared.get("run_id") != run_id or
            prepared.get("mode") != "live" or Path(prepared.get("db", "")).resolve() != target):
        raise ValueError("live run preparation returned an unexpected context")
    functions["register_initial_plan"]("family_screen", BASELINE_REASON)
    experiment_id = functions["commit_initial_spec"]("family_screen")
    if not isinstance(experiment_id, str) or not experiment_id:
        raise ValueError("initial family_screen registration failed")
    result = functions["execute_live_registered_experiment"](experiment_id)
    result_id = result.get("result_id") if isinstance(result, dict) else getattr(result, "result_id", None)
    status = result.get("execution_status") if isinstance(result, dict) else getattr(result, "execution_status", None)
    if not isinstance(result_id, str) or not result_id or status != "completed":
        raise ValueError("host-seeded family_screen did not return a completed result")
    return {
        "run_id": run_id,
        "database": str(target),
        "experiment_id": experiment_id,
        "result_id": result_id,
        "execution_status": status,
        "primary_choice_source": "host_seeded_baseline",
        "primary_selection_reason": BASELINE_REASON,
        "primary_role_model_called": False,
        "next_step": "run_adaptive_followup.py asks Omnigent to choose the next discovery action",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="new SQLite database path under runs/")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare_adaptive_run(args.database, args.run_id), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
