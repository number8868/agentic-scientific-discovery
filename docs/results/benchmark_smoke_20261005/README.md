# Offline fixture benchmark smoke — 2026-10-05

[Report](report.json), source commit `251a1e1172cc0d94561eda4de18fac38729b77dc`.
Run by the main agent after freezing the implementation and reviewing it with
an independent Luna reviewer. No model, native execution, prepared-data or
holdout call was made. This is a new offline engineering check, not native09.

| Check | Observed result |
| --- | --- |
| Registered two-step fixture path | 3 / 3 reached `SECOND_RESULT_READY` with successful fixture Results |
| Seven negative-control classes | 21 / 21 calls rejected with the expected exception class |
| Measurement | Raw `perf_counter` durations and explicitly bounded timing scope saved |
| Model usage / billing | Null; not applicable to this no-model run |
| Environment | macOS arm64, Python 3.12.13 |
| Final offline regression | 432 passed, 0 failed, 0 skipped; 22.93 seconds |

The seven negative controls cover an unregistered executor ID, a second
experiment before review, a review referencing the wrong Result, same-template
follow-up under another ID, a follow-up disagreeing with the review, an
over-budget choice, and an unregistered choice. They exercise actual core
runtime/tool guards. Six focused tests also check output containment, symlink
escapes, overwrite prevention, repetition limits and report contents.

The three fixture repetitions are deterministic smoke coverage, not independent
samples estimating deployment reliability. The path stops before final review,
freeze and holdout. In-process sub-millisecond fixture timing excludes startup
and export and is **not** scientific latency, native latency or agent speedup.
No single-agent / multi-agent / fixed-rule comparison has been measured here.

See [evaluation scope and next gate](../../BENCHMARK_SMOKE.md). Failed native
runs remain preserved separately; this smoke does not relabel them.

The final regression used the existing verified Omnigent/science environment
linked into the isolated worktree, with a separate temporary test directory.
The first full check lacked that repo-local environment and failed two
environment-presence tests; the environment link resolved them without any
production-source change. Final command: `.venv-omnigent/bin/python -m pytest
--basetemp=/private/tmp/nova-benchmark-final-20261005`.
