# NOVA MAT — science engine (Team A)

This guide describes Team A's data and deterministic experiment engine. The first milestone is one reproducible `family_screen` on a frozen JARVIS `dft_3d` snapshot. It is not yet an Omnigent discovery workflow.

## Scientific scope

Compare the observed screening pass rates of oxide and sulfide/selenide composition representatives. The protocol fixes OPT bandgap to 1.1–1.8 eV inclusive and energy above hull to at most 0.05 eV/atom. Composition representatives are selected using valid minimum energy above hull before inspecting bandgap; unavailable endpoints stay unknown.

Only discovery outcomes are calculated in this milestone. Holdout outcome evaluation remains unavailable. Metadata may report holdout counts and field coverage. A result can execute successfully and still be scientifically `data_limited`.

## Collaboration

- Team A owns `nova/data/`, `nova/experiments/`, and `nova/statistics.py`.
- Team B owns Omnigent configuration, shared `nova/contracts.py`, storage, runtime, and UI.
- Dictionary input/output adapters are provisional integration seams; they do not replace Team B's shared contract or experiment registry.
- Stage outcomes and validated handoff instructions are recorded in `docs/TEAM_STATUS.md`.

The agreed design is in [NOVA-MAT_Technical_Plan.md](../NOVA-MAT_Technical_Plan.md). Protocol thresholds are project choices, not claims of device performance, synthesizability, or toxicity safety.

## Data attribution

JARVIS-DFT data: NIST JARVIS / Kamal Choudhary and contributors. Source: https://doi.org/10.6084/m9.figshare.6815699. Figshare lists CC BY 4.0: https://creativecommons.org/licenses/by/4.0/. See the official download guide: https://jarvis-materials-design.github.io/dbdocs/thedownloads/.

Raw data and local environments are excluded from Git. Recorded manifests identify the exact tool-selected file, data hashes, and processing rules. See the reproduction instructions below once the first run has been validated.

## Reproduce the first experiment (PowerShell)

The verified runtime is Python 3.14.5. Python 3.12 from the design plan has not been verified. From a fresh checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-science-lock.txt
.\.venv\Scripts\python.exe scripts/nova.py prepare
.\.venv\Scripts\python.exe scripts/nova.py screen
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.verification-repro/pytest-stage1
```

`prepare` reads/downloads the tool-selected real dataset (about 48 MB compressed), freezes the protocol, and writes local manifest, original files, metadata, and audit tables. Run it once per checkout; it deliberately refuses to overwrite an existing freeze. To use a transferred cached snapshot, place the exact archive in `data/cache` before preparation. If jarvis-tools encounters a partial/corrupt download, preserve the failure and obtain the same source snapshot; do not change data sources silently. A cached archive without a download timestamp sidecar records the true download completion time as unavailable.

After preparation, `screen` can be repeated. Every execution writes a new JSON record under `runs/` and preserves previous records. Fixed seeds reproduce numerical summaries; timestamps and elapsed time vary. A new environment installation has not been independently tested; verified checks used the project environment and an independent working directory with the same cache.

## First live result

On the frozen discovery split, oxide passed **3 / 7,657** (0.0392%) and chalcogenide passed **6 / 3,158** (0.1900%). The difference is **0.1508 percentage points**, with a 95% percentile bootstrap interval of **[0.0111, 0.3222] percentage points**. Both primary field coverage rates were 100%. Under the preregistered classification rules, this is `supported_in_snapshot`.

There are only nine passing compositions. This is a sparse endpoint and the percentile interval may be sensitive; the result is restricted to the selected representatives in the frozen discovery snapshot. It is neither a claim of general material superiority nor holdout replication. No performance, optical absorption, manufacturability, synthesis, or safety validation has been done. Follow-up method/threshold sensitivity and frozen holdout validation remain pending.

Recorded artifacts are in `docs/results/`: `first_manifest.json`, `first_protocol.json`, `first_metadata.json`, and `first_family_screen.json`. They are reviewable records, not the active local `data/` inputs. This separation lets a fresh clone run `prepare` without colliding with already-frozen local files.

## Team B integration seam

```python
import json
from pathlib import Path
from nova.data.pipeline import read_metadata
from nova.experiments.family_screen import run_experiment

metadata = read_metadata()  # only counts and coverage, including holdout metadata
spec = json.loads(Path("docs/examples/family_screen_spec.json").read_text(encoding="utf-8-sig"))
result = run_experiment(spec)  # requires local prepared snapshot; discovery only
```

The example hash identifies the tested source ZIP. Check the generated manifest before using it with any other snapshot. Input fields are strict and fixed parameters cannot be changed in this first template. Unknown fields, another split, another method, or a mismatched dataset hash raise an exception. Execution failures raise exceptions and must be recorded by B's trusted host as failures, without fabricated numerical results.

This adapter does not perform authorization, shared contract validation, registry transitions, cross-run reference checks, process cancellation, or persisted execution budgets. Optional experiment/run/hypothesis IDs are untrusted integration metadata; they do not prove registry ownership. B must bind this function behind the authorized `execute_registered_experiment(experiment_id)` wrapper and map its scientific payload into the agreed contract. Do not expose private preparation loaders, generic Python execution, or raw holdout files as agent tools.

The complete combined A/B suite passed 37 tests after adopting the B bootstrap. Windows default temporary-directory access failed in this host; checks passed using a new workspace-local pytest base directory. Use a fresh directory name for subsequent validation when preserving previous test artifacts matters.

## Registered executor milestone

The mapping into B's shared Result is now implemented by `nova.experiments.executor.execute`. Use this adapter for the registered workflow; keep `run_experiment` as the low-level numerical API. See [real science integration](SCIENCE_INTEGRATION.md) for verified evidence and control boundaries. The threshold template is implemented and unit-tested; source-data grid execution is verified in a later stage record.
