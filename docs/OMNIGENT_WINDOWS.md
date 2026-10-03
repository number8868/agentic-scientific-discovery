# Windows Omnigent installation and real science adapter

Verified on 2026-10-03: Windows, Omnigent 0.16.0 (build 2026-09-29T19:16:56Z), isolated CPython 3.12.15, Node 24.15.0, Codex CLI 0.160.0. Existing Codex login was available; no credentials are recorded here. The original `.venv` science environment is preserved.

## Install locally

The project-local bootstrap environment supplies uv without modifying system Python:

```powershell
python -m venv .venv-omnigent-bootstrap
.\.venv-omnigent-bootstrap\Scripts\python.exe -m pip install uv
$env:UV_PYTHON_INSTALL_DIR = "$PWD\.venv-omnigent-python"
$env:UV_CACHE_DIR = "$PWD\.venv-omnigent-cache"
.\.venv-omnigent-bootstrap\Scripts\uv.exe venv --python 3.12 .venv-omnigent
.\.venv-omnigent-bootstrap\Scripts\uv.exe pip install --python .venv-omnigent\Scripts\python.exe -r requirements-omnigent-windows-lock.txt
.\.venv-omnigent\Scripts\omnigent.exe --version
.\.venv-omnigent\Scripts\omnigent.exe run --help
```

The dependency lock records the installed Omnigent and scientific packages. Local environments, caches and generated runtime state are ignored by Git. Keep the uv cache on the project drive: the first freeze attempt with its default cache failed during a cross-drive temporary-file rename; setting `UV_CACHE_DIR` resolved that failure.

## Verified adapter path

```powershell
.\.venv-omnigent\Scripts\python.exe scripts/run_live_science.py --science-adapter --two-rounds
```

The optional flag binds B's `nova.science_adapter.execute_science_experiment`; the original direct route remains the default. Run `live-d3e2875275af` completed both real discovery templates with the new Python 3.12 environment. Every threshold count, interval and primary scientific field matched the earlier frozen results. Canonical spec hashes, review/parent references, event order and every exported artifact hash were independently checked. The portable package is in `docs/results/windows_adapter_run`.

The adapter/executor/integration test selection passed all 23 tests in the new environment. The newly synced full suite in the original environment passed 94 tests and failed four Windows-incompatible fixture checks: POSIX mode 0600 enforcement and privileged symbolic-link creation. The existing fixture bridge fails closed; its checks have not been weakened. These failures were reported to Team B on PR #3. The offline `check_open_source_env.py` helper also strips Windows-required environment variables: direct CLI version/help succeeded while that helper returned false. These are platform compatibility findings, not a successful full-suite or fixture-bridge validation.

## Real model integration boundary

The [official Windows notes](https://github.com/omnigent-ai/omnigent#windows-native) support SDK harnesses such as `codex`; the native terminal harness used in B's Linux fixture (`codex-native`) requires tmux and is not a native Windows route. The installed 0.16.0 `CodexExecutor` supports explicit native-tool/web-search disabling, allowing a separately bounded registered-function pilot. This internal SDK path must be validated with actual tool-call evidence before claiming a model-driven loop. Installation and the adapter runs above alone do not prove that loop or the Databricks route.

Holdout outcomes remain closed, and hard worker timeout/cancellation remains a separate runtime verification requirement.
