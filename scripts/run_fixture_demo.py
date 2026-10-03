"""Two-round terminal demo; fixture values are not scientific results."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nova.fixture_engine import execute  # noqa: E402
from nova.runtime import Proposal, Run  # noqa: E402


def main() -> None:
    print("NOVA-MAT fixture demo (DEMO ONLY; numbers are not scientific evidence)")
    base = {"mode": "fixture", "seed": 1729, "bootstrap_repeats": 50}
    run = Run("Which family has the higher observed screening pass rate?", execute)
    run.freeze_hypothesis("H1: chalcogenide observed pass rate exceeds oxide")
    run.register_plan([
        Proposal("FIX-ROUND-1", "family_screen", {**base, "template": "family_screen"}),
        Proposal("FIX-ROUND-2", "threshold_sensitivity", {**base, "template": "threshold_sensitivity"}),
    ])
    print("planner | candidates=family_screen,threshold_sensitivity | chosen=family_screen")
    run.choose("FIX-ROUND-1")
    first = run.run_first()
    print(f"round 1 | {first.template} | delta={first.delta:+.3f} | next=threshold_sensitivity")
    run.submit_skeptic_review(
        concern="The main fixture result is inconclusive and may depend on the ehull threshold.",
        next_template="threshold_sensitivity",
        result_id=first.result_id,
    )
    print("skeptic | concern=inconclusive threshold dependence | next=threshold_sensitivity")
    second = run.run_second("FIX-ROUND-2")
    for point in second.points:
        print(f"round 2 | ehull<={point['ehull_max_ev_atom']:.3f} | delta={point['delta']:+.3f}")
    print(f"decision | state={run.state.value} | replace fixture executor before scientific interpretation")


if __name__ == "__main__":
    main()
