# Open-source live preparation

This path uses `codex-native` + `gpt-5.6-luna` for root and all three sub-agents. It requires A's prepared `data/manifest.json`; no fixture hash or documentation result is accepted.

```bash
python scripts/prepare_live_run.py --db /tmp/nova-live.sqlite --run-id live-demo
python scripts/check_live_config.py
PATH=.venv-tmux/bin:$PATH .venv-omnigent/bin/omnigent run agents/opensource-live.yaml
```

Success means SQLite contains live `run_created`, `objective_registered`, and `hypothesis_frozen` events, then the bounded Planner/PI/Runner/Skeptic flow writes two validated results. Preparation creates no selection or result. The database is 0600, `.nova` is 0700, and context is atomically written as 0600. Environment variables cannot redirect the run. No real model call is made by these tests.
