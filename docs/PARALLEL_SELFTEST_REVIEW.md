# Development-only implementation review

Date: 2026-10-05. Scope: synthetic engineering plumbing, four development
packets, two arms, three SDK turns per arm (24 requested SDK turns maximum).
This record is not a benchmark result, science approval, or model-call approval.

The main agent orchestrated three Luna-medium work streams (corpus/grader,
isolated SDK runtime, runner/report) and independently reviewed their code.
A separate read-only review by the corpus agent raised and rechecked blockers
in the runtime and runner; its final recommendation was conditional approval
of development plumbing only after the main agent's escalated offline tests.

## Resolved blockers

- Persistent baseline uses one actual native thread with a constant system
  prompt; the independent specialists use separate worker processes, and PI
  receives both outputs. No Planner draft is supplied to Skeptic.
- Arms run sequentially in the saved randomized order; only the independent
  specialists overlap. Each arm has its own deadline and timing origin.
- The parent reserves each unique role slot durably before granting dispatch.
  Duplicate slots, budget exhaustion, and persistence failure fail closed.
- Runtime success and report delivery status agree. Audit/cleanup failures
  stop later dispatches, rather than being silently followed by another case.
- Worker protocol remains on stdout despite SDK diagnostic redirection;
  forbidden tool events cannot become a successful answer.
- Detached-descendant cleanup is checked. A restricted environment which
  cannot run `ps` fails verification; absence of permission is not evidence of
  successful cleanup. Live execution requires the process-inspection permission.
- Development inputs now expose all required facts and answer schemas.
  The main agent independently recalculated the four answer keys. Correct
  semantic values and strict formatting are scored separately.
- The manifest covers runner/report/runtime/worker/grader, shared executor
  helper, cases, requested settings, limits, and saved schedule.

## Observed offline checks

- Initial complete regression: 497 passed in 24.66 seconds, before the final
  additional guard tests. This is not the final source-version test count.
- Final focused runtime, runner, and independent acceptance check:
  **23 passed in 1.42 seconds**, executed with process-inspection permission.
- Corpus checks: 9 passed; independent hand-calculated development checks:
  2 passed. All checks use synthetic fixtures or fake model executors.
- Gold-fixture CLI completed without any model calls. Its output explicitly
  labels development plumbing, not performance evidence.
- Final complete offline regression, including concurrent reservation,
  write/fsync/rename/directory-fsync fault injection and forbidden tool-event
  guards: **504 passed in 24.58 seconds**, with process-inspection permission.
- After the final trace-preservation and fail-closed exception changes,
  focused runtime/runner/independent acceptance: **28 passed in 1.28 seconds**.

## Not approved

The 24 exploratory packets remain a draft: several pairs share the same core
template, and their dependence audit is not approved. Interval calculation
must remain disabled. Free-prose accuracy and citation support still require
blinded adjudication. No efficiency or quality benefit is established by
these offline checks. No real science data, engine, registry, or holdout is
authorized by this review. The 288-turn budget requires separate approval
after these remaining protocol conditions are met.
