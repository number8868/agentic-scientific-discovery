#!/usr/bin/env python3
"""Run one or two host-scripted live discovery experiments and export evidence."""
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


def _proposal(
    experiment_id: str,
    template: str,
    dataset_sha256: str,
    *,
    parent_result_id: str | None = None,
    review_id: str | None = None,
) -> dict:
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
    if parent_result_id is not None:
        spec["parent_result_id"] = parent_result_id
    if review_id is not None:
        spec["review_id"] = review_id
    return {
        "proposal_id": experiment_id,
        "template": template,
        "spec": spec,
        "estimated_seconds": 120,
        "learning_score": 3,
    }


def _followup_reason(result) -> str:
    """Build a review from the observed first Result, not expected values."""
    groups = {summary.group: summary for summary in result.groups_summary}
    oxide = groups["oxide"]
    chalcogenide = groups["chalcogenide"]
    interval = result.resampling_interval
    interval_text = (
        "unavailable"
        if interval is None
        else f"[{interval[0]:.6g}, {interval[1]:.6g}]"
    )
    delta_text = "unavailable" if result.delta is None else f"{result.delta:.6g}"
    return (
        "HUMAN_SCRIPTED follow-up based on live Result "
        f"{result.result_id}: scientific_status={result.scientific_status}; "
        f"oxide observed passes={oxide.n_pass}/{oxide.n_observed} "
        f"(total={oxide.n_total}); chalcogenide observed passes="
        f"{chalcogenide.n_pass}/{chalcogenide.n_observed} "
        f"(total={chalcogenide.n_total}); delta={delta_text}; "
        f"95% resampling interval={interval_text}. Run the frozen "
        "threshold_sensitivity grid, report every point, and retain 0.05 "
        "as the primary endpoint."
    )


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
    parser.add_argument(
        "--two-rounds",
        action="store_true",
        help="run a HUMAN_SCRIPTED threshold follow-up after inspecting the first live Result",
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
        results = [result]
        if args.two_rounds:
            concern = _followup_reason(result)
            workflow.submit_review(
                concern=concern,
                next_template="threshold_sensitivity",
                result_id=result.result_id,
            )

            # Add actual lineage to the already registered threshold draft
            # before B canonicalizes and stores its immutable ExperimentSpec.
            # The review is keyed by its first Result ID in B's storage schema.
            followup = next(
                proposal
                for proposal in workflow.run.proposals
                if proposal.proposal_id == threshold_id
            )
            followup.spec["parent_result_id"] = result.result_id
            followup.spec["review_id"] = result.result_id
            storage.append_event(
                run_id,
                "followup_spec_linked",
                actor="pi",
                mode="live",
                payload_ref=result.result_id,
            )
            second = workflow.run_second(threshold_id)
            results.append(second)

        evidence_dir = ROOT / "runs" / f"live-evidence-{run_id}"
        export_run(storage.path, run_id, evidence_dir)
        for completed_result in results:
            export_science_artifacts(completed_result, evidence_dir)
    except Exception as error:
        print(f"live science run failed: {error}", file=sys.stderr)
        return 1

    print(f"run_id={run_id}")
    print("integration_mode=HUMAN_SCRIPTED_LIVE_SCIENCE")
    print("selection=family_screen (explicit scripted choice)")
    print(f"result_id={result.result_id}")
    print(f"scientific_status={result.scientific_status}")
    if len(results) == 2:
        print("followup_mode=HUMAN_SCRIPTED")
        print(f"followup_result_id={results[1].result_id}")
        print(f"followup_scientific_status={results[1].scientific_status}")
    print(f"evidence_dir={evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
