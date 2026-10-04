# Scientific method-review handoff

Team B owns the real model turns, role identity, run ledger, action selection
and execution gates. Team A provides the scientific input and structured
review validation. A passing review check establishes agreement of declared
facts and references with its input; it does not establish a model invocation,
an independent Skeptic turn or a complete autonomous workflow.

## Scientific interface

The input is built from an already validated `nova.method_evidence.v1` body
and its exact citation packet. The three arm comparisons remain separately
named, and the paired method-change contrast retains its different estimand.
Candidate references identify the same representative JID used by both
methods. Source evidence and review-input hashes bind a review to its actual
facts and disclosed candidate selection.

The default candidate sample is the first JID in each observed shortlist
category, with stable ordering. This is a host-selected sample, not a ranking
or a review of every shortlisted material. The host can request specific
JIDs, including the full shortlist, and must retain that scope in its trace.

Public integration functions in `nova.method_review`:

- `build_method_review_input(body, packet, candidate_jids=None, available_actions=('stop',))`
- `method_review_output_schema(review_input)`
- `validate_method_review(review, review_input)`

The input contains its own `review_input_sha256`: it hashes sorted compact
UTF-8 JSON plus a final LF with that one digest field omitted. This differs
from the file checksum of `review-input.json`, which includes the field.
Bind a model response to the input's value or the output schema's constant.
The source evidence digest covers the complete canonical method body plus LF.

The output schema requires three arm assessments, one named paired-method
change, every selected candidate, the scientific limitations, and an advisory
recommendation with at least one input-owned evidence reference. Candidate
assertions include family, both gaps, hull stability, method statuses,
category and next-validation guidance. Frozen quality flags remain visible
in the input. Units are explicit: gaps in eV, hull stability in eV/atom,
rates and coverage as fractions, and contrasts as fraction differences.
Numeric `1` and `1.0` are equivalent; booleans cannot replace numeric values.

The host supplies actions that are genuinely feasible in its current native
run. The initial interface permits stop and optionally the existing registered
threshold diagnostic. A review recommendation is advisory: validation does
not register or execute an action, reset an experiment attempt, or authorize
holdout. The old frozen family/threshold holdout protocol remains separate.

## Review acceptance boundaries

Structured validation checks exact source references and factual declarations:
named arm/contrast statuses, numerical values and units, paired subset
coverage, candidate JIDs, null comparator values, screening categories and
next-validation guidance. A missing MBJ value must remain unknown; a positive
interval does not override an inconclusive frozen status or a degenerate
endpoint. The contrast is not independent validation and MBJ is not truth.

Unrestricted rationale text still requires scientific review. A schema or
validator cannot prove that every sentence is correct merely because its
structured fields agree. B must preserve the actual independent model call,
tool-result return, role trace, timing and usage evidence alongside the
validated artifact. Host-generated fixture text must never be presented as
an independent model review.

## Runtime boundary

The portable command reads only the exported package manifest, method body
and citation packet. It does not read native SQLite, private context, other
Results, prepared data or holdout outcomes. It prepares input/schema or
checks an externally supplied review before writing to a fresh directory
under `runs/`. No model or scientific worker is launched.

Prepare the compact input and schema from the portable example:

```sh
.venv-omnigent/bin/python scripts/check_method_review.py \
  --evidence-dir docs/results/registered_method_integration \
  --output runs/method-review-input-01
```

Repeat `--candidate-jid <actual-JID>` to request a specific review set.
The default advisory action is stop. `--available-action
threshold_sensitivity` retains stop and adds that alternative; the host
still checks native legality and remaining budget.

After an actual model turn, check its separately saved response using the
same selection/action arguments:

```sh
.venv-omnigent/bin/python scripts/check_method_review.py \
  --evidence-dir docs/results/registered_method_integration \
  --review-json runs/native-review-response.json \
  --output runs/method-review-accepted-01
```

The response must be outside the immutable source package. A valid response
produces `accepted-review.json` and a structured validation report that
leaves prose semantics, model identity and independent Skeptic provenance
unverified. A rejected review creates no output. Input preparation produces
no accepted review. Output cannot be inside the source package.

The model output includes factual records and rationale text. B must choose
an adequate output budget for the emitted schema and measure actual usage;
the old single-choice selector's budget cannot be assumed sufficient for
this different role. A does not change experiment model configuration.

The previous method exporter covers a bounded parent-family-plus-method run.
Keep its existing scope until B publishes the concrete native multi-step
record shape. An explicit extension must preserve run ownership and reject
unapproved outcome reads; accepting arbitrary extra Results would not be a
valid integration shortcut.

Implementation is complete on `codex/method-review-integration`, based on
B's merged PR #11 at `44bc563`. The combined Linux regression passes 320
tests without skips. The [portable readiness kit](results/method_review_readiness/README.md)
contains an actual-source compact input/schema and the independent positive/
negative engineering checks; no model review or new science run is asserted.
