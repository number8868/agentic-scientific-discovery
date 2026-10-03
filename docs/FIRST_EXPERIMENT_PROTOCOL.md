# First experiment: frozen scientific intent

Recorded before any family-screen outcomes are computed, 2026-10-03.

Question: under the fixed computational screen in this JARVIS snapshot, is the observed composition pass rate greater for sulfide/selenide representatives than oxide representatives?

- H1: delta > 0. Competing statement: delta <= 0.
- Delta: observed chalcogenide pass rate minus observed oxide pass rate.
- OPT bandgap only; 1.1 <= gap <= 1.8 eV; ehull <= 0.05 eV/atom.
- Choose lowest valid ehull structure within each canonical reduced composition, jid lexical tie-break. No selection using gap. Keep missing representatives unknown.
- Exclude Pb, Cd, Hg, As, Tl and compositions with fewer than two elements.
- Oxide contains O and none of S, Se, N, F, Cl, Br, I. Chalcogenide contains S or Se and none of O, N, F, Cl, Br, I.
- Seed 1729; within-family composition split 70% discovery / 30% holdout. All structures of a composition stay together.
- Only discovery outcomes in this milestone. No holdout outcome analysis.
- Independent composition-level bootstrap within family, 2000 replicates, 95% percentile interval, seed 1729.
- Quality: discovery >=40 evaluable compositions in each family and coverage >=80%. Constant binary outcomes in either family force inconclusive when quality otherwise passes.
- Quality failure is data_limited. A strictly positive interval supports the direction in this snapshot; strictly negative reverses it; interval including zero is inconclusive.
- Report worst-case missingness difference interval. If it includes zero, complete-case conclusions do not establish ordering for all compositions.
- Execution success and scientific status are separate. Download/tool failure is not scientific evidence.

This is a preregistered engineering/science smoke test, not a claim of autonomous hypothesis generation. Team B will supply real Omnigent role orchestration and registry-bound execution. No material performance, synthesizability, toxicity safety, or holdout replication claim is made.

Source definitions: JARVIS official download guide https://jarvis-materials-design.github.io/dbdocs/thedownloads/. JARVIS thermodynamics implementation https://jarvis-tools.readthedocs.io/en/develop/_modules/jarvis/analysis/thermodynamics/energetics.html. NIST-hosted scientific paper labels energy above hull per atom in eV/atom: https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=936649. Thresholds and quality gates are from the agreed project plan.
