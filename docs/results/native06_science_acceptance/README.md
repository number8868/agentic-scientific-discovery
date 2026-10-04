# A independent acceptance of native run 06 science

Based on main `903579c` after B PR #20. Source:
[native run 06](../native_adaptive_live_06_completed/README.md), executed on
`955aaea`. A replayed the existing portable science preflight and inspected
the published discovery, review, finalization and model-tool evidence. No
scientific dependency, frozen protocol, original evidence or B runtime was
changed for this acceptance.

The [science preflight](audit.json) accepts both registered Results, their
immutable payloads, the original OPT family/threshold protocol, canonical
review/freeze hashes and the derived unexecuted holdout Spec. The exported
unredacted final PI text matches its original and export hashes. This portable
check still reports native completion and holdout execution permission as
unverified; the separate [B host acceptance](../native06_host_acceptance.json)
records original CLI exit 0 and the guarded response checks.

[Independent inspection](independent_verification.json) checks all 12
manifest entries and 13 inventory hashes, registered/computation/payload/Result
identities, historical primary/full-grid facts, 21 recorded tool-call pairs
and three accepted review/freeze packets. The recorded choice and Runner
transport hashes also match. Six guarded processes record ten completed
model turns. Two final-review requests are recorded, with one saved accepted
packet; the other's arguments/cause remain unknown. Keep that attempt in
latency/usage accounting. Published trace consistency does not attest
model/provider identity or OS confinement.

The primary OPT counts remain 3/7,657 oxide and 6/3,158 chalcogenide passes;
the contrast is 0.15081 percentage points with 95% resampling interval
[0.01109, 0.32220] percentage points. At the fixed stability limits
0.025 / 0.05 / 0.10 eV/atom, counts are 2 / 3 / 3 and 5 / 6 / 8.
Both reviews retain sparse-count uncertainty and discovery-only scope.
Threshold points reuse the same compositions and do not independently
validate the finding. The method option was available but not selected;
the separately audited 19-candidate OPT/MBJ shortlist is not a run06 Result.

One wording correction is needed for presentation: PI's frozen explanation
calls `NOVA-6438209c46bb471a` a registered Result; this is the experiment ID.
The Result is
`nova-result-ceb383e085a1a825c9b2c7f55441499ba1d3d626e0f6e060e7466b6a31b9ae5f`.
The original explanation, protocol bytes, frozen ID and hash are retained.
The final PI reply correctly says holdout is unexecuted and the evidence is
discovery-only. Initial hypothesis and primary screen remain host seeded.

A's independent complete Linux regression passed **405 tests, zero skips**,
in 54.82 seconds, using a fresh source-only checkout with no prepared data
or private context. [Validation](validation.json) records the actual JUnit
digest, tested source-byte checks and six unchanged protected digests.
This is a new independent offline check, not an additional live rehearsal.
Synthetic tests may execute scientific code; A made no new real-data science
or scientific-role model call and opened no private context/SQLite.

## Holdout execution conditions

The [source gate review](holdout_gate_review.json) separates native ownership,
frozen lineage, the atomic one-attempt claim and science budgets from B's
whole-run deadline. Run06's published 600-second budget has elapsed. Its
portable export cannot authorize continuation, recreate private context or
extend the original deadline. A did not invoke the holdout launcher or read
holdout outcomes.

B must connect the dedicated post-freeze Runner to A's existing gate inside
a fresh valid native run's original shared deadline. Keep the discovery
Runner guard and original OPT family/threshold protocol. Execute one actual
validation through the existing single-attempt interface; export its evidence
without recomputation after an export failure. Do not add the method audit
to that frozen validation or tune rules from holdout outcomes.

## Reproduce the read-only preflight

In the existing Linux environment, choose a fresh output directory:

```sh
python scripts/audit_discovery_bundle.py --evidence-dir docs/results/native_adaptive_live_06_completed --output runs/a-native06-science-audit-new
```

This command reads published discovery evidence only. It cannot execute a
holdout. [Published checksums](published_checksums.json) cover the new
aggregate acceptance artifacts; historical run evidence is unchanged.
Matched full-latency/cost comparisons, additional clean rehearsals and final
recording remain pending. Recorded event spans are not a speedup benchmark.
