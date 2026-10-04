# B-owned native discovery finalization

Scope: orchestration, bounded wrappers, immutable evidence, runtime acceptance
and submission packaging. A owns prepared data, numerical experiments,
statistics and scientific protocol interpretation. No scientific parameter,
dataset split or holdout protocol is changed by this integration.

## Intended acceptance chain

1. Native Omnigent PI dispatches Planner and Skeptic against the actual primary
   discovery Result, chooses a feasible action, then receives Runner's result.
2. For the already supported family-screen/threshold-sensitivity path, a real
   final Skeptic invocation reviews the second Result and records its concern.
3. PI calls the bounded final freeze wrapper. The host derives parameters from
   immutable registered Specs and returns the unexecuted holdout ID.
4. Host acceptance checks persisted stage state and actual model/tool traces;
   a natural-language claim of completion is insufficient.

The bounded launcher uses two real native CLI sessions in one trusted child:
the discovery session, followed by the final-review/freeze session. Both share
the original absolute deadline, immutable run/database binding and audit file.
The second PI receives stored evidence through bounded tools; this is not
claimed to be continuation of the first PI conversation or a budget-reset run.

The method audit has a different record structure and no supported holdout
protocol here. A legal method choice or stop is not forcibly replaced with
threshold sensitivity. Such runs must report discovery-only finalization
availability honestly, not fabricate a ReviewPacket or frozen protocol.

## Boundaries

- No holdout execution is exposed by this implementation tranche.
- The existing `native-adaptive-live-02` remains completed with host validation
  recovery and original CLI exit code 1. It is not relabeled as a new clean run.
- No new source code or synthetic test establishes a real model invocation.
- CLI model overrides remain optional; Luna is a rehearsal default, not a
  scientific or architectural restriction.
- Context binding must also be checked inside the legacy decision tools that
  the new wrappers call, not solely at the first wrapper read.
- Timeout, method incompatibility, invalid review and scientific inconclusive
  results remain distinct outcomes.

## Remaining B acceptance

### Clean run 06

[Run 06](results/native_adaptive_live_06_completed/README.md) completed the
bounded path with original CLI exit 0, six guarded PIDs and ten model turns.
Raw final PI text is captured directly from the successful freeze turn and
persisted/verified separately from CLI display. The holdout remains unexecuted.
This closes the clean single-run discovery finalization gate, not the larger
initial-autonomy, three-rehearsal, benchmark or submission requirements.

### Recorded run 03

[Native run 03](results/native_adaptive_live_03_frozen_cli_failed/README.md)
performed the real second Skeptic review and PI freeze, with six guarded
executor processes and seven completed model turns. The holdout Spec is
registered and unexecuted. Its original CLI exit code is 1: the final verifier
omitted the primary-review tool's role mapping. That mapping is fixed and the
original recorded tool/turn trace passes posthoc verification without any
model/science rerun. The failure remains recorded; final-stage PI reply text
was not persisted before the failure. No clean CLI success is claimed.

The opt-in mode for a **fresh prepared run** is:

```bash
.venv-omnigent/bin/python scripts/run_native_adaptive.py --enable-native-live --finalize-discovery --model gpt-6-luna --remaining-seconds 600
```

Do not run this against completed/failed run 03, reset its budget or execute
holdout merely to demonstrate the new launcher. Keep its original manifest
source hashes and failure records unchanged. Future responses are printed
before final host verification so a verification failure cannot silently
discard captured CLI output.

Before claiming clean full finalization acceptance, run the optional path with
a fresh context and preserve its exit code, model/tool linkage, second review,
frozen protocol and untouched holdout ID. Do not rerun failed attempts in place.
After A reviews the supported frozen protocol and execution is approved, B can
connect a dedicated post-freeze Runner to the existing holdout gate; reading
holdout before this boundary or repeated holdout tuning is prohibited.

The larger original plan still requires initial hypothesis/selection integration,
three engineering rehearsals, measured baseline and final demo packaging. This
integration does not establish any speedup or full challenge completion.
