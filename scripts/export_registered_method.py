#!/usr/bin/env python3
"""Export evidence for one already completed registered method audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-id", required=True, help="completed run-owned method audit ID")
    parser.add_argument("--output", type=Path, help="new or empty directory under runs/")
    args = parser.parse_args(argv)
    try:
        from nova.method_evidence_export import export_registered_method

        output = export_registered_method(args.audit_id, args.output)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        print(json.dumps({
            "run_id": manifest["run_id"],
            "audit_id": args.audit_id,
            "evidence_directory": str(output),
            "evidence_sha256": manifest["method_audit"]["evidence_sha256"],
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"registered method export failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
