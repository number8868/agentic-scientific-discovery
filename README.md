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
