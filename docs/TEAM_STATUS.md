# Team status and handoff

## Team A milestone 7 — frozen holdout interface verified with synthetic data, 2026-10-03

Synced main `51d45d9`, including B's `luna-pilot-07` complete fixed-role SDK protocol export. Its portable structural checker passes: two discovery Results, two native reviews, final freeze and an unexecuted holdout Spec. This does not establish YAML root-to-child orchestration. Preserve the original final review, but do not repeat its incorrect “missingness gap” wording for the screening pass-rate endpoint.

Added `nova.holdout_bridge.execute_live_registered_holdout(experiment_id)` as a separate ID-only host tool. It validates frozen hashes/parameters, native run-owned discovery/review lineage, both content-addressed discovery artifacts and exact registered Results before claiming a single attempt. Duplicate requests cannot create another worker; a successful cached Result is revalidated, while failure/interruption stays closed. The worker is bounded to at most 120 seconds, capped by the remaining 360-second science allowance, and the gate requires exactly two prior native discovery starts with no failed discovery attempt. Whole-model deadline enforcement remains a separate host responsibility; synchronous worker startup/cleanup remain outside the measured controller deadline.

The scientific executor computes the primary holdout endpoint and every frozen threshold point, labels each comparison separately, preserves sample/coverage/degeneracy protections and snapshot-only scope, and includes its implementation hash in the immutable payload. Existing discovery tools remain discovery-only. See [Team B integration and launcher](HOLDOUT_VALIDATION.md) and [verification record](results/holdout_readiness.json).

The final complete suite passes **196 Linux tests** against the latest team base, including 13 synthetic science cases and 18 gate cases. A synthetic CLI-to-gate-to-actual-executor-to-export test passes. The isolated Linux test checkout contains no real prepared data or private live context. Real frozen metadata and byte-hash preflight also pass separately. The frozen data pipeline and science dependency files were preserved. No real holdout result, new model run, full YAML rehearsal or efficiency gain is claimed in this milestone.

Next: B wires the dedicated post-freeze Runner into formal orchestration and verifies its shared deadline. Execute the frozen real holdout once through this gate, then publish verified comparison evidence, complete rehearsals/baseline and prepare both submissions. The current YAML's explicit post-freeze stop must change together with the dedicated tool; adding a callable alone does not complete that workflow.

---

## Competition readiness review — 2026-10-03

PR #6 is merged at main `11baca8`. The official participant screenshot confirms an October 4 **08:00 America/Chicago** deadline, mandatory platform **and Google Form** submissions, and **60-second MP4/MOV videos per section**. The original challenge wording/scoring remains to be independently verified; distinguish it from the agreed internal technical plan.

See [competition review and next-stage plan](COMPETITION_REVIEW.md). The next priorities are genuine CLI/YAML root-to-child orchestration with evidence-dependent experiment selection, A's controlled frozen-protocol holdout boundary, then validation, three full engineering rehearsals and a paired manual baseline. The fixed-role SDK pilot is completed connectivity evidence, not the full competition loop. Review B's latest session controls and 48-call per-session policy against the shared wall-clock budget before another live run. Holdout outcomes remain closed.

Freeze features by October 4 04:00 Chicago and target both submissions by 06:00, leaving the final two hours for corrections. Use the existing interface and scientific evidence; defer frontend/platform expansion. This update changes documentation only and does not claim new live runs or tests against the latest launcher changes.

---

## Team A milestone 6 — real Luna two-result pilot (partial), 2026-10-03

The completed `luna-pilot-07` portable evidence is in [omnigent_complete_run](results/omnigent_complete_run), with its concise [verification record](results/omnigent_complete_verification.md). Both SQLite and portable gates pass: 13 events, two Results, two reviews, a frozen final protocol, and an unexecuted holdout. The requested model is `gpt-5.6-luna`; model identity is not provider-attested. The final Skeptic's “missingness gap” wording is preserved for provenance but is scientifically incorrect for the pass-rate endpoint and must not be quoted.

Synced main `5d04bbf`, including B's final-protocol, process control and result-ownership changes. Real run `luna-pilot-06` completed the six-role `gpt-6-luna` workflow through the pinned Omnigent 0.16.0 internal SDK: nine model turns, six actual successful function calls, two real discovery Results, one model-authored review and eleven live events. Three clean no-tool responses were repaired once each. The review cites the actual first Result, correctly identifies sparse pass counts and interval width, and leads to its registered threshold follow-up. This export is partial: it has no second review, final protocol freeze, or holdout Spec. See [the pilot](OMNIGENT_LIVE_PILOT.md), [portable evidence](results/omnigent_luna_run), and [independent verification](results/omnigent_luna_verification.json).

The separately shipped Codex code-mode host was installed and its executable path passed explicitly through the SDK's environment filter. The current eight-role host permits at most sixteen model turns and eight actual function calls; tool failures and partial execution fail closed. Five earlier incomplete attempts remain preserved separately. This establishes the bounded SDK pilot with fixed protocols and role order; the YAML multi-agent server, Databricks runtime and complete OS sandbox remain separate verification scopes.

Fixed pipe backpressure in B's process controller by draining the result concurrently under a bounded deadline. The 8 MiB round-trip and worker timeout/reap checks passed; the complete Linux suite passed **145 tests**, including twelve controlled-host checks. The frozen prepared-data readiness check still passes. The data release is available and PR #5 was merged. Holdout outcomes remain closed.

