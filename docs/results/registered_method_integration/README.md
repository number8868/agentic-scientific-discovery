# Registered method audit: real discovery integration

Run `a-method-integration-01` verifies Team B's registered method worker and
Team A's completed-result evidence export against the actual frozen JARVIS
discovery data. The primary family screen was host-seeded, and A selected the
method audit explicitly for integration verification. **No model call,
autonomous choice or holdout execution is claimed.**

The audit ID is `NOVA-METHOD-eae6c2c6b239297ef3dc503c`. Its canonical parent is
Result `nova-result-98324977135fd7591e967da489426d1749db26b9906d15f5fe049af8c81e9856`.
The method record stays separate from canonical Result storage because it
contains three family comparisons and a different method-change estimand.

## Verified scientific contents

All 10,815 eligible discovery representatives, every aggregate and every field
of the 19 shortlisted records reproduce the
[previously published audit](../paired_method_audit/README.md).

| Candidate category | Count |
| --- | ---: |
| Both OPT and MBJ pass | 0 |
| OPT passes, MBJ fails | 3 |
| MBJ passes, OPT fails | 10 |
| OPT passes, MBJ unknown | 6 |

Both paired family comparisons remain `inconclusive`. MBJ's zero oxide pass
count prevents a supported family claim despite its positive interval. The
separate paired method-change contrast remains `direction_positive`; it is
not replication. Pair coverage remains approximately 16.1% and 25.5%, and MBJ
is not experimental truth. This integration check is not an independent
scientific sample.

## Portable package

- [Scientific evidence](method-audit.json): frozen request/parent links,
  source hashes, three arms, method-change contrast, coverage and shortlist.
- [Citation packet](method-evidence.json): **29 exact method references**,
  plus separately hashed canonical-parent and selection references. Candidate
  pointers resolve to the stated JID and preserve null comparator values.
- [Selection provenance](adaptive-selection.json): `not_recorded`, correctly
  distinguishing this human integration check from B's model-selected path.
- [Run manifest](manifest.json), [registered parent Spec](specs.json),
  [parent Result](results.json), [native events](events.jsonl), and
  [parent science artifact manifest](science-artifacts.json).
- [Independent reproduction](independent_reproduction.json),
  [export verification](export_verification.json), and
  [measured host integration](host-run.json).
- [Combined verification record](validation.json): 280 Linux tests, final
  source checksums and explicit test/live-data/model boundaries.

The scientific evidence SHA256 is
`c1d0a12afe09474821b3c09bd7f96e2c04a69d7945b023838a1ace7087e0752c`.
Every manifest/artifact checksum and citation pointer was independently
checked. The exporter left the source SQLite SHA256 and complete event list
unchanged. Exactly **one method worker** started; a subsequent controlled
lookup returned identical cached output without new events. The portable
package excludes the private database, active context, raw/prepared data and
complete audit rows.

Scientific protocol/input validation plus computation took 0.8297 seconds in
the existing Linux Python 3.12.13 / NumPy 2.5.3 environment. Method registration,
worker execution, result validation and persistence together took 3.4837
seconds inside the already-running host process. The separate export process
took 1.8634 seconds. These are measured components with different boundaries;
they do not include model deliberation or establish acceleration.

The [A/B interface guide](../../METHOD_EVIDENCE_HANDOFF.md) explains how to
export a completed native audit. The
[interpretation audit](../../SCIENTIFIC_REVIEW_AUDIT.md) corrects the old model
wording while preserving the original frozen records. Formal model review of
this method evidence, complete orchestration and comparative model latency/
cost remain B's next integration. B's separate
[real adaptive trace](../../ADAPTIVE_LIVE_VERIFICATION.md) selected threshold
sensitivity; it is not a model-selected method run.
