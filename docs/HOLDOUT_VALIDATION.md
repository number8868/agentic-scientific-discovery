# Frozen holdout validation handoff

## Post-freeze interface acceptance

B [PR #22](https://github.com/number8868/agentic-scientific-discovery/pull/22)
is merged at main `cdde367`. Its optional post-freeze Runner now connects the
existing A gate inside the fresh native workflow's original shared deadline.
A's [independent acceptance](results/postfreeze_gate_acceptance/README.md)
found no blocking source defect within the reviewed scope; seven new
synthetic integration cases exercise the real A claim/transaction, nested
timeouts, tamper rejection and durable no-retry behavior. The combined Linux
regression passes 424 tests with no skips after correcting a test-tree venv
link, without production changes. This is offline compatibility evidence;
no actual holdout outcome is established.

The three temporary private-hook wrappers restore themselves in `finally`.
Do not invoke unrelated A gate calls concurrently in the same process.
SQLite deadline checks are cooperative; the bounded POSIX parent supplies
the outer cancellation deadline. The claim enforces one attempt per frozen
run, so one actual team validation also requires coordinated ownership across
hosts. A owns the next scientific acceptance and interpretation. A method or
stop choice cannot be substituted into the original family/threshold freeze.
Use a fresh valid native run and retain its original budget, exact guarded PI
response and frozen ID. Export alone is not native authorization, and any
failed/partial validation must be preserved without another computation.

## Latest native freeze review

Native run06 on `955aaea` completed the bounded discovery/review/freeze path
with original CLI exit 0; B PR #20 is merged at `903579c`.
A's [run06 science acceptance](results/native06_science_acceptance/README.md)
checks the same frozen family/threshold protocol and unexecuted holdout
`NOVA-HOLDOUT-57d4e4ffc96064d4`, including the persisted final PI reply.
Scientific consistency and clean discovery completion do not authorize an
out-of-deadline holdout call. Run06's original 600-second budget has elapsed;
do not reset it, rebuild its private context or import its portable events.

The [gate review](results/native06_science_acceptance/holdout_gate_review.json)
checks source only: A's bridge enforces immutable lineage, one attempt and
worker/science budgets. The historical run06 YAML stops with holdout
unexecuted; B PR #22 adds the separate opt-in connection described above.
A real validation still needs a fresh valid run, with the original protocol
and no method extension.
No holdout property, outcome or private runtime state was read in A's review.

B run03 and the following implementation notes are historical evidence:

B PR #16 records a real second Skeptic review and PI freeze in native run 03.
A's [independent portable acceptance](results/frozen_science_acceptance/README.md)
checks the original OPT family/threshold parameters, canonical protocol/stage
hashes, both discovery reviews and the derived unexecuted holdout Spec.
The original CLI exit 1 and post-freeze failure remain preserved. This is
scientific evidence consistency, not native execution authorization or clean
workflow completion. It does not replace the owning native database/context,
remaining deadline and single-attempt checks below, and must not reopen the
failed run or import portable events to manufacture authorization.

For the next accepted native run, B supplies the original untouched holdout ID
and dedicated post-freeze Runner under the shared deadline; A checks the native
lineage and interprets one controlled validation. Method audits cannot be
substituted for the frozen threshold follow-up. No real holdout result is
established by this acceptance stage.

This stage adds an execution path for the currently supported frozen `family_screen` plus `threshold_sensitivity` protocol. It does not establish a new live Omnigent run or a real holdout result. Development and verification use synthetic rows and synthetic registered runs; actual holdout outcomes remain closed until the real workflow has completed both discovery results, both native reviews and final protocol freeze.

During this stage, Team B published `luna-pilot-07` on main `51d45d9`. Its [portable export check](results/omnigent_complete_verification.md) passes with two discovery Results, two reviews, a freeze and an unexecuted holdout Spec. The fixed-role SDK evidence does not establish a full YAML workflow. Its final review's “missingness gap” wording is incorrect for the pass-rate endpoint and must not become the interpretation of validation results. Keep that review unedited for provenance.

Verification: **196 Linux tests passed**, including 13 synthetic science cases and 18 gate cases. The CLI integration invokes the actual scientific executor through the gate and exports evidence using only synthetic rows. The isolated full-suite checkout has no real prepared data or private context. The real metadata/byte-hash preflight passes separately. See [the recorded checks and source hashes](results/holdout_readiness.json).

## Host entry point

`nova.holdout_bridge.execute_live_registered_holdout(experiment_id)` accepts only the holdout experiment ID returned by `nova.decision_tools.freeze_final`. It uses the existing private live context and database. The existing `execute_live_registered_experiment` and science adapter remain discovery-only. Do not redirect the generic discovery tool to the holdout executor or expose paths, parameters or arbitrary callables to an agent.

The host checks the live run, native discovery selections/results/reviews, frozen protocol hash and event, derived holdout ID and registered parameters before a worker may read prepared compositions. One atomic database claim permits a single attempt for the frozen run. Successful repeated requests return the stored, authorized Result; failures and interrupted attempts do not automatically reopen the holdout. A timeout is an execution failure, not scientific contradiction. Worker time is at most 120 seconds and is capped by the remaining 360-second scientific compute budget. The separate bridge does not establish the planned 12-minute deadline across all model calls.

The worker calls `nova.experiments.executor.execute_holdout` with host-authenticated protocol and discovery evidence. This lower-level Python function is an internal computation API, not an independently authorized agent tool. Its validation does not replace registry/run ownership checks at the host boundary.

The existing process controller measures the worker compute/receive/exit deadline after synchronous process startup; startup and cleanup are outside that measured budget. A shared overall host deadline remains necessary to bound the entire workflow.

## Scientific scope

One holdout call computes the frozen primary endpoint (`opt`, inclusive gap 1.1–1.8 eV, ehull <=0.05 eV/atom) and the entire selected threshold grid (0.025, 0.05, 0.10). It keeps the primary endpoint distinct and does not select a best threshold after seeing holdout outcomes. The pre-existing extension protocol digest binds the supported grid; this stage does not support an arbitrary newly selected method/window/subgroup protocol.

Holdout quality requires at least 20 observed compositions per family, coverage >=80%, and both pass and fail endpoints. These are engineering quality gates, not statistical power guarantees. Bootstrap repeats remain 2,000 with seed 1729. The numeric interval describes resampling stability within this snapshot, not uncertainty across all real materials.

Compare each frozen discovery finding with its holdout counterpart separately. `replicated_in_snapshot` requires matching supported or matching reversed statuses and passing quality checks in both splits. Opposite supported/reversed statuses give `contradicted`; matching nonzero point-estimate directions involving an inconclusive status give only `direction_consistent_inconclusive`. Failed quality gates give `data_limited`. Missing comparison evidence must never produce replication. Missingness bounds crossing zero prohibit endorsement of ordering across all compositions; interpretation defaults to observed representatives only. A primary replication label does not establish replication of every grid point.

## Team B integration

Complete the real model-driven final Skeptic review and PI freeze first. Preserve the returned holdout ID. Add the dedicated host tool to the appropriate post-freeze orchestration step, with the same shared deadline and cancellation accounting as the rest of the run. Do not treat the previous partial `luna-pilot-06` export as a completed freeze, and do not invent a human freeze merely to make that model run appear complete.

The existing YAML explicitly stops after freeze and its Runner forbids holdout. Team B must update those prompts together with the new tool; adding a callable alone will not complete the workflow. The function declaration for a dedicated post-freeze Runner is:

```yaml
execute_live_registered_holdout:
  type: function
  callable: nova.holdout_bridge.execute_live_registered_holdout
  parameters:
    type: object
    properties: {experiment_id: {type: string}}
    required: [experiment_id]
    additionalProperties: false
```

Keep the discovery Runner's original guard. This implementation does not itself change Team B's YAML or upgrade its model settings.

For a trusted host invocation after a valid freeze, in the configured Linux/macOS environment:

```sh
python scripts/run_holdout_validation.py --experiment-id NOVA-HOLDOUT-<id>
```

Use the actual ID rather than this placeholder. The launcher exports run events/specs/results/reviews, final protocol and checksummed science payloads into a fresh `runs/holdout-export-*` directory. `--output` may select a new or empty directory inside `runs/`. Export failures leave the completed Result in the database; recover its evidence without starting a second computation. Native Windows retains the existing POSIX private-file permission limitation; use the verified Linux environment for the real bridge.

Do not commit the private live context, credentials, SQLite database or prepared dataset. After independent review, publish only the portable evidence and its limitations. Completion of this implementation milestone is not completion of the actual holdout experiment, formal YAML orchestration, three complete rehearsals, manual baseline, or final competition submissions.
