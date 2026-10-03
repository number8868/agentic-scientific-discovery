# Open-source Omnigent H2 fixture

This route is fixture-only. It has completed a real Omnigent/Codex orchestration
smoke test, but it is not a scientific run. The YAML pins root and every
sub-agent to the official `codex-native` harness with model `gpt-5.6-luna`,
confirmed by `codex debug models`; this quota-conscious selection excludes
Sol/Reserve routes. Authentication comes from the local Codex login. No
account, token, or arbitrary import is selected by the repository.

## Run the offline handoff

From the repository root:

```bash
python scripts/prepare_h2_fixture.py --db /tmp/nova-h2.sqlite --run-id h2-open
python scripts/check_opensource_config.py
PATH=.venv-tmux/bin:$PATH .venv-omnigent/bin/omnigent run agents/opensource.yaml
```

Preparation atomically writes the bridge context to the repository-fixed
`.nova/context.json` (mode `0600`, parent mode `0700`). The context contains
only `schema_version`, `mode`, `db`, and `run_id`; no `NOVA_*` exports are
needed. The Runner callable is
`nova.omnigent_bridge.execute_fixture_registered_experiment` and accepts only
the registered `experiment_id`. After the run, verify the SQLite evidence
without treating it as scientific output:

```bash
python - <<'PY'
import json, sqlite3
ctx = json.load(open('.nova/context.json'))
db = sqlite3.connect(ctx['db'])
rows = db.execute("select result_json from results").fetchall()
assert rows, "no stored Result"
assert 'fixture' in rows[0][0]
print("stored fixture Result:", len(rows))
PY
```

A successful H2 fixture proves wiring and provenance checks only. It does not validate the real provider, model, Omnigent version, scientific data, or a live experiment.
