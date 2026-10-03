#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nova.evidence import export_run

def main() -> int:
    parser = argparse.ArgumentParser(description="Export one NOVA run's evidence")
    parser.add_argument("database")
    parser.add_argument("run_id")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    try:
        print(export_run(args.database, args.run_id, args.output_dir))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
