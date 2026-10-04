# B: bounded adaptive discovery extension

This extension preserves the original eight-role pilot and all published
scientific evidence. It adds a separate path from a completed discovery family
screen to a real choice of threshold sensitivity, paired method sensitivity, or
stop. It does not authorize holdout execution.

## Components

- `nova/adaptive_policy.py`: host-built options, actual parent evidence, explicit
  planning cost estimates, and bounded choice validation. No option is selected
  in advance. The model is configurable, not restricted to Luna.
- `nova/registered_method_audit.py`: run-owned immutable requests, one audit per
  run, atomic execution claims, no retry after failure, a 120-second controlled
  worker, and semantic validation of fresh and cached rich results.
- `scripts/run_adaptive_followup.py`: one Omnigent/Codex decision call, durable
  choice provenance, and execution of only the selected registered option.
- `scripts/prepare_adaptive_run.py`: deterministic, explicitly host-seeded
  primary baseline. This is not an autonomous initial model selection.

The method result is stored separately from canonical `Result` records. Its
three arms and paired method-change estimand must not be collapsed into an OPT
family result or called hypothesis replication. Frozen scientific output still
describes the original human-selected protocol; wrapper provenance describes
the new selection separately.

## Running a new extension

Use the installed, pinned environment and matching Codex host setup documented
for the original pilot. An existing `.nova/live_context.json` must first be
intentionally archived by the operator; these commands never overwrite it.
Use a new run/database, not a completed two-experiment run.

```sh
.venv-omnigent/bin/python scripts/prepare_adaptive_run.py --database runs/adaptive-01/run.sqlite --run-id adaptive-01
.venv-omnigent/bin/python scripts/run_adaptive_followup.py --database runs/adaptive-01/run.sqlite --run-id adaptive-01 --remaining-seconds 600 --model gpt-6-luna
```

Preparation computes the actual primary screen. The second command uses the
authenticated model and may compute one selected discovery follow-up. Do not
run these commands merely to inspect the repository.

## Boundaries and remaining work

Tests use mocked model/tool calls and synthetic rows. They establish engineering
behavior, not a new scientific outcome or live orchestration evidence. The new
path still requires a fresh authenticated live rehearsal before being described
as demonstrated adaptive orchestration. It is not the complete four-specialist
workflow in the technical plan.

The original pilot now has a 720-second role-sequence cancellation deadline.
Cancellation is not a hard process-exit deadline: cleanup takes additional time,
and Python cannot cancel an already-running thread. Scientific workers retain
their separate 120-second hard bound. Keep this distinction in timing claims.

The paired method path has no authorized holdout protocol. The legacy frozen
family/threshold holdout gate must not be used to validate it. Remaining acceptance
work includes specialist integration, fresh live evidence, separately frozen
method holdout design with A, and an honest measured comparison with manual/rule
selection and running all inexpensive tests. No speedup or novelty-first claim
is established by this patch.

The report validator checks row labels, aggregates, status gates, and interval
consistency. It does not recompute bootstrap intervals; published independent
scientific verification remains a separate evidence source.
