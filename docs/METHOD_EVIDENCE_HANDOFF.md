# Completed method-audit evidence handoff

Team B's [adaptive discovery host](ADAPTIVE_DISCOVERY.md) owns method request
registration, experiment selection and the single-attempt worker. Team A's
evidence layer exports an **already completed** registered audit. It does not
register an experiment, call a model, execute scientific code or open holdout.

## Contract boundary

The canonical parent `family_screen` Result is preserved with its registered
Spec and content-addressed science payload. The method audit remains a
separate rich record linked to that Result and to B's immutable audit request.
It contains three arm statuses plus a different paired method-change
estimand. No overall method `Result.scientific_status` is invented, and no
method Spec enters the old frozen family/threshold validation protocol.

A's `build_method_evidence(request, audit_output, parent_result, parent_spec)`
checks frozen dataset/protocol/representative/split links, OPT-parent numerical
agreement, row semantics, aggregate quality gates and candidate guidance.
It retains all three arms, the separately named method-change contrast,
coverage, transitions and shortlist candidates. Full audit rows stay local.
Missing comparator gaps remain JSON null and their screening status remains
`unknown`.

The immutable scientific body excludes execution timestamps and elapsed or
phase timings. Its digest covers sorted compact UTF-8 JSON plus one final LF.
The original scientific executor's `human_selected` field describes the
extension's registration history; it does not describe a later model choice.
Actual adaptive choice provenance is exported separately, or explicitly
marked absent. `no_new_model_calls` in the scientific payload refers only to
the deterministic scientific executor.

## Export from the native run

After B's `execute_registered_method_audit(audit_id)` completes successfully,
use its actual returned audit ID in the same host-owned active run context:

```sh
.venv-omnigent/bin/python scripts/export_registered_method.py \
  --audit-id NOVA-METHOD-<actual-id> \
  --output runs/method-evidence-01
```

The Python host integration is
`nova.method_evidence_export.export_registered_method(audit_id, output=None)`.
The output must be new or empty and inside `runs/`. Registered, running,
failed, foreign-run and malformed audit references are refused. The exporter
reads completed source records without invoking the execution API. An export
failure is not permission to restart the science experiment; repair the
export and choose a fresh directory.

This first exporter covers B's bounded parent-family-plus-method run. It
rejects additional registered Specs or science Results in that run rather
than silently dropping them. A later native multi-step flow will need an
explicit run-scope extension before using this exporter.

The package contains the canonical parent run export and science artifact,
`method-audit.json` with aggregate/shortlist scientific evidence,
`method-evidence.json` with exact hash-bound JSON Pointer references,
`adaptive-selection.json` with recorded choice provenance or explicit absence,
and an extended checksum manifest. It excludes SQLite, private context,
prepared/raw data and full row-level audit data.

## Reviewer use

For every claim, carry the evidence SHA256 and JSON Pointer from
`method-evidence.json`. Cite the named arm for its counts, interval, coverage
and frozen status; cite the separate paired-method-change object for method
sensitivity; cite the candidate object for the same JID's gaps, status,
reason and next validation. Result-level parent references alone do not
support a claim about a particular candidate.

The current real scientific interpretation remains in the
[paired-method result](results/paired_method_audit/README.md). A positive MBJ
interval does not override the zero-oxide-pass degeneracy gate. Six missing
MBJ values are unknown, and a recommended calculation is not an executed
validation. See the [model-language audit](SCIENTIFIC_REVIEW_AUDIT.md) before
reusing the original Skeptic or PI wording.

B still owns consumption of these references by the next model reviewer,
formal multi-agent orchestration, full model latency and measured cost,
and comparison with a fixed rule or running all diagnostics. Successful
scientific export alone establishes none of those outcomes.

The [real registered integration](results/registered_method_integration/README.md)
verifies the completed-method path with one worker start and no model call.
B's separate [adaptive live run](ADAPTIVE_LIVE_VERIFICATION.md) chose threshold
sensitivity, so it does not yet demonstrate a model selecting this method
experiment or reviewing its candidate-level citations.
