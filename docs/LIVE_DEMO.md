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

The partial model-driven selection is `luna-pilot-06` under [the portable evidence package](results/omnigent_luna_run). Its audit records nine model turns, six successful registered-function calls and three clean no-tool repairs. The actual stored Skeptic review correctly cites 3/7,657 and 6/3,158 passes and the interval width; the follow-up spec links that first Result/review. The export has no second review or final protocol freeze, so it is not complete live-protocol evidence. See [the pilot runbook](OMNIGENT_LIVE_PILOT.md) and [independent verification](results/omnigent_luna_verification.json).

For this presentation, describe the bounded Omnigent SDK host with fixed protocols and role order. The YAML multi-agent server and Databricks competition runtime have separate verification gates. Windows installation alone is not model-run evidence; this recorded pilot ran on Ubuntu WSL.
