#!/usr/bin/env python3
"""Run the exploratory paired OPT/MBJ method audit and write local reports."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nova.method_audit_report import ensure_output_dir_available, write_report  # noqa: E402


def _load_experiment():
    """Import the science executor only after the destination passes preflight."""
    from nova.experiments.method_sensitivity import run_experiment

    return run_experiment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the exploratory discovery-only paired OPT/MBJ method audit."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new report directory; an existing path is refused",
    )
    args = parser.parse_args(argv)

    try:
        ensure_output_dir_available(args.output_dir)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    try:
        run_experiment = _load_experiment()
        result, audit_rows = run_experiment()
        summary = write_report(result, audit_rows, args.output_dir)
    except Exception as error:
        print(f"method audit failed: {error}", file=sys.stderr)
        return 1

    print(f"output_dir={summary['output_dir']}")
    print(f"eligible={summary['n_eligible']}")
    print(f"shortlisted={summary['n_shortlisted']}")
    print(f"execution_status={result.get('execution_status', 'Unknown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
