# Setup: from a fresh clone

Run all commands from the repository root unless stated otherwise. There are
three independent entry points: a synthetic fixture, a static evidence website,
and optional real scientific/model execution. Viewing the recorded evidence
does not require data downloads, model credentials or a new holdout attempt.

## 1. Prerequisites and clone

- Git and access to this private repository (including its data release assets).
- Python **3.12** for the native/scientific path. The fixture is standard-library
  Python; this guide's fresh-environment check used Python 3.12.13.
- macOS or Linux for native execution. On Windows, use WSL with the checkout,
  environment and runtime state on the **Linux filesystem**, not `/mnt/c`.
  Do not weaken POSIX permission checks to run directly on Windows.
- A browser for the evidence website. No Node/npm build is required for it.
- Only the native model path additionally needs Omnigent, an authenticated
  Codex CLI, an accessible configured model and a compatible code-mode host.

Authenticate GitHub with your normal SSH/HTTPS credential flow. Do not put a
token into the clone URL, source files or chat.

```bash
git clone https://github.com/number8868/agentic-scientific-discovery.git
cd agentic-scientific-discovery
git switch main
git pull --ff-only
python3.12 --version
```

If the repo is reported as missing, confirm your account has access first.
If `python3.12` is unavailable, install Python 3.12 through your usual package
manager before continuing; macOS's system `python3` may be an older version.

## 2. Quick Start: synthetic fixture (no model or data)

```bash
python3.12 -m venv .venv-fixture
.venv-fixture/bin/python -m pip install 'pytest==9.1.1'
.venv-fixture/bin/python scripts/run_fixture_demo.py
.venv-fixture/bin/python -m pytest tests/test_contracts.py tests/test_runtime.py tests/test_storage.py tests/test_fixture_engine.py
```

The demo should print `DEMO ONLY; numbers are not scientific evidence`, two
fixture rounds and `state=second_result_ready`. The four core test files
passed **17 tests** in a fresh macOS Python 3.12.13 environment. This checks
contracts, runtime, storage and the fixture—not native model execution or the
full scientific suite. Scripts run directly from the checkout; editable
package installation is not needed for this route.

For fixture-only Windows PowerShell, replace `.venv-fixture/bin/python` with
`.venv-fixture\Scripts\python.exe`. Native execution still needs WSL/POSIX.

## 3. Preview the actual evidence website locally

From the repo root:

```bash
.venv-fixture/bin/python -m http.server 8000 --bind 127.0.0.1 --directory web/demo
```

Open **http://127.0.0.1:8000**. Keep that terminal running; stop it with Ctrl+C.
Choose a different port if 8000 is occupied. Serve over HTTP rather than
opening `index.html` with `file://`, because the page fetches `data.json`.

The website is static HTML/CSS/JavaScript with adjacent aggregate evidence.
It has **no backend, model calls or scientific execution endpoints**. A local
HTTP server is only serving files. See [website details](../web/demo/README.md).

## 4. Scientific + native environment

Create a separate environment; do not replace an existing team's verified
environment or silently change its pinned science dependencies.

```bash
python3.12 -m venv .venv-omnigent
.venv-omnigent/bin/python -m pip install 'omnigent==0.16.0' -r requirements-science-lock.txt
.venv-omnigent/bin/python -m pip check
.venv-omnigent/bin/omnigent --version
```

The science lock pins the scientific dependency tree; Omnigent itself is pinned
to 0.16.0, while its additional transitive dependencies are resolved by pip.
This is not claimed to be a fully locked cross-platform native environment.
Do **not** install `requirements-omnigent-windows-lock.txt` on macOS/Linux:
it includes Windows-specific packages. If pip reports a version conflict,
stop and inspect it rather than loosening the scientific pins.

If you use an existing `uv` installation instead:

```bash
uv venv --python 3.12 .venv-omnigent
uv pip install --python .venv-omnigent/bin/python 'omnigent==0.16.0' -r requirements-science-lock.txt
uv pip check --python .venv-omnigent/bin/python
```

Choose **one** environment creation route. A uv-created environment can lack
pip; use `uv pip` rather than assuming `python -m pip` is available.

## 5. Model authentication and native host compatibility

