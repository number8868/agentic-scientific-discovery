# Controlled decision tools

`nova.decision_tools` is the host-owned persistence boundary for the MVP
Planner/PI/Skeptic handoff. The model supplies only a bounded template choice
and explanatory text. The host supplies the run context, actor, IDs, dataset
hash, and immutable `ExperimentSpec` values.

The tools read the fixed live context loader (`nova.live_bridge._read_context`
when available) and never accept a database path, run ID, actor, arbitrary
specification, or filesystem path from the model. A small `decision_packets`
table is owned by this module so `Storage` remains unchanged.

`register_initial_plan` always persists two complete proposals:
`family_screen` and `threshold_sensitivity`. `commit_initial_spec` validates the
Planner selection and registers the frozen discovery spec using the prepared
manifest's active dataset SHA256. `submit_live_review` accepts only a stored
successful Result and a different bounded template. The MVP follow-up gate
allows only `threshold_sensitivity`; `commit_next_spec` sets its parent result
and review reference and records the PI's `second_selection` event.

Every invalid transition appends a host `schema_failed` event when a valid
context is available and creates no spec or result. Actors are constants from
the host wrapper, never model-provided fields. These are live-only decision
tools; fixture/replay runs must use their separate fixture path.
