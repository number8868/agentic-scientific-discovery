# NOVA-MAT evidence replay

A small static, buildless interactive replay of the published `native-adaptive-live-09` run. It uses only local HTML, CSS, JavaScript, and the adjacent `data.json`; there are no package dependencies, external fonts, analytics, API calls, or server-side experiment endpoints.

## Preview or deploy

Serve this directory as a static site with `index.html` as the entry page. Keep `data.json` beside it. The page is designed to work from a static HTTPS host; `file://` may block the JSON fetch in some browsers. The evidence summary can also be downloaded with the in-page button.

## Evidence boundary

The JSON is a compact, self-contained subset of `docs/demo/evidence.json` and the published aggregate exports under `docs/results/native09_completed/`. It contains timestamped event metadata (sequence, actor, type, UTC timestamp), aggregate threshold outcomes, lineage IDs, and source hashes. It excludes material-level rows and private runtime databases/traces. Repository evidence documents are private; the site shows the reviewable summary and hashes without requiring GitHub access.

The starting question and hypothesis were host-seeded. After reviewing the primary Result, the PI selected threshold sensitivity. Method comparison was offered only, not executed. The holdout classification is `direction_consistent_inconclusive` at all three thresholds, and the intervals cross zero. “100% coverage” refers only to the original OPT-selected cohort. The run-reported ~188-second trace span is not a speedup, cost comparison, or complete end-to-end benchmark.

## Data schema

`data.json` version 1 has these top-level sections:

- `run`: immutable run label, source commit, event span, export time, reported runtime counters, and aggregate artifact counts.
- `events`: sanitized event sequence records (`seq`, `utc`, `actor`, `type`) from the native event export.
- `stages`: seven interactive narrative phases with actual event sequence mapping, timestamps, summaries, and evidence notes. Evidence export is anchored to the exported manifest rather than invented as a native event.
- `roles`: recorded actors, event sequence references, and bounded responsibilities.
- `choices`: the PI's threshold selection and the two offered-but-unselected alternatives.
- `thresholds`: discovery and holdout counts, percentage-point difference, 95% interval, and stored status for each threshold.
- `lineage`: actual experiment, Result, registered Spec SHA, payload SHA, and frozen protocol identifiers.
- `sources`: source paths and SHA-256 values copied from the approved evidence manifest.
- `boundaries`: concise interpretation limits shown with the evidence drawer.

This page is a replay of recorded evidence, not a live Omnigent console or new scientific execution.
