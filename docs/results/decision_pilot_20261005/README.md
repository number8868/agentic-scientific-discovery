# Decision pilot — 2026-10-05

Source: `8ec1792`; frozen corpus digest is recorded in `report.json`.

- Fixed rule: 6/6 structural checks passed, offline.
- SDK pilot: one case, four requested Luna turns, exit 0, no retries.
- Single role: structural pass; 4.329 seconds.
- Planner/Skeptic/PI: structural pass; 12.582 seconds summed turn latency.
- All roles selected threshold sensitivity. No model arm demonstrated superiority.
- Provider usage was unavailable (`null`); cost is unknown, not zero.
- Full regression: 449 tests passed (exit 0).

This measures proposed-action availability, citation matching, and permitted claim tags, not scientific correctness, discovery benefit, or full workflow performance. Model arms used only case 01; do not compare their 1/1 result with the fixed arm's 6/6 as evidence of relative quality. No experiments, SQL, or holdout evaluation were executed.

Next: freeze a harder discovery-only comparison protocol, then obtain a budget before running repeated trials. Do not use this pilot to claim a quality improvement on a resume.
