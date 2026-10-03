# Real science executor integration

This milestone connects A's deterministic real-data experiment to B's registered experiment workflow and run-scoped evidence export. Its control flow is a human-scripted integration check. It is not proof of Omnigent model/tool connectivity or autonomous experiment selection.

## Trust and scientific boundaries

- A's `execute(spec)` maps a complete registered scientific specification into the narrow deterministic computation and returns the shared `nova.contracts.Result` shape.
- The registered specification SHA is distinct from the effective computation SHA. Preserve both in the evidence; do not overwrite one with the other.
- A writes the complete computation payload as a separate host-named artifact, including structured quality flags and every threshold point, rather than losing fields during the shared Result mapping.
- B's workflow owns registration, run/event provenance, selection and review. B's existing Omnigent H2 bridge is fixture-only; it must not be used as a live bridge by changing an environment flag.
- The original snapshot, representative table and split stay unchanged. Holdout outcomes remain unavailable to the science executor.
- `completed` means the numerical execution returned successfully. Scientific states describe the evidence and may be `data_limited` or `inconclusive` after a successful execution.
- Caller-selected filesystem paths, arbitrary code and unknown scientific parameter fields are not accepted by the science executor.

## Budgets and failure limits

The current B workflow accounts for declared estimated experiment costs. A's direct scientific executor does not implement a worker-process timeout, persistent lease recovery or hard run cancellation. These controls must be verified in B's trusted runtime before a full live competition run. A's integration check does not establish those guarantees.

Malformed specifications or input/hash failures raise exceptions. The host must preserve execution failures separately from scientific status and never replace failed real experiments with fixture numbers.

## Follow-up protocol

The threshold sensitivity extension is recorded in `docs/THRESHOLD_PROTOCOL.json`, SHA256 `9dd5cda359722312ebe4cc9087b566eb0849ccd7175ada7587eb5efa7c6624c3`. It is frozen after the first discovery result and before evaluating its grid. The grid was already defined in the agreed technical plan, but this record does not claim it was executed or selected autonomously earlier.

All three energy-above-hull thresholds (0.025, 0.05, 0.10 eV/atom) must be reported. OPT window remains 1.1–1.8 eV; 0.05 remains the main endpoint. Grid points are correlated sensitivity analyses, not three independent replications. No best grid point replaces the main result.

## Verified first registered run

With the same prepared frozen dataset and project environment:

```powershell
.\.venv\Scripts\python.exe scripts/run_live_science.py
.\.venv\Scripts\python.exe -m pytest --basetemp=.verification-repro/pytest-integration-check
```

The default launcher runs one real family-screen computation through `PersistentWorkflow`, SQLite storage and B's registered-ID tool entry. It creates the parent of its default database and chooses unique run/experiment IDs. It registers two initial proposals but selects family_screen explicitly as a human-scripted integration choice.

The portable evidence directory contains B's `events.jsonl`, `specs.json`, `results.json`, `reviews.json`, and checksum manifest, plus `science-artifacts.json` and all referenced rich numerical payloads in `science-artifacts/`. The executor's content-addressed artifacts exclude elapsed time and timestamps for stable scientific contents; shared Result still records real execution times. Cumulative artifact manifests keep multiple results distinct and preserve every grid point.

Recorded run `live-aa50364f44b0` is in `docs/results/registered_family_run`. Independent validation matched registered spec SHA, checked every exported file/payload digest, and matched the original family-screen numerical summaries. All 89 combined tests passed. A fresh working-directory data reproduction was already checked in milestone 1; a fresh dependency installation has not been separately verified.

The CLI's optional database path belongs to the trusted host, not an agent tool. The executor itself accepts only a full scientific specification and host mode metadata. B owns run authorization and may bind it behind the narrow registered-ID callable. Existing `nova.omnigent_bridge` is fixture-only and remains unchanged.

## Verified two-round run

```powershell
.\.venv\Scripts\python.exe scripts/run_live_science.py --two-rounds
```

After the first actual Result, the launcher writes a review containing its ID, scientific state, counts, delta and interval. The review recommends the previously frozen threshold grid. The host adds `parent_result_id` and `review_id` to the existing threshold draft before `run_second` registers its immutable canonical spec. In the current B schema a review is keyed by its first Result ID, so both linkage fields use that ID. This is an explicit host integration choice, not a model-generated critique or independent scientific selection.

Run `live-64ccc87d7e06` contains two completed real Results, one review and 11 live events. Its portable evidence is in `docs/results/two_round_live_science`; `docs/results/two_round_verification.json` records independent hash, linkage, event-order and discovery-count checks. All 90 combined tests passed. The 0.05 primary point matches the original scientific result exactly; all three points have positive differences and positive lower interval limits under the frozen rules. The small number of positives and correlated grid limit interpretation. See `docs/TEAM_STATUS.md` for every point, including counts and intervals.

Generate the chart from the exported threshold payload, rather than recomputing or editing numbers:

```powershell
.\.venv\Scripts\python.exe scripts/plot_threshold_result.py <exported-threshold-science-payload.json> --output docs/results/threshold_sensitivity.png
```

The chart uses observed pass rates in percent and differences in percentage points. It retains the primary point and the intervals stored in the immutable science payload. Both payloads have separate content-addressed files and the cumulative artifact manifest retains both Results. Git attributes preserve all portable evidence bytes so checkout line-ending conversion cannot invalidate the checksums.
