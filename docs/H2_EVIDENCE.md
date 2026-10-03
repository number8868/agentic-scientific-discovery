# Open-source Omnigent H2 evidence

Status: **passed for fixture orchestration** on 2026-10-03. This is not a live
scientific result and does not validate the Databricks managed route.

Verified local components:

- Omnigent `0.16.0` in the repository-local Python `3.12.13` environment.
- `tmux 3.7` in a separate repository-local Conda environment.
- Root PI, Planner, Runner, and Skeptic all used `codex-native` with
  `gpt-5.6-luna`. The checked YAML and captured runner log contained no Sol
  model route.
- The Runner called only
  `nova.omnigent_bridge.execute_fixture_registered_experiment` with the
  registered ID `EXP-H2-FIXTURE-001`.
- The fixed host-owned `.nova/context.json` pointed to the newly prepared run;
  no stale/default database was accepted as evidence.

Evidence in the context-selected SQLite database:

- one registered spec;
- six ordered fixture events: `run_created`, `hypothesis_frozen`, `selection`,
  `running`, `result`, and `review`;
- one result, `FIX-18070b1d5c78`, with `execution_status=completed` and
  `quality_flags=["fixture"]`;
- every event used the same run ID and `mode=fixture`.

The temporary database and model logs were intentionally not committed because
they are machine-local run evidence. Reproduce the check with
`docs/OPEN_SOURCE_H2.md`; export a redacted evidence bundle before the final
hackathon submission.

Remaining gates:

1. Run the same controlled path through `nova.science_adapter` against A's
   frozen JARVIS snapshot.
2. Add at least one second real experiment template before claiming a complete
   result-driven scientific loop.
3. Record a fresh submission-time run and export its evidence bundle.
