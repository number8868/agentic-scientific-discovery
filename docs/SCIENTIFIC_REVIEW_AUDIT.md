# Scientific interpretation and citation handoff

## Native run 06 independent science review

After B PR #20 merged at `903579c`, A replayed the portable preflight and
independently inspected run06's registered Results, historical numerical
facts, original frozen protocol and public model/tool trace. See the
[acceptance report](results/native06_science_acceptance/README.md).
Both Skeptic reviews retain sparse 3/7,657 oxide and 6/3,158 chalcogenide
passes, full coverage, the primary contrast/interval and all three correlated
threshold points. The final review explicitly distinguishes same-discovery
sensitivity from independent replication. The final PI reply names the
frozen protocol and holdout correctly and preserves discovery-only scope.

PI's frozen explanation calls `NOVA-6438209c46bb471a` a registered Result.
It is the experiment ID; the canonical Result is
`nova-result-ceb383e085a1a825c9b2c7f55441499ba1d3d626e0f6e060e7466b6a31b9ae5f`.
Correct this reference in future narration, without changing the original
explanation, protocol/hash or model-authored evidence. The method candidate
was available but not selected; no run06 method-candidate review is claimed.
Initial hypothesis and primary screen were host seeded. The clean B host
acceptance does not extend the original deadline or authorize a holdout from
its portable export; the [gate review](results/native06_science_acceptance/holdout_gate_review.json)
describes the remaining integration conditions.

## Native run 03 final review and freeze

After B PR #16 merged at `c6cea09`, A independently checked the actual second
Skeptic review and PI freeze against the published discovery payloads. The
review correctly cites sparse 3/7,657 oxide and 6/3,158 chalcogenide passes,
full coverage, delta 0.001508138314330796 and interval
[0.00011091441699668733, 0.003222018323127856]. It explicitly preserves that
the three threshold points reuse one snapshot and do not independently
resolve sparse-count uncertainty. PI freezes the same original OPT protocol
and registers holdout unexecuted; no method extension enters validation.

The [A acceptance report](results/frozen_science_acceptance/README.md) links
both review records, the frozen canonical protocol, derived holdout Spec and
the three accepted native tool packets to their recorded argument/response
hashes and completed turns. Two final-review and two freeze requests are
recorded, with one accepted persisted packet each. Dispatch success alone
does not establish scientific success for the unmatched requests.

Original CLI exit 1 and the terminal post-freeze failure remain unchanged.
Final-stage PI prose is absent; its recorded completion hash does not permit
reconstructing or interpreting that text. This audit establishes portable
scientific consistency, not clean CLI acceptance or holdout execution
authorization. Candidate-JID model review and autonomous initial hypothesis
selection remain unproved. Native context, ownership, deadline and the
single-attempt gate still apply to any eventual real validation.

