# NOVA-MAT real-data demonstration

This demonstration uses the frozen JARVIS discovery snapshot. The threshold grid is a correlated sensitivity check. Do not describe it as independent confirmation or a newly discovered material.

## Two-minute presentation

1. **0:00–0:20 — Question.** Compare the observed screening pass rates of oxide and sulfide/selenide composition representatives. Show the frozen 1.1–1.8 eV OPT gap window and the primary 0.05 eV/atom energy-above-hull limit. Explain that holdout outcomes are still closed.
2. **0:20–0:45 — First evidence.** Show a registered `family_screen` Result: 3/7,657 oxide and 6/3,158 chalcogenide compositions pass. The difference is 0.15081 percentage points, with a 95% resampling interval of [0.01109, 0.32220]. Only nine compositions pass, so the evidence is sparse.
3. **0:45–1:10 — Review.** Show the actual stored review and its first Result ID. Explain why checking the stability limit is a bounded follow-up. Distinguish a host-scripted review from a model-generated review according to the specific run's provenance.
4. **1:10–1:35 — Follow-up.** Show `docs/results/threshold_sensitivity.png`: every fixed threshold is reported, and 0.05 remains primary. The differences at 0.025 / 0.05 / 0.10 are 0.13221 / 0.15081 / 0.21415 percentage points. These points reuse the same compositions and are not independent experiments.
5. **1:35–2:00 — Audit and limits.** Show the canonical specs, Result/review links, events and both immutable science payloads. Explain the restricted registered-ID tool. State that the conclusion applies to this snapshot and selection procedure; it is not a materials-performance claim.

## Reproduce the verified host-scripted run

After preparing the frozen data and installing the scientific environment:

```powershell
.\.venv-omnigent\Scripts\python.exe scripts/run_live_science.py --science-adapter --two-rounds
```

For a presentation, use the portable checked evidence under `docs/results/windows_adapter_run`, or export the newly generated run. Fresh run IDs are printed by the launcher; do not substitute results from a different run.

## Model-driven demonstration gate

Before describing this as an Omnigent model-driven demonstration, inspect the selected run's actual model/tool audit and canonical stored review. A textual claim that a model ran the tool is insufficient. The original B terminal route is fixture-only; the Windows installation and science-adapter validation do not establish model-driven success. See `docs/OMNIGENT_WINDOWS.md` for the exact environment and current integration boundary.
