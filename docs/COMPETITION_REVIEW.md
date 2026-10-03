# NOVA-MAT competition readiness review

Reviewed 2026-10-03 against repository main `5163e96`, including the teammate's final-protocol evidence requirements. This is a coordination plan, not evidence that outstanding runs have succeeded.

Subsequent stage update against main `51d45d9`: B published complete fixed-role SDK protocol evidence for `luna-pilot-07`, including the previously missing final review and freeze. A's separate frozen holdout interface now passes synthetic verification (196 full Linux tests), but actual holdout execution and full YAML orchestration remain outstanding. See [current team status](TEAM_STATUS.md) and [holdout handoff](HOLDOUT_VALIDATION.md). The review tables below preserve the earlier snapshot and should be read with this update.

## Requirements and source boundaries

The participant supplied a screenshot of the official Team & Submission page for [the event](https://app.hack-nation.ai/?eventId=4ee144f2-dd47-4613-9290-cf3e47509011). It confirms:

- Deadline: **2026-10-04 08:00 America/Chicago (GMT-5)**. Uploads and edits remain open until 08:15, but the team should finish before 08:00.
- **Both** the platform submission and its linked Google Form are required.
- Each submission section accepts one MP4 or MOV video, at most **60 seconds and 1 GB**. The screenshot does not show all section names or the Google Form destination; confirm these on the actual form before preparing final assets.
- Teams contain 1–4 members; one member submits the shared project. Our team has two members.

The supplied `NOVA-MAT_Technical_Plan.md` is the agreed internal plan. It attributes scoring to an Agentic Scientific Discovery brief: orchestration 30%, breakthrough 25%, acceleration/learning 20%, rigor 15%, creativity/responsibility 10%. **These weights and the original challenge wording have not been independently verified.** The event's publicly retrieved HTML was a workspace-opening shell, not the challenge text. The screenshot confirms submission rules, not the scientific rubric.

Internal acceptance criteria include four scientific roles, competing proposals, evidence-dependent selection, two dependent discovery experiments, protocol freeze followed by one controlled holdout validation, three complete engineering rehearsals, and a paired human timing baseline. These are our agreed targets, not independently confirmed official mandates. The plan's two-minute demonstration outline must be adapted to the actual 60-second submission sections.

## Verified state

| Area | Evidence and boundary |
| --- | --- |
| Shared data | Prepared JARVIS snapshot and frozen split exist locally and in the private [prepared-data release](https://github.com/number8868/agentic-scientific-discovery/releases/tag/data-prepared-20261003-v1). Release checksums support an identical teammate setup. Raw/prepared data remain outside Git history. |
| Real science | Registered discovery `family_screen` and `threshold_sensitivity` execute real computations with portable evidence. Holdout outcomes remain closed. |
| Scientific finding | Discovery has 3/7,657 oxide passes and 6/3,158 chalcogenide passes: difference 0.15081 percentage points. Only nine primary passes exist. Threshold results share the same snapshot and are not independent replications. No general materials-performance or synthesis claim follows. |
| Model connectivity | [PR #6](https://github.com/number8868/agentic-scientific-discovery/pull/6) is merged. `luna-pilot-06` records nine actual model turns, six successful tool calls, two computed Results, a linked model review, and eleven live events. Three zero-call repair turns and earlier failures are preserved. It remains partial: the export has no second review, final protocol freeze, or holdout Spec. |
| Orchestration boundary | The verified SDK pilot uses a host-fixed role order and family-to-threshold path. It proves connectivity and dependent provenance, but does not prove autonomous CLI/YAML root-to-child orchestration or comparison of alternative experiments. |
| Runtime checks | The recorded final pilot integration baseline passed 154 tests against main `f366048`. Do not automatically attribute that result to later launcher/config changes. Pipe draining and bounded worker execution are covered; end-to-end model-run deadline enforcement still needs confirmation. |
| Teammate progress | Main now includes isolated model selection/session controls, an increased YAML per-session tool limit of 48, and stricter final-protocol evidence checks. The fixed-role host now includes final review and protocol freeze (eight successful calls, at most sixteen model turns); the preserved pilot predates those additions. These changes are not evidence that a new full run succeeded. The recorded SDK pilot uses `gpt-6-luna`; the current live YAML selects `gpt-5.6-luna`. |

See [pilot evidence](OMNIGENT_LIVE_PILOT.md), [portable run](results/omnigent_luna_run), and [verification](results/omnigent_luna_verification.json). The repository does not yet contain verified evidence for a complete CLI/YAML run through frozen holdout validation, three full rehearsals, or a paired timing baseline. Teammates may have unpublished local work; check their latest commits and evidence before duplicating it.

## Next work, in order

| Priority | Work | Suggested owner | Acceptance evidence |
| --- | --- | --- | --- |
| 1 | Run the real CLI/YAML supervisor and child agents against the shared prepared data. Compare legal proposals and make the next experiment depend on the actual Result and critique. | B leads orchestration; A supports science integration. | Root/child/tool trace, registered proposals and selected spec, linked critique, real numerical artifacts, failures and timing. A fixed template sequence alone is insufficient. |
| 1, parallel | Add the controlled holdout execution boundary for the chosen protocol. Preserve the frozen data pipeline and dependency hashes. | A leads; agree the registered contract with B. | Only a registered frozen final protocol may open holdout; validate its dataset/split/spec references and reject premature or changed requests. Test gates without reading real holdout outcomes. |
| 2 | Freeze the final protocol after discovery decisions, then execute the single authorized holdout validation and interpret all quality flags. | A science, B registry/freeze path. | Immutable freeze record, frozen spec, controlled validation Result, auditable lineage, bounded conclusion. Do not select thresholds using holdout outcomes. |
| 3 | Complete three full engineering rehearsals, including one legal budget variation; collect the paired manual baseline. | Both. | Complete traces and cancellation/failure behavior. Aim for six paired contexts; with fewer than three valid pairs, show raw timing only and make no acceleration-ratio claim. Rehearsals are reliability evidence, not independent scientific samples. |
| 4 | Package evidence, limitations, reproducibility instructions and the actual submission-section videos. Complete both submission channels. | Both; choose one submitting member. | Each video within 60 seconds; repo/access and assets verified; platform and Google Form confirmations retained. |

If alternative experiments require method-sensitivity support, first audit paired discovery metadata and sample feasibility without reading holdout outcomes. Implement only the branch needed for the evidence-driven decision; record data limitations instead of expanding the project indiscriminately.

## Schedule and scope

The screenshot was supplied around 17:29 Chicago on October 3, leaving roughly 14.5 hours at that time. Start with CLI/YAML integration and the holdout gate in parallel, then complete validation, rehearsals and baseline collection. **Freeze feature development by 04:00 Chicago on October 4**, reserving the final four hours for evidence review, recording, upload and corrections. Target completion of both submissions by 06:00, leaving a two-hour buffer before the deadline. Adjust intermediate work to actual run failures; do not spend the submission buffer adding features.

Use Omnigent's existing interface and scientific plots for demonstration. Defer a new React frontend, GPU/DFT work, model training, material generation and broad infrastructure expansion. The defensible contribution is an auditable, bounded scientific decision and validation loop, not the number of agents or a claim to have discovered a new material.

Before another expensive live run, reconcile the internal planned limits (120 seconds per experiment, 360 seconds aggregate compute, 12 minutes for the model workflow) with actual enforcement. The current 48-call YAML limit is **per session**, not a proven global dispatch or wall-clock budget. Confirm the persisted shared deadline, worker cancellation and model-request accounting; increasing a call limit does not fix missing cancellation.

After each verified milestone, publish its evidence and limitations to GitHub and review the latest teammate commits. Keep credentials, `.nova/live_context.json`, live SQLite files and private session state out of commits. Model usage counters in the recorded pilot are inconsistent; do not infer billed token cost or invent efficiency gains.

## Coding assistants versus experiment agents

The two coding helpers used for the completed integration stage were `omnigent_windows` and `process_boundary_fix`, both explicitly configured as **`gpt-6-luna` with `xhigh` reasoning**. Both finished; no new coding helper was launched for this review. This configuration selects the faster/lower-cost Luna model family; it does not prove that a separate UI Fast-mode switch was enabled.

These helpers are distinct from the experiment's Omnigent scientific-role calls and their YAML model configuration. [Official subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents) describes subagent activity/threads in the Codex app, but the reason a particular client view does not display them cannot be determined from repository evidence. Future delegation updates should name the task, model, reasoning effort and completion evidence explicitly.
