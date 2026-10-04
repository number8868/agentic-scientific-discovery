# Paired-method screening audit

This exploratory extension answers a concrete question: which screening candidates still pass when OPT and MBJ are compared on the same frozen JARVIS representative, and which decisions depend on method availability or choice?

The [protocol](METHOD_AUDIT_PROTOCOL.json) is registered before new method outcomes are calculated. It keeps the original discovery split, 1.1–1.8 eV gap window and 0.05 eV/atom hull threshold. The three arms are OPT on all evaluable discovery representatives, OPT on the paired subset, and MBJ on exactly that same subset. The first difference exposes subset selection; the second isolates a method difference conditional on those paired records. Missing MBJ stays unknown. Holdout outcomes remain closed.

The researcher-facing output is a candidate evidence list with JID, composition, both gaps, stability value, eligibility under each method, uncertainty reason and a next validation action. Candidates passing both methods remain computational screening candidates. The full eligible-row audit is retained locally; the published shortlist and aggregate results do not replace the frozen prepared dataset.

This iteration is a standalone scientific executor and report. Shared live registries, B's Planner/PI choice mechanisms and YAML prompts need a separate integration before this can be advertised as an agent-selectable live alternative. PR #9's holdout code is independent; this exploratory protocol does not change its frozen primary/follow-up choices.

## Reproduce the registered audit

Use the same [prepared-data release and science environment](A_DATA_HANDOFF.md). The local manifest, original source, representative CSV, parent protocol and dependency specifications must match the frozen hashes. The executor takes no scientific parameter overrides. The new protocol's byte SHA256 is `ef09b94e6eebec20974ae4d05647f718471880e44cecb0bbaee55f2c2d050b03`, registered in commit `647816f` before the new outcomes.

```bash
python scripts/check_prepared_data.py
python scripts/run_method_audit.py --output-dir runs/paired-method-audit-01
python scripts/plot_method_audit.py runs/paired-method-audit-01/result.json --output runs/paired-method-audit-01/comparison.png
```

Run these with the science environment's Python (`.venv/Scripts/python.exe` on this Windows host, or the collaborator's `.venv-omnigent/bin/python` on Linux). Choose a fresh output directory for every run; an existing directory is refused before loading the executor.

The output contains `result.json`, the local full `audit_rows.csv`, the union-of-passes `candidates.csv`, Markdown/HTML reports, and output checksums. HTML is self-contained, with search and family/evidence-label filters. Blank CSV numeric fields and HTML `Unknown` mean missing evidence. Rates/coverage are percentages; differences and changes are percentage points. The candidate list is ordered lexically by family then JID, with no score or performance ranking.

The aggregate's timing separates protocol/input validation and scientific computation. It excludes Python import/startup, report/plot generation, any human review and all earlier data preparation. No live model runs are performed by this command. Repeated exports from the same snapshot are reproducibility checks, not independent scientific experiments.

## Prior work and claim boundary

OPT/MBJ comparisons and JARVIS data are established research: the original data paper compares the methods and provides both band-gap fields for method analysis ([Scientific Data, 2018](https://www.nature.com/articles/sdata201882); [NIST publication record](https://www.nist.gov/publications/computational-screening-high-performance-optoelectronic-materials-using-optb88vdw-and)). This audit uses those existing calculations; it does not perform new DFT or treat MBJ as experimental truth.

Autonomous sequential experiment selection also predates this project ([CAMD, 2020](https://pubs.rsc.org/en/content/articlelanding/2020/sc/d0sc01101k)), as does broader LLM-based workflow planning for materials research ([MAPPS](https://arxiv.org/abs/2506.05616)). Our intended usefulness is a reproducible candidate decision audit with explicit method and missing-data limits. We make no first-of-kind novelty claim. This is a targeted prior-work check, not an exhaustive novelty review.
