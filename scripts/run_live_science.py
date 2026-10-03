#!/usr/bin/env python3
"""Run one host-scripted live discovery experiment and export its evidence."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nova.evidence import export_run  # noqa: E402
from nova.experiments.executor import active_dataset_sha256, execute, export_science_artifacts  # noqa: E402
from nova.storage import Storage  # noqa: E402
from nova.workflow import PersistentWorkflow  # noqa: E402


def _proposal(experiment_id: str, template: str, dataset_sha256: str) -> dict:
    spec = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "hypothesis_id": "H1",
        "dataset_sha256": dataset_sha256,
        "split": "discovery",
        "template": template,
        "groups": ("oxide", "chalcogenide"),
        "bandgap_method": "opt",
        "gap_window_ev": (1.1, 1.8),
        "ehull_max_ev_atom": 0.05,
        "bootstrap_repeats": 2_000,
        "seed": 1_729,
        "timeout_seconds": 120,
        "mode": "live",
    }
    return {
        "proposal_id": experiment_id,
        "template": template,
        "spec": spec,
        "estimated_seconds": 120,
        "learning_score": 3,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a real family_screen over the prepared frozen dft_3d snapshot."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=ROOT / "runs" / "live-science.sqlite",
        help="host evidence database (default: runs/live-science.sqlite)",
    )
    args = parser.parse_args(argv)

    try:
        dataset_sha256 = active_dataset_sha256()
        run_id = "live-" + uuid4().hex[:12]
        family_id = f"{run_id}-family-screen"
        threshold_id = f"{run_id}-threshold-sensitivity"
        args.database.parent.mkdir(parents=True, exist_ok=True)
        storage = Storage(args.database)
        workflow = PersistentWorkflow(
            storage,
            objective="Compare frozen discovery pass rates for oxide and chalcogenide compositions.",
            mode="live",
            run_id=run_id,
            experiment_executor=execute,
        )
        workflow.freeze_hypothesis(
            "H1: chalcogenide discovery compositions have a higher observed screening pass rate than oxides."
        )
        workflow.register_plan([
            _proposal(family_id, "family_screen", dataset_sha256),
            _proposal(threshold_id, "threshold_sensitivity", dataset_sha256),
        ])
        # This is a transparent host-scripted choice for the first integration
        # run; the script does not claim an Omnigent agent selected the test.
        workflow.select(family_id)
        result = workflow.run_first()
        evidence_dir = ROOT / "runs" / f"live-evidence-{run_id}"
        export_run(storage.path, run_id, evidence_dir)
        export_science_artifacts(result, evidence_dir)
    except Exception as error:
        print(f"live science run failed: {error}", file=sys.stderr)
        return 1

    print(f"run_id={run_id}")
    print("integration_mode=HUMAN_SCRIPTED_LIVE_SCIENCE")
    print("selection=family_screen (explicit scripted choice)")
    print(f"result_id={result.result_id}")
    print(f"scientific_status={result.scientific_status}")
    print(f"evidence_dir={evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
