# H2 fixture bridge threat model

The bridge is intentionally a narrow host boundary. It accepts only an
experiment ID. Host context comes from the fixed repository path
`.nova/context.json` (exported as `nova.omnigent_bridge.CONTEXT_PATH`), never
from `NOVA_*` environment variables or agent arguments.

The context must contain exactly `schema_version`, `mode`, `db`, and `run_id`;
version is `1`, mode is `fixture`, and the database path is absolute. Both the
context and database must be regular non-symlink files with no group/world
permissions (`mode & 0o077 == 0`). Unknown fields, live/replay mode, relative
paths, missing files, symlinks, and environment-variable pollution fail closed.

The bridge then requires fixture events for the run and a PI selection event for
the requested registered experiment. It calls only the fixed
`fixture_engine.execute`, stores a canonical result idempotently, and writes
runner/host events. This is single-process/single-worker H2 protection; it does
not implement leases, CAS, or multi-process locking.
