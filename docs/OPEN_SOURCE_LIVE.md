# Open-source live preparation

This path uses the open-source SDK `codex` harness. The checked-in pilot currently pins `gpt-5.6-luna` for root and all three sub-agents; later runs may assign different explicitly named models per role. `codex-native` is forbidden here because its terminal wrapper can expose shell/file tools outside the function-tool allowlist. Omnigent 0.16's Codex SDK controls are environment settings, so native tools and web search must be disabled at launch. It requires A's prepared `data/manifest.json`; no fixture hash or documentation result is accepted.

The live session has a bounded 48-call budget. This accommodates two discovery rounds plus reviews while remaining finite. The PI must record child session IDs, avoid wasteful inbox polling, and pass only the actual first `Result.result_id` to `commit_next_spec`; placeholders or guessed IDs are invalid.

```bash
python scripts/prepare_live_run.py --db /tmp/nova-live.sqlite --run-id live-demo
.venv-omnigent/bin/python scripts/run_open_source_live.py
```

Success means SQLite contains live `run_created`, `objective_registered`, and `hypothesis_frozen` events, then the bounded Planner/PI/Runner/Skeptic flow writes two validated discovery results. Skeptic must call `submit_final_review`; PI then calls `freeze_final`, which returns only the frozen protocol ID and `holdout_experiment_id`. The holdout is not executed until a controlled Runner interface exists. Preparation creates no selection or result. The database is 0600, `.nova` is 0700, and context is atomically written as 0600. Environment variables cannot redirect the run. No real model call is made by these tests.