Install Codex CLI using the [official CLI instructions](https://learn.chatgpt.com/docs/codex/cli).
Use your own authorized account; never copy a teammate's credentials into Git.
The [official authentication guide](https://learn.chatgpt.com/docs/auth) documents:

```bash
codex --version
codex login
codex login status
```

On a supported headless setup, `codex login --device-auth` is an alternative
when enabled for your account/workspace. Authentication does not guarantee
access to the model configured in the YAML. If using API-key authentication,
follow the official guide and keep credentials in your private host environment.

**Additional project prerequisite:** the launcher requires an executable
`codex-code-mode-host` compatible with your installed CLI. It looks beside
the resolved CLI binary, or uses an explicitly configured absolute path:

```bash
export CODEX_CODE_MODE_HOST_PATH="/absolute/path/to/compatible/codex-code-mode-host"
test -x "$CODEX_CODE_MODE_HOST_PATH"
.venv-omnigent/bin/python scripts/run_native_adaptive.py --check-only --finalize-discovery
```

Replace the placeholder with the real provisioned binary. The repository does
not distribute this binary or provide a universal installer for it. A normal
Codex CLI install/login alone is **not** a guarantee of native readiness. If
the compatible host is unavailable, stop here and use the fixture/evidence
replay; do not substitute a shell wrapper or bypass the guarded harness.

Expected preflight status is `configuration_validated`. For the native path,
inspect `bootstrap_route_available`; it must be true. Check-only deliberately
reports `runtime_ready: false` and unverified guardrails because it makes no
live calls. It is configuration validation, not proof of authenticated live
execution or runtime confinement. Actual acceptance is checked during a run.

Models are configured in `agents/adaptive-live.yaml` and the finalization and
holdout fragments. An optional `--model` overrides specialist/root routes;
Luna is not a structural requirement. Use a route your account can access.

## 6. Obtain and verify frozen prepared data

For exact native09-source reproduction, download both assets from the private
[prepared-data release](https://github.com/number8868/agentic-scientific-discovery/releases/tag/data-prepared-20261003-v1):

- `nova-prepared-jarvis-v1.zip` (134,455,054 bytes).
- Its `.sha256` sidecar.

Before extraction, verify the archive SHA256 using your OS's hash utility:

```bash
# macOS; on Linux use: sha256sum nova-prepared-jarvis-v1.zip
shasum -a 256 nova-prepared-jarvis-v1.zip
```

Expected: `25fc3e46efff1b6a6e1f60f8453f40b92a3a81f23a630cb80fde0ecebdf48773`.
For a **fresh checkout with no existing prepared `data/`**, place the verified
archive at the repository root, inspect its members, then extract and check:

```bash
unzip -l nova-prepared-jarvis-v1.zip
unzip -n nova-prepared-jarvis-v1.zip
.venv-omnigent/bin/python scripts/check_prepared_data.py
```

Expected readiness is `status: ready`. The check hashes files and metadata;
it does not execute science or inspect holdout outcomes. If prepared data
already exists or hashes disagree, stop and investigate; do not overwrite,
reroll the split, or mix sources. The archive contains no model credentials,
live context or SQLite runtime state. Never commit its raw/prepared files.

Alternatively, [A's data guide](A_DATA_HANDOFF.md) describes public JARVIS
preparation with `scripts/nova.py prepare`. That can require network downloads;
it must produce the expected frozen-source hashes before being treated as the
same source. Preparation does not authorize any holdout execution.

## 7. Start an approved fresh discovery run

Coordinate a single operator/host first. Check-only is safe, but the following
preparation **computes a primary discovery Result**, and live mode consumes
model usage and may compute a follow-up. Do not run it merely to view a demo.

```bash
.venv-omnigent/bin/python scripts/check_prepared_data.py
.venv-omnigent/bin/python scripts/run_native_adaptive.py --check-only --finalize-discovery
.venv-omnigent/bin/python scripts/prepare_adaptive_run.py --database runs/my-new-discovery/run.sqlite --run-id my-new-discovery
.venv-omnigent/bin/python scripts/run_native_adaptive.py --enable-native-live --finalize-discovery --remaining-seconds 600
```

Use a new run ID and previously nonexistent database **inside `runs/`**.
If `.nova/live_context.json` already exists, coordinate finishing or explicitly
archiving that run before preparing another. Do not delete it automatically,
reuse a failed run or reset its budget. The primary question/screen is host-seeded.

This command does **not** request holdout execution. A legal method or stop
choice may not support the threshold-path finalization; preserve that outcome
instead of forcing the desired experiment. Holdout requires separate explicit
approval, supported freeze and a bounded native gate. Do not rerun native09
or invoke the holdout tool directly to improve a result.

With the scientific/native dependencies installed, run the offline suite:

```bash
.venv-omnigent/bin/python -m pytest
```

The native09 report's 426-pass regression is historical, not a guarantee for a
new platform. Full fresh native installation/model/data execution was not
rerun to write this guide; the isolated fixture/core checks were verified.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| GitHub repo/release not found | Check your private-repository access and GitHub authentication |
| `python3.12` not found | Install Python 3.12; do not use macOS's older system Python for native science |
| Missing `numpy` / `omnigent` / `yaml` in full tests | Use the full environment, not the fixture-only one |
| `No module named pip` in a uv environment | Use `uv pip --python ...`, or create a separate standard venv |
| `codex` not on PATH | Install CLI and start a shell with the correct PATH |
| Missing executable code-mode host / unavailable bootstrap route | Provision a compatible host; login alone does not resolve this blocker |
| Permission check fails on Windows | Use WSL's Linux filesystem; do not weaken the checks |
| Prepared-data hash mismatch | Preserve files; reconcile the exact source/transfer rather than changing the split |
| Database / live context already exists | Coordinate ownership and archive intentionally; never overwrite a run |
| Website cannot fetch JSON | Serve `web/demo` over localhost HTTP, not `file://` |
| Holdout is inconclusive | This is a scientific outcome, not an installation error; do not tune/repeat holdout |

For current results, use [native09](results/native09_completed/README.md) and
[A's independent acceptance](results/native09_science_acceptance/README.md).
Older handoffs describe historical milestones, not current completion status.
