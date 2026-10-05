# Equal-budget decision-audit comparison — 2026-10-05

**The comparison ran successfully; multi-role superiority was not established.**

Original CLI exit: **0**. All 84 requested Luna SDK turns and all 36 arm evaluations completed, with no retries or execution failures. Final regression: **465 passed in 23.20 seconds**. Science engines and holdout outcomes were not accessed or executed.

## Frozen protocol and provenance

- Source commit: `4557142`; [protocol](../../QUALITY_BENCHMARK.md).
- Six fixed engineering cases, two repetitions, 12 matched groups. Discovery aggregates are reused; other numerical scenarios are explicitly synthetic. These are not independent scientific samples.
- Corpus SHA-256: `bfabe6cc46487e406deffdeec5c12797c00294021aeff2b181acc4c45f7c57eb`.
- Exact [raw report](report.json) SHA-256: `9292007d80b9e442f69d0483a70178365e169f948b1aaa2806e157b541fdc90d`. Packets, order, prompts' hashes, decisions, errors, and timing are preserved. Published bytes match the original generated report.
- Requested model: `gpt-6-luna`, medium reasoning. Provider-attested identity, token usage and billed cost are unavailable, not zero. The token limit is requested, not enforced by the pinned executor.
- All arms receive the same visible evidence; answer keys stay host-side. Primary arms use three fresh-session turns, identical stage instructions and call budgets; role framing differs. This tests a serial role-framing ablation, not the entire native four-role scientific workflow or parallel agent scheduling.
- Arm order was shuffled before calls with seed 1729. No cases, prompts or scoring were changed after the live run began. No result-driven retries or extra calls were added.

## Measured results

The score includes strict answer types/labels, a legal action, and exact source references. It is **not a scientific-discovery quality metric**.

| Arm | Requested turns per evaluation | Mean strict score | Exact pass | Mean arm elapsed |
| --- | ---: | ---: | ---: | ---: |
| Single once | 1 | 90.48% | 10/12 | 5.658 s |
| Single self-review | 3 | 100.00% | 12/12 | 15.993 s |
| Planner → Skeptic → PI | 3 | 91.67% | 10/12 | 15.274 s |

Primary comparison is the equal-three-turn pair, **not** multi-role versus a one-turn baseline:

- Mean multi-role minus self-review score: **−8.33 percentage points**; six-case cluster-bootstrap 95% interval **[−20.24, 0.00] points**.
- Casewise sign test: 0 wins, 2 losses, 4 ties; two-sided **p = 0.5**. No quality advantage established; this also does not establish general inferiority.
- Mean time saved relative to self-review: **0.719 s**; 95% case-cluster interval **[−1.466, 2.904] s**, crossing zero. The predefined quality-noninferiority check also fails under the strict rubric. **No reliable efficiency improvement established.**
- Repetitions are clustered by six cases, not treated as 12 independent scientific contexts. Small convenience-corpus intervals are exploratory, not population guarantees. Latency includes SDK startup, queueing, bounded cleanup and host work inside each arm; the sum of these arms is not a measured whole-science-workflow duration.

## Independent post-run error audit

Frozen scores are retained unchanged. The following audit separates substantive errors from representation mismatches; it is not a rescored or tuned benchmark:

| Case / repetition / arm | What happened |
| --- | --- |
| Denominators / 2 / single once | Two correct rates were returned as strings. The B/A ratio was genuinely wrong: approximately 1.616 instead of 4.85. |
| Matched methods / 1 / single once | Five correct quantities were written as percent/percentage-point strings rather than numeric JSON values. |
| Matched methods / 2 / multi-role | Same five correct quantities were expressed as strings. |
| Discovery draft / 1 / multi-role | `Discovery evidence` and `Unverified` are substantively correct but fail the expected exact lowercase labels. |

Only one substantive calculation error was found in this audit, in the one-turn baseline. Neither three-turn arm had an observed substantive calculation error. Thus the lower multi-role strict score does not demonstrate worse scientific reasoning; conversely, avoiding the one-shot error does not demonstrate a benefit of specialist roles over ordinary self-review.

The prompts did not fully specify numeric JSON answer types for each question. This is a benchmark limitation, particularly for percentage strings. Do not describe the overall score gap as a scientific-accuracy improvement or regression.

## Engineering conclusion and next step

The harness is runnable and observable, but this experiment gives **no basis for a multi-agent speedup or quality-improvement claim on a resume**. An honest quantified claim is: implemented and evaluated an auditable role-based harness in 36 evaluations / 84 requested turns against one-shot and budget-matched self-review controls.

For a future confirmation, freeze a versioned per-question output contract (numeric units and enumerated labels) before calls; use new, independently reviewed cases rather than tuning this measured set. If pursuing latency, implement truly independent parallel reviews plus final adjudication and measure them against a matched serial baseline. These are proposals, not completed results. Any additional model-call budget must be agreed before that run.