After recording the model run, synced B's newest main `f366048`, which bounds the YAML SDK launcher and prevents stale session/model reuse. Its launcher expects `.venv-omnigent`; the Linux checkout now links that path to the installed real Linux environment. The merged full suite passes **154 tests**. This compatibility check does not claim a new live YAML run.

---

## Team A milestone 5 — exact data transfer and Linux readiness, 2026-10-03

Synced B's real orchestration implementation at main `b24b080`. The prepared-data environment prerequisite is satisfied locally: all original/raw, protocol, audit, pipeline and dependency-file digests match the frozen reference. Added a standard-library, metadata-only readiness check with missing-file, tamper, path and symlink rejection tests. Linux passes all seven readiness tests; Windows passes six and skips the privileged symlink case.

At the user's explicit request, uploaded the exact prepared dataset as a [private GitHub release asset](https://github.com/number8868/agentic-scientific-discovery/releases/tag/data-prepared-20261003-v1), with SHA256 sidecar, attribution and extraction instructions. The archive is about 128 MiB; its remote digest matches the locally verified `25fc3e46efff1b6a6e1f60f8453f40b92a3a81f23a630cb80fde0ecebdf48773`. Data and runtime-private files remain outside Git commits. See [Team B handoff steps](A_DATA_HANDOFF.md).

Omnigent 0.16.0 plus scientific dependencies are also installed in the existing Ubuntu WSL environment (Python 3.12.13). The official Linux Codex CLI 0.160.0 archive was checked against GitHub's release SHA256. All 108 pre-handoff A/B tests pass on Linux. Original Windows-only POSIX failures were not bypassed. A real `gpt-6-luna` controlled ping function call passed through Omnigent's Codex SDK. A separately bounded six-role real-data pilot is still being verified; its initial attempt reached first result, actual model review and second approval, but the last model turn made no tool call, so it is not a complete two-round success.

The basic real-data [two-minute demonstration](LIVE_DEMO.md) preserves snapshot and sparse-endpoint limits. Its model-driven presentation gate requires the final verified audit, not a model's textual claim.

---

## Team A milestone 4 — Windows installation and B adapter verified, 2026-10-03

Synced main `b05f395`: B has verified Linux Omnigent/Codex fixture orchestration and added `nova.science_adapter`. Installed Omnigent 0.16.0 in an isolated local Python 3.12.15 environment. Version/help pass directly. With `--science-adapter --two-rounds`, both real discovery templates completed in this new environment; all numerical results and portable evidence hashes/lineage matched the earlier evidence. See [Windows setup](OMNIGENT_WINDOWS.md), [adapter evidence](results/windows_adapter_run), and [verification](results/windows_adapter_verification.json).

The focused adapter/executor/integration selection passed 23 tests on Python 3.12. The new full suite on Windows is 94 passed / 4 failed, due to B's POSIX fixture permission and privileged symlink checks; these were reported on PR #3. The fixture bridge still fails closed. Neither this installation nor these human-scripted runs prove real model-driven scientific orchestration. A separate Windows-compatible controlled SDK pilot is the next stage. Holdout remains closed; B-owned files were preserved.

---

## Team A milestone 3 — two real rounds verified, 2026-10-03

Synced B's merge of milestone 2 at `615de5f`. Recorded discovery-only run `live-64ccc87d7e06` executes `family_screen`, records a review citing its actual Result, links the threshold draft to that Result/review, and executes `threshold_sensitivity` through B's registered-ID workflow. Both shared Results, 11 live events, one review, canonical specs and two rich scientific payloads are preserved in [the portable evidence package](results/two_round_live_science). This remains human-scripted control flow; no live Omnigent call is claimed.

| Inclusive ehull maximum (eV/atom) | Oxide passes / 7,657 | Chalcogenide passes / 3,158 | Difference (percentage points) | 95% resampling interval (percentage points) |
|---|---:|---:|---:|---|
| 0.025 | 2 | 5 | 0.13221 | [0.00555, 0.29054] |
| **0.050 (primary)** | **3** | **6** | **0.15081** | **[0.01109, 0.32220]** |
| 0.100 | 3 | 8 | 0.21415 | [0.04830, 0.39859] |

All points classify as `supported_in_snapshot` under the frozen rules, and the primary point exactly reproduces milestone 1. The observed direction survives this fixed threshold grid. Only 7–11 compositions pass at each point; these correlated analyses are not independent confirmation, and no material performance or broader population claim follows. Coverage is 100% in both discovery groups at every point. Holdout outcomes remain unexamined.

All 90 combined tests passed. Independent verification checked exported file/payload hashes, registered contract hashes, review/parent links, event order, and actual discovery counts from the frozen representative CSV. Measured computation times in this environment were 0.569 s for family_screen and 0.777 s for threshold_sensitivity; these are not a cold-start or deployment benchmark. Evidence bytes are preserved across Git checkouts. See [the chart](results/threshold_sensitivity.png) and [verification record](results/two_round_verification.json).

Next handoff: B can bind `nova.experiments.executor.execute` to a separately validated live Omnigent registered-ID bridge. B still owns hard worker timeout/cancellation and run authorization. A can support method sensitivity after its follow-up protocol is agreed and frozen; holdout stays closed until the final validation protocol is frozen. No B-owned implementation files changed in this milestone.

---

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
