# Live registered-ID bridge

`nova.live_bridge.execute_live_registered_experiment(experiment_id)` is the
host-only live boundary. Its public function accepts only an experiment ID and
reads `.nova/live_context.json`, never environment variables. The context must
strictly contain `schema_version: 1`, `mode: live`, an absolute database path,
and a non-empty run ID. Context and SQLite files must be non-symlink regular
files with no group/world permissions.

The bridge requires every event for the run to be live, and requires a PI-owned
selection event for the requested registered experiment. Only family and
threshold sensitivity specs are allowed. It calls the controlled B→A science
adapter, persists the canonical result idempotently, and records runner
`running`/`result` or host `tool_failed` events. Fixture, replay, cross-run,
unknown-ID, path, and environment-variable substitutions are rejected.
