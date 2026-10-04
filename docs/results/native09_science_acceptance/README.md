# Team A acceptance of the existing native09 scientific evidence

Based on merged B PR #25, main `11f81c1`, and run
`native-adaptive-live-09` recorded against source `19a1c91`. A accepts the
portable scientific records as internally consistent. The native engineering
workflow is complete according to B's observed exit-0 run and published record;
the scientific validation remains `direction_consistent_inconclusive`.

## Scientific interpretation

| Primary endpoint, 0.05 eV/atom | Oxide passes / observed | Chalcogenide passes / observed | Difference (percentage points) | Stored 95% resampling interval (percentage points) |
|---|---:|---:|---:|---|
| Discovery | 3 / 7,657 | 6 / 3,158 | +0.15081 | [0.01109, 0.32220] |
| Frozen holdout | 1 / 3,282 | 3 / 1,354 | +0.19110 | [-0.03047, 0.48652] |

Both primary holdout groups have 100% field coverage and pass the frozen sample,
coverage and nonzero-endpoint gates. The interval crosses zero. Its point
scientific status is `inconclusive`; comparison with discovery is
`direction_consistent_inconclusive`, not demonstrated replication. All three
frozen holdout threshold intervals cross zero. Threshold comparisons reuse
the same representatives and are correlated analyses, not three independent
validations. These are JARVIS snapshot screening outcomes, not new materials
or measured physical performance.

Native09 selected threshold sensitivity from the offered threshold, method and
stop choices. Its hypothesis and primary baseline were host-seeded. The separate
OPT/MBJ audit was available but was not executed in this native run and is not
part of this frozen holdout protocol.

## Independent review and source binding

[audit.json](audit.json) is the aggregate-only review independently rerun by A's
root in the existing Ubuntu WSL Python 3.12.13 environment. Its bytes match the
separate reviewer output: SHA256
`b3a2d8f80b9115a8b82a0948e384fd74eae138d067fac8a1900a9a99503ed8eb`.
The [validation record](validation.json) distinguishes this review from B's
reported full regression of 426 passed; A did not repeat that suite in this stage.

The review verified all 13 manifest files, the 14-entry hash inventory, three
registered Specs/Results and immutable science payloads, canonical frozen
protocol identity, both review/parent links, freeze-before-holdout event order,
one exported holdout start/result, the native/shared Result mapping, recorded
aggregate arithmetic, missingness bounds and frozen classification gates.
Stored resampling intervals were classified without computing new intervals.

The source-only Linux review tree contains the exact 36 Git blob files from
`19a1c91`: 34 Python modules and the two threshold/method JSON protocols.
A independently matched every byte and Git blob object ID; see
[source_manifest.json](source_manifest.json). The recorded holdout implementation
is Git blob `4b4ac3890e15f78b4f10dd2e881bbc396b41a4e4`, SHA256
`6b89ac0594b522222d9fcd0a6da886cc727c4557d58fca191cd35da0bc148e44`.
The existing Windows checkout's CRLF representation differs from this Linux
blob. A used an isolated exact-byte copy and preserved the working scientific
source and dependency files.

The private review helper was adapted only to the actual export envelope:
13 declared files, separate pretty-printed versus canonical protocol hashes,
and schema-appropriate provenance fields. Exact artifact identities and
scientific gates remained required. Earlier local review-format rejections are
preserved privately and are not failed native09 scientific runs.

This stage made **zero model or scientific execution calls**, read no raw or
prepared outcomes, and performed no bootstrap resampling. The private SQLite,
exact PI response and provider state were not read. Portable consistency is
not runtime authorization, independent provider identity, OS confinement, or
verification of a global cross-host attempt lock. B's original native timing
and claim status remain separately attributed to its run report.

## Submission handoff

The two local [submission videos](../../demo/README.md) replay this existing
evidence and explicitly retain the inconclusive holdout outcome. No further
holdout computation is needed for recording or export. Matched full-latency
and cost baselines remain unfinished, so no acceleration or cost advantage
is claimed.