B's concurrent PR #17 is integrated at `7da9673`. The same A preflight
accepts [run04's frozen scientific records](results/frozen_science_acceptance/native04_audit.json)
while leaving the original runtime failure, null final PI export and exact
failed-verifier input unresolved. Its final review's sparse 2–3 oxide / 5–8
chalcogenide pass range, primary 3/7,657 versus 6/3,158 counts and snapshot-only
interval interpretation agree with the recorded science. For presentation,
use "OPT computational gap" for its "optical gap" phrase. Its PI freeze
explanation names experiment ID `NOVA-3b16648b7eb16bdb` as a Result; cite the
canonical `nova-result-298fbfdcd574bc467752f4ea71e3b7f189f9db6752af9bd9b810fa8375fd4a86`
instead. These are wording corrections for future summaries; the historical
model-authored evidence remains byte-for-byte preserved.

## Recovered native discovery acceptance — 2026-10-03

First inspected B integration `fc41d23`, then synced main `359de7a`. A
independently checked the new
`native-adaptive-live-02` published bundle at `be154a3`: all 13 manifest/14
hash-inventory entries, exact historical science, four Skeptic references,
the accepted PI request, full-grid Runner transport and final PI text hashes.
The [acceptance report](results/recovered_science_acceptance/README.md)
distinguishes recorded linkage and human scientific reading from runtime/provider
attestation. Source package and frozen scientific bytes remain unchanged.

This evidence advances the bounded discovery follow-up: a separately recorded
Skeptic critique informed PI's choice, Runner returned the actual three-point
grid, and PI summarized it. Two choice requests produced one accepted commit.
Original CLI exit code was 1; the outcome is completed with host validation
recovery, not clean launcher success. Initial hypothesis/primary were host
seeded, and no formal post-result independent review, explicit stop/freeze,
real holdout or method-candidate model review is present. PI's short final text
is scientifically correct but needs sparse/correlated-snapshot caveats for
standalone presentation. Preserve it unchanged and add A-authored scope wording
in [the submission brief](SCIENCE_SUBMISSION_BRIEF.md).

Earlier snapshots below remain historical assessments of their named runs.

Earlier addendum: A's [independent stored-result acceptance](results/science_closeout/README.md)
checks the published failed native run from B `fe02c2a`. Both persisted science
Results and the fixed threshold grid match their historical evidence. The
registered and minimized computation hashes each validate against their own
contract. The saved sparse-count review and threshold recommendation are
scientifically acceptable as stored text, with resolved Result references.
Native workflow completion, independent model review and effective runtime
guards remain unverified; the original run stays failed. See the new
[submission wording](SCIENCE_SUBMISSION_BRIEF.md) and
[unmeasured baseline plan](BASELINE_COMPARISON_PLAN.md).

Reviewed on 2026-10-03 against the published `luna-pilot-07` evidence and the
paired-method audit. The original model text and frozen protocol remain
unchanged. This review is an independent reading of stored evidence, not a new
model run or holdout computation.

## Existing model evidence

The [portable export checker](../scripts/check_omnigent_luna_export.py) passes
for [the complete SDK export](results/omnigent_complete_run): two discovery
Results, two reviews and a final protocol. This establishes the exported
structure; it does not establish correct scientific language or autonomous
experiment selection.

| Record | Assessment | Required interpretation |
| --- | --- | --- |
| Initial Skeptic review, Result `nova-result-28dd8fd53dc6ab1092bbf8c93e4effd4cb801a78670093d4f15aafcf2b5c5fbe` | Refers to the actual family Result and correctly reports complete coverage, delta and interval. | The frozen status is still `supported_in_snapshot`. Sparse counts and the wide relative interval restrict precision and generalization; they do not change the stored status. |
| Final Skeptic review, Result `nova-result-190c4a6f95d37287bcd518a958a6a8025a032782fa660949bb112553d7584813` | The reference resolves, but the reason incorrectly calls the screening pass-rate difference a "missingness gap." | The endpoint is the joint gap-and-stability screening pass rate. Field coverage is 100% in both discovery families. |
| PI final-freeze explanation in `decisions.json` | Repeats the same incorrect "missingness gap" wording. | Preserve the immutable record, but correct the interpretation explicitly in the final report. Do not quote the explanation as a scientifically verified conclusion. |

The two recorded reviews cite Result-level evidence, not individual candidate
JIDs. They predate the paired-method experiment. They are not evidence that a
model has reviewed the 19 method-audit candidates.

## Method evidence the next reviewer must preserve

- Use the same representative JID for OPT and MBJ. The shortlist contains 0
  both-method passes, 3 OPT-only passes, 10 MBJ-only passes and 6 OPT passes
  with MBJ unknown. Unknown is not failure.
- Keep the three family comparisons separately named. Both paired arms are
  `inconclusive`. In particular, MBJ has zero oxide passes; its positive
  bootstrap interval cannot override the frozen endpoint-degeneracy rule.
- The paired method-change contrast has status `direction_positive`. It
  describes a different estimand and is not independent confirmation of the
  family comparison. A single unlabeled Result status would lose this
  distinction.
- Pair coverage is approximately 16.1% for oxides and 25.5% for chalcogenides.
  The comparison applies to the paired subset. MBJ is a computational method,
  not experimental truth.
- For a discordant candidate, cite its JID, both gaps, frozen stability value
  and category, then recommend checking methods/convergence/structural inputs
  for that same representative. For an unknown comparator, obtain the missing
  calculation before making a cross-method claim. These are recommendations,
  not completed experiments.

Source values and independently checked comparisons are in the
[recorded method audit](results/paired_method_audit/README.md). The new A
handoff should export precise references to named arms and individual
candidates while retaining the canonical parent Result's identity.

## Latest adaptive decision evidence

After syncing B's `22506ef`, independently checked every listed file hash in
the failed run 01 and completed run 02 bundles (8 and 9 files respectively).
Run 02's recorded choice is `threshold_sensitivity`; its reason cites the
actual parent Result, delta approximately 0.00151, complete coverage and
positive resampling interval. Those values agree with the saved parent
summary. The next-threshold-check recommendation is within discovery scope.

This supports one evidence-informed model choice gating host execution. It
does not show that a model selected the method audit or reviewed candidate
JIDs. The saved Skeptic event reuses the choice rationale through a host
call, so it is not an independent Skeptic model review. Run 01 remains a
failed decision attempt; its inspection packet is explicitly reconstructed.
See B's [bounded live-run verification](ADAPTIVE_LIVE_VERIFICATION.md).

A's [completed registered method export](results/registered_method_integration/README.md)
now supplies 29 exact method references, plus parent and selection references,
for that next review. Its own selection provenance is explicitly absent:
the integration check called the host gate directly and made no model call.

## Holdout readiness boundary

The real frozen input metadata and byte-hash readiness check passes. A
read-only inspection of the existing local Linux runtime found
`luna-pilot-06`, with two discovery results, one review and **no final protocol
record**. No scientific outcome rows were read in that inspection.

The portable `luna-pilot-07` export has a freeze, but it is not a replacement
for the native run database, owned events and artifacts required by the
[single-attempt holdout gate](HOLDOUT_VALIDATION.md). Execute that validation
from the native completed family/threshold run. Do not import exported events
to manufacture authorization, or substitute a method audit for the frozen
threshold follow-up. A method-specific holdout would require a separately
registered protocol; it is outside this handoff.
