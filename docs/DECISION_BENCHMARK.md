# NOVA decision benchmark

The decision benchmark evaluates a frozen discovery-only corpus. It scores whether a proposed action is available, citations match the packet, and claim tags stay within the evidence rubric. It does not score prose accuracy or scientific quality. The benchmark-local reference `native09-main` is an alias in the supplied packet, not a canonical NOVA Result ID.

The default command is offline: it runs the fixed threshold-then-method-then-stop rule over the corpus and makes no model calls. Reports are new JSON files under `runs/`; existing files and paths outside `runs/` are rejected.

```sh
.venv-omnigent/bin/python scripts/run_decision_benchmark.py
```

The optional Omnigent arm compares one independent single-role turn with Planner, Skeptic, and PI turns on the first case. It is capped at one case, one repetition, four requested model calls, 45 seconds per call, and 180 seconds total. There are no retries. Each raw response, sanitized error, elapsed time, and provider usage (or `null` when unavailable) is recorded. A failed or structurally invalid turn remains in the report and produces a nonzero exit status.

```sh
.venv-omnigent/bin/python scripts/run_decision_benchmark.py --enable-model-calls
```

The SDK runner uses Omnigent `CodexExecutor` with native tools, web search, skills, and code mode disabled. Each role receives no registered tools and runs in a fresh session; the SDK session is interrupted on failure and closed with bounded cleanup. The host only records decisions. It cannot submit NOVA decisions, authorize an experiment, run SQL, execute science, or access a holdout. This measures SDK-hosted role decisions, not native Omnigent dispatch or the full scientific workflow.

Add `--output runs/name.json` to choose a report name. The path must be new and remain under `runs/`.
