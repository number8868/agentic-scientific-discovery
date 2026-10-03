# Paired-method screening audit

This exploratory extension answers a concrete question: which screening candidates still pass when OPT and MBJ are compared on the same frozen JARVIS representative, and which decisions depend on method availability or choice?

The [protocol](METHOD_AUDIT_PROTOCOL.json) is registered before new method outcomes are calculated. It keeps the original discovery split, 1.1–1.8 eV gap window and 0.05 eV/atom hull threshold. The three arms are OPT on all evaluable discovery representatives, OPT on the paired subset, and MBJ on exactly that same subset. The first difference exposes subset selection; the second isolates a method difference conditional on those paired records. Missing MBJ stays unknown. Holdout outcomes remain closed.

The researcher-facing output is a candidate evidence list with JID, composition, both gaps, stability value, eligibility under each method, uncertainty reason and a next validation action. Candidates passing both methods remain computational screening candidates. The full eligible-row audit is retained locally; the published shortlist and aggregate results do not replace the frozen prepared dataset.

This iteration is a standalone scientific executor and report. Shared live registries, B's Planner/PI choice mechanisms and YAML prompts need a separate integration before this can be advertised as an agent-selectable live alternative. PR #9's holdout code is independent; this exploratory protocol does not change its frozen primary/follow-up choices.

## Prior work and claim boundary

OPT/MBJ comparisons and JARVIS data are established research: the original data paper compares the methods and provides both band-gap fields for method analysis ([Scientific Data, 2018](https://www.nature.com/articles/sdata201882); [NIST publication record](https://www.nist.gov/publications/computational-screening-high-performance-optoelectronic-materials-using-optb88vdw-and)). This audit uses those existing calculations; it does not perform new DFT or treat MBJ as experimental truth.

Autonomous sequential experiment selection also predates this project ([CAMD, 2020](https://pubs.rsc.org/en/content/articlelanding/2020/sc/d0sc01101k)), as does broader LLM-based workflow planning for materials research ([MAPPS](https://arxiv.org/abs/2506.05616)). Our intended usefulness is a reproducible candidate decision audit with explicit method and missing-data limits. We make no first-of-kind novelty claim. This is a targeted prior-work check, not an exhaustive novelty review.
