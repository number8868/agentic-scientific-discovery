# Open-source Omnigent environment

The repository-local environment was installed from PyPI using the official
manual-install route:

```bash
uv venv --python 3.12 .venv-omnigent
uv pip install --python .venv-omnigent/bin/python omnigent
```

Observed installation evidence (2026-10-03): `uv 0.11.8`, CPython `3.12.13`,
and `omnigent 0.16.0` (built `2026-09-29T19:16:56Z`). The environment is local
to `.venv-omnigent` and does not modify system Python. The installed package
included the default CLI dependencies; no provider call was made.

## Offline smoke checks

```bash
.venv-omnigent/bin/omnigent --version
.venv-omnigent/bin/omnigent --help
python scripts/check_open_source_env.py --yaml agents/databricks.yaml
```

The checker only runs local `--version`/`--help` and textual YAML checks. It
does not print environment variables, read credentials, launch `omnigent run`,
or contact a model provider. YAML parsing was also checked offline with the
installed PyYAML package; the Databricks route was not authenticated.

## Minimal next harness choice

The official YAML spec supports `executor.harness: codex`. The local `codex`
executable is present, so Codex is the lowest-friction harness to try after
the fixture bridge is integrated. Presence is not authentication evidence:
run a harmless local Codex smoke test or confirm its existing login through
the approved host workflow before claiming it works. If Codex auth is not
available, use the configured Databricks profile with `claude-sdk` and the
`databricks` extra; that route remains blocked until profile/model access is
verified.

Do not run the Databricks agent with a provider prompt during this offline
check. H2 success requires a real function-tool result from the registered
fixture experiment, not a natural-language claim by a model.
