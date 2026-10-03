# Team B → Team A science adapter

`nova.science_adapter.execute_science_experiment(spec)` is the B-owned seam to
A's controlled `nova.experiments.executor.execute` API. It accepts a canonical
`ExperimentSpec` or its registered dictionary form and returns A's canonical
shared `Result`.

Supported templates are currently `family_screen` and
`threshold_sensitivity`, both discovery-only. Fixture/replay/holdout modes,
unknown fields, dataset or cache paths, and callable/module injection are
rejected before A is called. Dataset selection remains A's host-controlled
prepared manifest; the adapter never accepts a data location.

The adapter verifies result `experiment_id`, `spec_sha256`, and
`dataset_sha256` against the registered contract. It propagates schema,
authorization, dataset, protocol, and computation errors. No such error is
converted into an inconclusive or other scientific status.

A's executor performs the richer threshold grid computation and stores
content-addressed payload/artifact references in `Result.artifact_ids`; B's
SQLite storage remains responsible for registry/event/result persistence.
