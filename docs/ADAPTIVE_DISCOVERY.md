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

The native multi-agent path (`agents/adaptive-live.yaml` and
`scripts/run_native_adaptive.py`) now has a real discovery rehearsal:
`native-adaptive-live-02`. PI, Planner, Skeptic, and Runner produced five completed
model turns, two scientific Results, and a persisted PI final response. The
original CLI exited 1 during host trace validation; a hash-bound, host-only
transport recovery completed acceptance without another model or science run.
This is **completed with host validation recovery**, not a clean CLI success.
See `results/native_adaptive_live_02_recovered/`. The first failed attempt remains
preserved in [the failure and evidence boundary](NATIVE_ADAPTIVE_BLOCKERS.md).
Executor configuration and tool/turn linkage are recorded; they are not proof
of OS-level confinement or provider model attestation.

For a fresh native run, use a new database/run ID with `prepare_adaptive_run.py`,
then `run_native_adaptive.py --enable-native-live --model gpt-6-luna
--remaining-seconds 600`. Archive an existing live context deliberately first.
Each teammate needs their own authenticated Codex CLI, pinned Omnigent environment,
and matching code-mode host configured through `CODEX_CODE_MODE_HOST_PATH`.
Model selection remains configurable; Luna is not a protocol requirement.
The merged [registered-method evidence handoff](METHOD_EVIDENCE_HANDOFF.md)
is a separate read-only, completed-artifact integration, not a native model run.

Tests use mocked model/tool calls and synthetic rows; they establish engineering
behavior, not scientific outcomes. The authenticated `adaptive-live-02` rehearsal
also completed: the model received the real primary Result summary, chose
threshold sensitivity from bounded alternatives, and the host executed that
registered discovery follow-up. See `results/adaptive_live_02_with_science/`;
the earlier failed attempt is preserved separately in
`results/adaptive_live_01_failed_with_science/`. These portable bundles include
the registered scientific payloads, including the complete threshold grid.

This proves one evidence-informed Omnigent/Codex choice gating real host
execution, not the complete four-specialist workflow. The primary is host-seeded;
the persisted `skeptic` review is written by the host from that same selection
rationale, not a separately called Skeptic model. The follow-up Result is not
returned to this single decision turn. Requested model metadata is not provider
attestation. No holdout execution or speedup claim follows from this rehearsal.

The original pilot now has a 720-second role-sequence cancellation deadline.
Cancellation is not a hard process-exit deadline: cleanup takes additional time,
and Python cannot cancel an already-running thread. Scientific workers retain
their separate 120-second hard bound. Keep this distinction in timing claims.

The paired method path has no authorized holdout protocol. The legacy frozen
family/threshold holdout gate must not be used to validate it. Remaining acceptance
work includes a fresh clean-CLI native acceptance run, initial hypothesis autonomy,
final scientific review/freeze integration, separately frozen method holdout design
with A, and an honest measured comparison with manual/rule
selection and running all inexpensive tests. No speedup or novelty-first claim
is established by this patch.

The report validator checks row labels, aggregates, status gates, and interval
consistency. It does not recompute bootstrap intervals; published independent
scientific verification remains a separate evidence source.
