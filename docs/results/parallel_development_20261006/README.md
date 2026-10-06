# Persistent versus independent-parallel: development run

**Result: the new request chain ran successfully; no efficiency or quality
improvement is established.** This is the four-case development stage, not
the unapproved 24-case exploratory study or a scientific-workflow benchmark.

Run: `parallel-selftest-20261006T032752Z-bc642ec8`.
Frozen implementation: `314cf19`; requested model `gpt-6-luna`, reasoning
`medium`, open-source Omnigent 0.16.0. Launcher exit: **0**.

## What actually completed

- **24/24 SDK turns**, 4 paired cases, **8/8 valid deliveries**; no host retry.
- Both arms scored **1.0 on all four structured-answer checks**. This checks
  objective answers and their contract, not independently adjudicated prose.
- Each single-agent arm reused one observed native thread for all three turns.
  Each parallel arm used distinct Planner, Skeptic and PI threads.
- All eight arms reported verified worker/descendant cleanup. No scientific
  engine, registry, data download or holdout was invoked by this isolated runner.
- Model identity, provider-internal request/retry counts, token usage and
  billing are not attested. `max_tokens=1200` is a request, not a verified cap.

Observed valid-delivery wall time includes host startup, SDK work, cleanup,
validation and output persistence. Arms ran sequentially; only Planner and
Skeptic overlapped internally.

| Development case | Persistent single-agent | Independent parallel + PI |
| --- | ---: | ---: |
| Unknown evidence | 9.273 s | 9.367 s |
| Conflicting constraints | 8.728 s | 9.498 s |
| Unit conversion | 13.060 s | 11.535 s |
| Combined denominator | 8.968 s | 11.925 s |

These are raw plumbing observations, not an effect estimate. Parallel was
slower on three cases and faster on one; answers tied on these easy cases.
The report deliberately leaves primary effect, intervals and full semantic
quality as `null`. This development set cannot establish a general advantage,
noninferiority, scientific utility, or a resume speedup claim.

## Evidence and audit

- [Full report and sanitized inputs/responses](report.json)
- [Append-only dispatch and delivery journal](events.jsonl)
- [Runner and reproduction boundaries](../../PARALLEL_SELFTEST.md)
- [Implementation review](../../PARALLEL_SELFTEST_REVIEW.md)
- [Frozen evaluation plan](../../SELF_TEST_PLAN.md)

The publication copies are byte-identical to the original completed run:

```text
report.json  e665152cbb9773b304257770042c27fcc2f7b9c43463cecac8ea677075e26fcc
events.jsonl 1ecb8b103fa8a52cf57996d15b413168f742bea92960e955e8f6881452c3dc65
manifest     d5b6bbab2eeb123b8fe9b59cd8339dc681cc48ba226b21696f0e6b956a53da2f
```

Offline verification included 504 passing regression tests and a final
28-test focused check after the narrow trace/exception fixes. These test
counts are engineering checks, not model-answer samples.

## Remaining decision

Do not spend the 288-turn exploratory budget yet. Several draft case pairs
share the same core template, so the dependency audit is unapproved; prose
and citation-support adjudication is also pending. The next work is to
independently review/redesign a harder, separate case set, freeze its rubric
and dependencies, and obtain the separately approved exploration budget.
The already completed development cases must not become selected evidence
of an advantage or be reused as confirmatory samples.
