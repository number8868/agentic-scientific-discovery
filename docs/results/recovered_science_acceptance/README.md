# A acceptance of the recovered native discovery rehearsal

`native-adaptive-live-02` passes independent checks of its published scientific
records and recorded model/tool linkage. Its status remains
**`completed_with_host_validation_recovery`**, with original CLI exit code **1**.
This supports a bounded discovery follow-up, not clean launcher success,
autonomous initial hypothesis selection, formal final review/freeze, or holdout.

Source: [B's unchanged recovered bundle](../native_adaptive_live_02_recovered/README.md)
at `be154a3`, first inspected at integration base `fc41d23`, then incorporated
into main `359de7a`. A checked all **13
manifest entries and 14 hash-inventory entries**, including the source README,
recovery record, 21 host events and 65 trace records. Source bytes and six
protected scientific source/protocol/dependency digests are unchanged.
The [independent verification](independent_verification.json) contains full
digests, arithmetic, trace linkage, usage fields and exact scope.

## Scientific facts

The registered Spec hashes and minimized computation hashes were independently
reconstructed and checked against their respective payload fields. Both
content-addressed Result IDs agree with the registered identities and payloads.
Primary scientific fields exactly match the original discovery result;
every threshold point, quality flag and stored bootstrap field matches the
historical threshold result. This compares stored evidence and arithmetic;
it does not authenticate raw data or recompute bootstrap samples.

| Frozen threshold (eV/atom) | Oxide passes / 7,657 | Chalcogenide passes / 3,158 | Difference (percentage points) | 95% resampling interval (percentage points) | Status |
| --- | ---: | ---: | ---: | --- | --- |
| 0.025 | 2 | 5 | 0.13221 | [0.00555, 0.29054] | `supported_in_snapshot` |
| **0.050, primary** | **3** | **6** | **0.15081** | **[0.01109, 0.32220]** | `supported_in_snapshot` |
| 0.100 | 3 | 8 | 0.21415 | [0.04830, 0.39859] | `supported_in_snapshot` |

Discovery coverage is 100%; missingness bounds collapse to observed rates.
The endpoint is a screening pass-rate contrast, not a missingness gap. There
are only 7–11 passes per point. The grid reuses the same compositions and is
correlated sensitivity, not independent replication or a general performance
claim. Primary threshold, representative structures and split are preserved.

## What the agents actually used

Planner's host-generated packet contains threshold sensitivity, exploratory
paired method sensitivity and stopping. Its evidence summary agrees with the
actual parent Result. All three options are recorded as feasible. This is an
option packet for one existing primary Result; the initial hypothesis and
primary screen were seeded by the host.

Skeptic ran in a separately recorded executor process. Its four field references
resolve to the parent Result, and its submitted argument hash matches the saved
review: 3 oxide and 6 chalcogenide passes, positive resampling interval with a
lower bound near zero, and complete coverage that does not remove sparse-pass
uncertainty. This is a scientifically correct bounded critique.

PI's accepted argument hash matches the saved threshold choice. The reason
responds to Skeptic's concern and the frozen threshold axis. Its 60-second
estimate fits the reported remaining budget, but is a planning estimate,
not measured latency. The reason does not demonstrate optimality over the
unselected method option. There are **two PI choice requests and one accepted
host commit**; the earlier request's raw arguments and response text are absent
from the portable package. Dispatch-completion status is not proof of a
successful choice. Retain this extra attempt in timing/usage accounting.

Runner's registered-ID request matches the selected Spec. Independently
reconstructed the returned registered Result and complete frozen three-point
grid. Canonical structured-response and Python-dict transport hashes match
the original function completion, dispatch completion, recovery record and
retrospective witness. The original dispatch record has no structured decode;
the later `tool_result_decoded_retrospectively` entry is a host witness,
not an additional model event. No worker or model rerun was needed for A's checks.

PI's saved final text hash matches the last completed PI turn's response
metadata hash. Its statement that contrasts and resampling intervals remain
positive at all three registered thresholds is correct. As a standalone final
report, it omits sparse-count/correlated-snapshot caveats and does not register a
post-result independent review, explicit stop decision or protocol freeze.
Keep the original response unedited. A's submission wording adds scope limits
as human-authored presentation text.

No method audit was selected or executed in this native run. It does not show
model review of the 19 candidate JIDs, missing MBJ values or paired arm statuses.
Those remain separately verified scientific evidence, not this run's agent acts.

## Model, runtime and timing boundaries

- All **21 request/completion call IDs** match recorded PID, role, tool,
  model and sequence. Four recorded executor PIDs completed five turns:
  Planner, Skeptic and Runner once each, PI twice.
- Each recorded executor start follows its own guard record. Recorded
  native-tool/web/skill settings and SDK-added provider selector are
  consistent. This does not test OS confinement, the remote provider or the
  teammate's host binary. `gpt-6-luna` is the recorded configuration; provider
  model identity remains unattested. The original runtime manifest and its
  pre-recovery source hashes are preserved, not relabeled as current source.
- The original orchestration-failed event precedes recovery events. This
  report does not erase that failure or change the separately preserved
  `native-adaptive-live-01` failed attempt.

| Recorded interval | Seconds | Boundary |
| --- | ---: | --- |
| Native start to last completed model turn | 191.293664 | Overlapping roles, tools and waiting; not isolated model latency. |
| Native start to original failure | 192.742208 | Includes the original host validation failure. |
| Native start to recovered completion | 708.706676 | Includes elapsed operator/host recovery time. |
| Run creation to recovered completion | 722.063728 | Includes registered primary setup; ends before final evidence export. |

These are cross-process timestamp differences from one recorded attempt,
not a complete benchmark or controlled latency comparison. Preserve all
five SDK usage records individually; cache/context/total fields have different
boundaries and do not establish billed tokens or cost. Billed cost is unknown
(`null`), and no matched fixed-rule/run-all timing exists. See
[the declared benchmark design](../../BASELINE_COMPARISON_PLAN.md).

## Reproduce the scientific audit

From Linux/WSL with the existing Linux environment and a fresh output directory:

```sh
.venv-omnigent/bin/python scripts/audit_discovery_bundle.py \
  --evidence-dir docs/results/native_adaptive_live_02_recovered \
  --output runs/recovered-science-audit-01
```

B's concurrent `d137017` update now admits two explicitly named new package files:
opaque UTF-8
`README.md` and strict JSON object `host-recovery.json`. Their hashes/counts are
checked; their prose/declared recovery status are not certified. The existing
scientific payload checker, guards and early holdout rejection are unchanged.
The CLI still reports native completion/model identity/prose validation as
unverified. Separate independent verification and human reading above provide
the narrower recorded-linkage and scientific-interpretation checks.

Reuse B's unchanged [CLI audit](../native02_submission_audit/audit.json) and
[CLI manifest](../native02_submission_audit/manifest.json); A independently
replays the CLI and compares their bytes rather than publishing duplicate
outputs. The
[validation record](validation.json) distinguishes test coverage from inspection
of real published artifacts. This A stage makes zero new real-data scientific execution
or scientific-role model calls, reads no prepared properties/holdout outcomes,
and performs no browser validation. Coding helper configuration is recorded
separately from Omnigent experiment model configuration. Regression tests can
execute scientific code on synthetic inputs; these are separate from the zero
new real-data production-run counters.

Next: B supplies a clean-CLI run, actual final review/decision/freeze and complete
benchmark accounting. A reviews those artifacts and performs real holdout only
through original valid frozen family/threshold lineage and the single-attempt
gate. This recovered run creates no substitute holdout authorization.
