# Method review readiness kit

This kit prepares scientific input for B's next independent reviewer from
the [real registered method evidence](../registered_method_integration/README.md).
It is a portable engineering verification, with no model invocation, new
scientific computation or holdout execution.

## Prepared input and scope

- [Review input](review-input.json) preserves all three arm comparisons,
  the distinct paired method-change contrast, original quality flags,
  units, candidate source references and mandatory scientific limitations.
- [Output schema](review-output-schema.json) defines the structured review
  and cited advisory recommendation that A can validate.
- [CLI manifest](manifest.json) binds the two files to their source package
  hashes and discloses the exact files read and review selection.

The default host sample contains three of 19 shortlisted materials:

| JID | Source category |
| --- | --- |
| JVASP-107267 | MBJ passes, OPT fails |
| JVASP-121313 | OPT passes, MBJ fails |
| JVASP-120874 | OPT passes, MBJ unknown |

These are the first JIDs under stable category/JID ordering, not a ranking
or a review of the entire shortlist. The independent check also requested
and validated factual fixtures for all 19 JIDs explicitly. Both paired
family statuses remain `inconclusive`; the separately named contrast stays
`direction_positive`. MBJ's zero-oxide-pass degeneracy flag remains visible.

The review input's binding digest is
`2385f3f74096280fd1cd4cf61a98427074dc9bdad2affc40e949e6807347f925`.
It hashes canonical input with its own digest field omitted. The manifest's
file checksum includes that field and is a different value. The source
scientific evidence digest is
`c1d0a12afe09474821b3c09bd7f96e2c04a69d7945b023838a1ace7087e0752c`.

## Verification and limits

The [independent verification](independent_verification.json) checks real
source values using host-written engineering review fixtures. Ten wrong
reviews are rejected: unknown as failure or zero, false support despite
the zero endpoint, cross-candidate citation, percentage-valued coverage,
boolean counts, a family status substituted for the method contrast,
wrong hull stability, a holdout action and an unsupported recommendation
reference. Integer/float equivalents pass, and source files are unchanged.

The [combined regression record](validation.json) reports **320 Linux tests
passed, no failures or skips**, including 40 new review/CLI cases. The
Linux checkout contains no prepared data or private live context. Windows
focused tests pass apart from one optional symlink-creation privilege case,
which passes on Linux. [Published file hashes](published_checksums.json)
cover this kit's files except the hash inventory itself.

No `accepted-review.json` is published here: the positive fixture was written
for tests, not by an independent scientific model. A successful structured
check cannot attest free-text semantics or model-role provenance. B must
perform and record the actual reviewer call, return its result to PI, choose
continuation/stop under native gates, and measure full model latency/cost.

Use the [A/B review interface guide](../../METHOD_REVIEW_HANDOFF.md) for API
and CLI integration. The original frozen family/threshold holdout remains
separate; this kit grants no holdout authorization.
