# Native startup failure: handoff to Team B

Source base: main `433bdf55298aa74adf9c88c0f3f8d3fc161105bc`, after B PR #22 and A PR #23. The prior offline Linux regression passed 424 tests; this report concerns a separate actual run, not those tests.

## Actual attempt

Run `postfreeze-20261004T062802Z-f7a0b41a` used Ubuntu WSL, Python 3.12.13, Omnigent 0.16.0, Codex CLI 0.160.0, and model `gpt-6-luna`. The user explicitly approved the aggregate project/model inputs to OpenAI. A invoked the official entry points in a fresh source snapshot and database:

```sh
python scripts/prepare_adaptive_run.py --database <fresh-db> --run-id <fresh-run-id>
python scripts/run_native_adaptive.py --enable-native-live --finalize-discovery --execute-frozen-holdout --remaining-seconds 600 --model gpt-6-luna
```

Preparation exited 0 in 3.697 seconds and persisted one host-seeded `family_screen` Result. The native stage exited 1 in 76.576 seconds, without hitting its outer timeout:

```text
Error: Codex app-server closed stdout
RuntimeError: Omnigent native adaptive CLI exited with status 1
```

The native audit contains two executor-start records, zero completed turns, zero registered tool requests and zero tool completions. These are local trace counters, not exact provider API or billing counts. No autonomous selection or completed model response is established. There are zero holdout events. A read-only, immutable database check found exactly one Spec/Result, classified as `family_screen/discovery`; zero frozen protocols; and no holdout claim table or entry. There is no holdout Result. A checked the Linux process list for the failed snapshot's working directory and executable/argument paths: no matching processes remain. A has stopped and will not start parallel live validation. The failed attempt and its original partial Result were preserved; A did not retry or renew its deadline. Raw data, credentials, active databases and private logs are not published.

## Startup-only reproduction

Using the same copied CLI, configuration flags and launcher environment, a bounded probe sent only the Omnigent `initialize` JSON-RPC request. It did not create a thread, turn, scientific execution or model call:

```sh
codex app-server -c features.code_mode_host=true -c features.code_mode=false -c 'web_search="disabled"'
```

With `CODEX_HOME=/mnt/c/Users/Herbert/.codex`, the probe exited 1 in 0.299 seconds. Its stderr exposed the underlying startup error:

```text
Error: failed to initialize sqlite state runtime under /mnt/c/Users/Herbert/.codex: failed to initialize state runtime at /mnt/c/Users/Herbert/.codex
```

With only `CODEX_HOME` changed to a new empty directory on the Linux filesystem, the same binary, flags and initialize request succeeded in 0.42 seconds, with no stderr. No authentication file was copied or read. This isolates the observed startup failure to initializing against the existing Windows-backed profile as configured; it does not distinguish mount behavior, existing profile state/configuration, permissions, or another profile-specific cause. The empty-profile probe does not establish logged-in model execution.

## B's next check

Use B's own existing, authorized Codex profile on a Linux filesystem, first verify app-server initialization, then confirm the required SDK guard configuration. Preserve the frozen science inputs and source bytes. If B can run the real workflow, coordinate a single host's ownership before starting a fresh run/database with the original 600-second budget and the official controlled holdout gate. Do not resume this failed run, reuse native06, reset A's attempt marker, invoke the holdout directly, or force a threshold choice when the planner selects method comparison or stopping.

A's actual attempt failed before holdout execution. This handoff does not assert a complete workflow, independent scientific validation, model latency improvement or measured cost benefit.
