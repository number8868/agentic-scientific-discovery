# Native discovery rehearsal — host validation recovered

Run: `native-adaptive-live-02`. Four actual Omnigent/Codex specialist processes
completed five model turns. The host-seeded family screen informed a separately
reviewed PI choice; Runner executed registered threshold sensitivity and PI
returned a final discovery-only summary. Two scientific Results are exported.

The original CLI exited **1**, after the model/science work, because host
verification rejected an SDK-added model-provider setting and did not decode
the SDK's Python-dict-repr transport. Host-only recovery safely decoded the
original transport, matched its recorded raw and structured SHA-256 hashes,
verified the original completed executor turns, and persisted the actual PI
response. No additional model call or scientific computation was performed.
Original failure events remain. The added transport witness explicitly says
`tool_result_decoded_retrospectively`; it is not a new model event.

`host-recovery.json` records the explicit recovery checks and original exit code.
The generic exporter conservatively labels guardrails unverified; the separate
recovery checks verify recorded executor configuration and tool/turn linkage,
not OS-level confinement or provider model attestation. The original runtime
manifest is preserved byte-for-byte, including pre-recovery source hashes and
requested-only configuration labels. It must not be relabeled as current source.

This is not a clean-CLI acceptance run, autonomous initial hypothesis selection,
final hypothesis freeze, holdout, replication, three reliability runs, or a
measured speedup. The corrected launcher has unit coverage but has not undergone
another paid native rehearsal. Model names remain configurable.

Inspect `adaptive_evidence.json`, `science-artifacts.json`, full registered
payloads, `native-model-audit.jsonl`, and `events.jsonl`. Verify exported file
contents against `hashes.json`; inspection requires no credentials/model calls.
