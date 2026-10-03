# NOVA-MAT

NOVA-MAT is a 24-hour hackathon prototype for an auditable, result-driven
materials-screening workflow orchestrated with Omnigent.

The immediate milestone is deliberately small:

1. A Planner presents at least two valid experiments.
2. A PI approves one registered experiment.
3. A Runner invokes a controlled deterministic experiment tool.
4. A Skeptic cites the returned result and identifies a testable weakness.
5. The first result changes the second registered experiment.

The bundled fixture is for integration testing and demonstrations only. Its
numbers are not scientific evidence. A real JARVIS-backed executor supplied by
the science-engine owner must replace it for a live submission run.

## Local verification

```bash
python3 -m pytest
python3 scripts/run_fixture_demo.py
```

## Hackathon safety boundary

- Agents never receive a shell or arbitrary-path tool.
- The Runner accepts only a previously registered experiment identifier.
- `live`, `fixture`, and `replay` runs must remain visibly distinct.
- Provider credentials must stay in the host environment and out of prompts,
  events, results, and the repository.
- The checked-in Omnigent configuration is provisional until validated against
  the exact competition runtime and version.

See `docs/DEMO.md` and `docs/B_SECURITY_REVIEW.md` after the first integration
pass.

## Team A: first real-data milestone

The standalone JARVIS discovery `family_screen` is now implemented and verified. See [science-engine setup and results](docs/A_SCIENCE_ENGINE.md), [team status and handoff](docs/TEAM_STATUS.md), and the recorded evidence in [docs/results](docs/results).

These are real scientific-computation records. They now run through the registered experiment workflow with human-scripted selection and review; live Omnigent orchestration remains unverified. The bundled fixture remains explicitly non-scientific.

The real science executor now also supports the shared Result mapping and portable evidence packaging. See [registered science integration](docs/SCIENCE_INTEGRATION.md). Its validated control plane is currently human scripted; actual Omnigent model/tool connectivity remains a separate check.

The two-round real-data check is complete: the first family result informs a recorded threshold follow-up, and all three frozen thresholds retain the same observed direction. See the [threshold chart](docs/results/threshold_sensitivity.png) and [two-round evidence](docs/results/two_round_live_science). All 90 combined tests pass; holdout outcomes remain unexamined.
