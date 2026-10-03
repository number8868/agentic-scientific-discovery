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
numbers are not scientific evidence. A real JARVIS-backed discovery executor
and a verified bounded Luna SDK pilot are now available; see the evidence below.

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

Team B subsequently published `luna-pilot-07`: its [portable check](docs/results/omnigent_complete_verification.md) passes with two discovery Results, two reviews, a final freeze and an unexecuted holdout Spec. This is still the fixed-role SDK host rather than verified YAML root-to-child orchestration. The requested model route is `gpt-5.6-luna`, not provider-attested backend identity. The final review's “missingness gap” phrase misidentifies the screening pass-rate endpoint; preserve the original record but use the actual numerical results for scientific interpretation.

These are real scientific-computation records. The early runs used human-scripted selection and review. The latest `luna-pilot-06` completed six actual registered-function calls through Omnigent with `gpt-6-luna`, including a model-authored review and the linked second experiment. Its preserved export remains partial: it has no second review, final protocol freeze or holdout Spec. See [the runbook](docs/OMNIGENT_LIVE_PILOT.md), [model/tool evidence](docs/results/omnigent_luna_run), and [independent verification](docs/results/omnigent_luna_verification.json). This is a bounded SDK host with fixed protocols; the YAML server and competition deployment remain separate checks.

The real science executor supports the shared Result mapping and portable evidence packaging. See [registered science integration](docs/SCIENCE_INTEGRATION.md). The recorded pilot compatibility baseline passed 154 Linux tests against main `f366048`; see team status for later verification. The exact prepared dataset is available to collaborators through the [private release handoff](docs/A_DATA_HANDOFF.md).

The separate [frozen holdout validation interface](docs/HOLDOUT_VALIDATION.md) requires native discovery results, both reviews and an immutable final protocol before a bounded worker may open holdout. Its implementation milestone uses synthetic verification; no real holdout result or complete YAML workflow is claimed. [Competition readiness and submission priorities](docs/COMPETITION_REVIEW.md) distinguish remaining work from completed evidence.

The earlier host-scripted two-round real-data check recorded the first family result and its threshold follow-up, and all three frozen thresholds retain the same observed direction. See the [threshold chart](docs/results/threshold_sensitivity.png) and [two-round evidence](docs/results/two_round_live_science). That milestone passed 90 combined tests; holdout outcomes remain unexamined.

The Windows Omnigent installation and B science-adapter check are now recorded in [Windows setup and verification](docs/OMNIGENT_WINDOWS.md). Both real templates reproduce in isolated Python 3.12. The latest synced suite includes four POSIX fixture checks that fail on Windows; see the current [team status](docs/TEAM_STATUS.md) for exact verification boundaries.
