# B post-freeze execution handoff

This change adds an optional native post-freeze Runner; it does not constitute
real holdout validation. The accepted native06 run remains frozen and expired.
Never reopen its deadline or reuse it for holdout execution.

## Execution contract

- Default behavior is unchanged. `--execute-frozen-holdout` requires
  `--finalize-discovery` and `--enable-native-live` on a fresh native run.
- The trusted parent authorizes the child explicitly, retaining the original
  run/database binding and one shared monotonic deadline for all three sessions.
- SDK tool executors are descendants, not direct launcher children. On POSIX
  the verified launcher child publishes its process-group owner PID; the tool
  checks that it remains in that live owner's bounded group. This is cooperative
  runtime validation, not an OS sandbox or protection against malicious host code.
- The distinct `holdout_runner` accepts only the host-registered experiment ID.
  Discovery Runner cannot access the holdout execution tool.
- A's immutable protocol checks, science limits, atomic one-attempt claim and
  Result validation remain authoritative and unchanged. Failures are not retried.
- B authenticates the prior freeze against the guarded PI tool call and exact
  completed-turn response hash, bounds worker time by remaining workflow time,
  and checks binding/deadline before claim, persistence and evidence export.
- Evidence export reads already persisted Results. It must not execute science
  again. An export/trace failure is a failed workflow, even if a scientific Result
  was already committed; preserve that Result and inspect feedback, not rerun it.
- The holdout export is scientific evidence, not a self-contained native
  authorization proof. The original private run audit and exact PI response
  remain separately required for native trace verification.

## Review limitations and acceptance

The deadline adapter temporarily wraps three private A gate hooks inside a
process-local lock and restores them in `finally`. This is a narrow compatibility
adapter, not a public A interface. Do not run unrelated gate invocations
concurrently in the same process. Cooperative checks are not nanosecond-atomic
SQLite deadlines; the parent process-group timeout is the outer wall-time bound.

Offline/mock tests establish wiring and failure behavior only. Before a real
attempt, A should review this adapter and approve the registered protocol, and
the team should explicitly approve one fresh-budget native rehearsal. Scientific
interpretation and holdout conclusions remain A's responsibility. Neither this
document nor the opt-in implementation claims a measured quality improvement.

Safe configuration preflight (no model or scientific calls):

```sh
.venv-omnigent/bin/python scripts/run_native_adaptive.py --check-only --finalize-discovery --execute-frozen-holdout
```

`configuration_validated` is not runtime readiness. A live attempt additionally
requires the matching executable `CODEX_CODE_MODE_HOST_PATH`, authenticated
model harness and a freshly prepared trusted context. Never use an old context
merely because this command parses successfully.
