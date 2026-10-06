# Parallel self-test runner

This is a new runner; the earlier 84-turn serial benchmark is not reused. It compares a persistent three-turn single-agent self-review with three independent Planner/Skeptic/PI turns. The 4-case development packets are synthetic and plumbing-only. The 24-packet exploratory corpus at [`docs/examples/parallel_selftest_v1.json`](examples/parallel_selftest_v1.json) is not approved for live use until an independent reviewer signs off distinct stems/dependencies. It is engineering-only, not science data, and never initializes the scientific engine, registry, or holdout path.

## Offline first

By default the CLI only validates the corpus, freezes a hashed manifest, and writes an exclusive run directory under `runs/`; it makes no model calls:

```sh
python scripts/run_parallel_selftest.py --stage development
```

To test the deterministic answer-key grader without a model, use the explicitly synthetic gold fixture:

```sh
python scripts/run_parallel_selftest.py --stage development --offline-gold-fixture
```

The gold fixture is not a model response, workflow result, or empirical evidence. Development output has no primary quality/effect estimate; blind prose adjudication remains pending. Reports keep those boundaries explicit. Each run writes an append-only, fsynced `events.jsonl` and an atomically replaced, fsynced `report.json`; the output directory is exclusive and existing evidence is never overwritten. The runner does not automatically resume an interrupted run.

## Model-call gates

Live execution remains opt-in and requires a separately authorized development budget. The development arm consumes 24 SDK turns (4 packets × 2 arms × 3 turns). The 288-turn exploratory stage is separate and is not enabled by this guide. It additionally requires an independent, pre-call pair/stem dependency audit. The CLI flag `--dependency-audit-approved` only records the operator's assertion; it is not itself review evidence or authorization. Do not pass it without a completed independent review and separate approved budget.

Live runtime requires the compatible POSIX/Codex setup described in [`docs/SETUP.md`](SETUP.md), including the validated `CODEX_CODE_MODE_HOST_PATH` configuration, Omnigent 0.16.0 and Codex CLI 0.160.0. Runtime identity, authentication, SDK availability, and process cleanup must pass the offline/live-readiness checks first. On cleanup or audit failure, the runner fails closed and stops; never weaken POSIX permissions to bypass a check.

```sh
python scripts/run_parallel_selftest.py --stage development --enable-model-calls
```

The runtime is still subject to implementation review and offline fault-injection acceptance. `--enable-model-calls` is a paid external action; no live call is made by default. SDK turns, provider-internal requests, retries, token usage, and billing are distinct; unavailable attestation remains `null`. There are no retries. Each attempted dispatch is durably reserved before the SDK worker can proceed. A failed/interrupted dispatch remains charged and is not automatically replayed.

The report distinguishes observed valid-delivery time from the 150-second deadline penalty used for operational screening. The deterministic grader checks contract and structured answers only; blind prose adjudication is pending, so screening remains `pending_blind_review`. Descriptive resampling is disabled unless the independent dependency audit was approved. Neither this runner nor its scores establish scientific utility, general multi-agent superiority, or superiority to a one-shot/deterministic-tools deployment baseline.

Useful checks:

```sh
python -m pytest tests/test_parallel_selftest_runner.py
python scripts/run_parallel_selftest.py --stage development
```
