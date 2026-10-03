# Team status and handoff

## Team A milestone 2 — registered real executor completed, 2026-10-03

Synced main `e8b40a4`, including B's H2 fixture bridge. Added `nova.experiments.executor.execute(spec) -> nova.contracts.Result` and a human-scripted launcher `scripts/run_live_science.py`. B-owned runtime, storage, contracts, workflow, evidence exporter and Omnigent bridge were preserved.

Real family-screen execution now passes through B's registered-ID tool entry, persists the canonical registered spec and Result, and exports events plus a portable, checksummed science payload. Recorded run: `live-aa50364f44b0`, under `docs/results/registered_family_run`; all scientific summaries match milestone 1 exactly. The executor maps raw `success` to shared `completed`, preserves group names/intervals, and retains structured quality flags and the effective computation SHA in its immutable payload. The shared Result's spec SHA is the actual registered contract SHA.

All 89 combined tests passed, including the new threshold template's 15 focused tests. Threshold source is implemented and strictly tied to the independently frozen extension protocol; actual three-point execution and two-round human-scripted integration are the next verification step. No holdout outcomes or Omnigent model/tool call are claimed here. Budget enforcement remains a host responsibility; current B estimated-cost accounting is not hard wall-clock cancellation.

See `docs/SCIENCE_INTEGRATION.md` for the current integration boundary and reproduction commands. The older raw dictionary adapter remains usable as a low-level computation function; B should now bind the shared-contract `execute` adapter rather than implement the mapping again.

---

## Team A milestone 1 — completed, 2026-10-03

One real JARVIS discovery-only `family_screen` now runs end to end. The work is on `science-engine`, based on B's `eb936f8` bootstrap commit. B's agents, shared contracts, storage, runtime, tools, fixture engine, and existing tests are preserved.

### Verified outcome

| Family | Discovery compositions | Evaluable | Pass | Observed pass rate |
|---|---:|---:|---:|---:|
| oxide | 7,657 | 7,657 | 3 | 0.03918% |
| chalcogenide | 3,158 | 3,158 | 6 | 0.18999% |

Delta (chalcogenide minus oxide) = 0.15081 percentage points. The 95% percentile bootstrap interval is [0.01109, 0.32220] percentage points. Frozen classification: `supported_in_snapshot`. Both field coverage rates are 100%, so the missingness interval collapses to the observed difference.

Only nine compositions pass. The sparse endpoint and the snapshot/representative selection limit the interpretation. Holdout outcomes, method sensitivity, threshold sensitivity, and real Omnigent orchestration remain untested in this milestone. This is not a material-performance or general scientific-discovery claim.

### Delivered to B

- `nova.data.pipeline.read_metadata()` returns family/split sample sizes and coverage only; holdout values/outcomes are not exposed.
- `nova.experiments.family_screen.run_experiment(spec)` computes the real frozen discovery result. Use `docs/examples/family_screen_spec.json` as the input example and `docs/results/first_family_screen.json` as the real output example.
- `python scripts/nova.py prepare` prepares one immutable local snapshot; `python scripts/nova.py screen` emits a new result file per execution.
- Original snapshot, protocol, source hashes, split/representative hashes, and count audits are recorded in `docs/results/first_manifest.json`. Local raw files and active frozen inputs are ignored by Git.
- Install `requirements-science-lock.txt` in an isolated environment. Verified Python is 3.14.5; Python 3.12 remains unverified. B's dependency-free fixture checks can run in the same environment.

### Integration gaps requiring agreement

The current B `nova.contracts.ExperimentSpec` is a dataclass. A's adapter accepts only the minimal scientific fields plus optional experiment/run/hypothesis metadata; B must select these fields from its registered spec rather than pass the entire `to_dict()` silently. `timeout_seconds`, `parent_result_id`, `review_id`, and `frozen_protocol_id` are host/registry fields and are not accepted by this minimal function. A does not enforce wall-clock worker timeout, run ownership, registry authorization, or cross-run references; B must enforce these in its trusted wrapper.

A returns `execution_status="success"`; B's fixture uses `completed`. Agree and map this execution vocabulary explicitly. A's `groups_summary` is a dictionary keyed by family; B's shared `Result` expects `GroupSummary` entries with a `group` field. A's missingness interval is a named dictionary including family bounds; B's result shape currently expects a two-value tuple. A's `quality_flags` is structured, rather than a tuple. B supplies registered `result_id`, `experiment_id`, and registered `spec_sha256`; A's scientific `spec_sha256` hashes its validated effective parameters and should be retained as a separate computation provenance hash when mapping.

The first adapter supports only the fixed OPT `family_screen` on discovery. Other templates, different thresholds, dataset mismatch, unknown fields, and holdout calls raise exceptions. If an execution fails, retain the failure and keep scientific status null; no synthetic replacement. B's fixture supports more templates but those fixture numbers must never substitute for these live computations.

### Verification

Twenty scientific tests passed; the combined A/B suite passed all 37 tests with a new workspace-local temporary directory. Three standalone executions produced identical numerical summaries, including a fresh working directory prepared from the cached original archive; frozen protocol, raw, representative, and split hashes also matched. All discovery endpoint values were independently matched to the raw snapshot by JID. This used the same installed environment; a separate clean dependency installation and actual Omnigent integration have not been verified.

Initial prepare failed on non-finite `elastic_tensor` values in the real data before producing any frozen artifacts or scientific result. The canonical derived serialization now records such values as null; original ZIP/member bytes remain unchanged. A fixture-shape error in one test was fixed by using the actual persisted CSV input shape. Both issues are resolved and covered by checks.

### Source and provenance

Tool-selected source: Figshare file 64391379, `jdft_3d-9-24-2025.json.zip`, 93,902 records, downloaded 2026-10-03 19:07:30 UTC. JARVIS-DFT attribution and CC BY 4.0 license are recorded in the manifest and science guide.

Original ZIP SHA256: `f9e0a3309f0000d5de1ec9e49c93963109ea45e63f451103f8f6595d2eabf7f5`.
Protocol SHA256: `9497988f1f8443f66326fa66a976d7196e5671ad320a1cce8a638780a8fc64ac`.
The scientific intent document was recorded before the first outcome calculation: `docs/FIRST_EXPERIMENT_PROTOCOL.md`, SHA256 `2bc819e58d7168edc496edd11cb8c5f286a7b0868424f0646094ddc800217d86`.

### Next A milestone

Agree the shared contract mapping with B, then implement real threshold sensitivity as the second available test. Preserve the original result and frozen criteria. Do not read holdout outcomes until the final protocol and follow-up choice are frozen.
