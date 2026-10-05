# Offline benchmark smoke: scope and next gate

This first measurement stage validates the evaluation plumbing against the
actual core fixture runtime. It is **not** a multi-agent performance benchmark,
native Omnigent acceptance, real-data result, or independent scientific validation.
Fixture outputs must not be combined with native09 outcomes or used as a speedup.

[Accepted smoke report](results/benchmark_smoke_20261005/README.md): 3/3 legal
fixture paths and 21/21 expected rejections across seven negative-control
classes. These small deterministic checks are not a model performance study.

From the repository root, with the fixture or full Python environment:

```bash
python scripts/run_benchmark_smoke.py --repetitions 3 --output runs/benchmark-smoke-first.json
python -m pytest tests/test_benchmark_smoke.py
```

Use the environment's Python rather than an older system interpreter. The
output must be new and under `runs/`. Existing reports are never overwritten.
The report records observations, legal positive controls, rejected negative
controls and actual monotonic-clock durations. The fixture workflow stops at
`SECOND_RESULT_READY`; it does not claim final freeze or holdout completion.
Model usage and billing remain null/not-applicable, not invented zero costs.
Repeated deterministic checks are engineering repetitions, not independent
scientific samples or evidence of general reliability.

## What this closes

- A runnable report writer and bounded repetition count.
- A positive registered two-step fixture path.
- Negative controls against actual runtime/tool guards, not fabricated agents.
- Explicit timing boundaries and fixture-only provenance.

## What remains before resume-ready performance claims

1. Freeze a discovery-only task corpus and rubric **before** paid measurement.
   Use budget, available actions, missing evidence and fault scenarios; never
   use holdout outcomes as prompts or tune the scientific protocol.
2. Keep fixed-rule and real model arms on the same inputs, tool surface,
   resources and terminal-output requirements. Model arms need actual calls;
   a scripted review is not a single-agent or multi-agent result.
3. Version the benchmark separately from
   [the original comparison plan](BASELINE_COMPARISON_PLAN.md), which compares
   adaptive, fixed-rule and run-all policies. A proposed single-agent arm is an
   additional protocol, not silently interchangeable with run-all.
4. Do not execute run-all by bypassing the current one-follow-up registration
   shape. Its legal multi-follow-up path remains separate work.
5. Predeclare repetitions, budget, arm order and failure handling. Retain every
   failed attempt; report interventions separately. Missing usage or billed
   cost remains null. Check completion, lawful decisions and evidence fidelity
   before comparing latency.
6. Review model rationales blind to arm where possible. Report limitations and
   the extra coordination cost even if multi-agent does not beat a baseline.

No new holdout or paid model execution is required for this smoke. The
completed native09 remains the recorded engineering acceptance reference.
