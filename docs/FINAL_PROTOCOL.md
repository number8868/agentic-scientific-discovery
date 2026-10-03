# Final protocol and holdout boundary

`nova.decision_tools.freeze_final` is the only B-side operation that opens the
final validation path. It accepts references to the two already-persisted
discovery results and a short explanation. The host verifies that both results
belong to the current run and completed successfully, and that the second
result has a persisted Skeptic review and review event.

The host copies parameters from the registered discovery Specs, computes a
canonical protocol JSON and SHA-256, and atomically persists that protocol,
the derived `holdout_validation` Spec, and a `final_protocol_frozen` event.
The caller cannot provide a holdout dataset, threshold, path, ID, or hash.
Repeated freeze attempts or references from another run fail closed. No
holdout result is read or executed by this operation; the returned
`holdout_experiment_id` is the only value that a separately authorized Runner
may submit after checking the frozen protocol.
