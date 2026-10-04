# Scientific interpretation and citation handoff

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
