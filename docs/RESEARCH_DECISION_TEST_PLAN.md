# Research decision pilot v1

This prospective pilot tests B's evidence-to-decision responsibility. It uses eight new synthetic research evidence packets, not the earlier arithmetic corpus. The intended endpoint is a correct next-experiment choice and calibrated conclusion from the evidence available at decision time.

## Comparison and scope

The primary paired comparison is a persistent single agent (draft, critique, final) versus independent parallel Planner and Skeptic followed by PI. Both request gpt-6-luna with medium reasoning, receive the same public evidence and answer contract, and have three SDK turns with no retry. Existing isolated Omnigent workers, durable dispatch reservations and process cleanup are reused. A deterministic threshold-first policy provides a transparent additional reference for action correctness only. It checks visible blocking issues, completed templates and budget; it does not assess conclusions or prose. That policy is a limited baseline, not the strongest possible evidence-aware rule system.

Eight packets include easy decisions as well as method/cohort ambiguity, missing evidence, conflicting provenance, infeasible budgets, redundant diagnostics and justified stopping. Acceptable actions and conclusions are frozen before the live run, derived solely from available evidence. Multiple defensible choices should be accepted. A correct stop is rewarded only when consistent with the stated objective and evidence constraints.

This is a decision-on-evidence proxy. Models do not execute experiments or use scientific tools. It cannot establish full workflow performance, autonomous scientific discovery, clinical/materials validity, or reduced human intervention. A later native comparison needs identical registered tools and permissions for a competent single agent and multi-agent system, plus A's scientific review.

## Outcomes frozen before execution

- Primary descriptive quality: proportion of all scheduled cases with valid delivery and all objective decision answers correct. Failed or missing deliveries count as zero. Report individual action, conclusion and claim-permission errors as well.
- Secondary descriptive latency: per-case time to a validated persisted delivery, paired wins/losses and median relative saving. Include failed delivery count separately; never use only successful cases to imply a reliability benefit.
- Review behavior: inspect whether final decisions correct errors in drafts/plans and whether review introduces errors. This is descriptive audit, not a blinded prose-quality score.
- Three turns are a dispatch budget, not equal measured token usage or cost. Report provider usage and billing as unknown when unattested.

There is one repetition per case and a maximum of 48 SDK turns. The cases form a small purposive pilot, not a representative population or an independent confirmation set. No confidence interval, significance claim, or architecture-wide superiority claim follows from this run. All ties and negative outcomes remain published. Cases, prompts, grading and endpoints must not be changed after seeing outputs.

## Run readiness

Before model calls: independent review of available-evidence gold answers and runner budget/cleanup; targeted offline tests; a durable manifest hashing source, cases, grader, worker, runtime and requested settings. Each arm gets its own full 150-second deadline; arms run sequentially while independent specialists may overlap. Failures retain raw output and dispatch records. Unverified cleanup stops further dispatch.

If results show no advantage, retain the single-agent or fixed-policy option for the tested workload. Future changes to review triggers or scientific workflows require a new prospective evaluation, rather than relabeling this result.

## Pre-run review record

An independent Luna reviewer and the primary agent checked the case rubric and reused runner before model calls. They identified and resolved a nonexistent grader argument, leaked conclusion labels in the public packet, an ambiguous choice between two new tests, and missing or inconsistent directional quality criteria. The final cases expose evidence and criteria, keep answer keys out of the model packet, specify completed method work in the easy case, and give explicit missingness bounds. The reviewer confirmed the targeted corpus blockers were resolved. This is an implementation and rubric review; it does not constitute blinded review of live model prose.
