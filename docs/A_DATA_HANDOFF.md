# Same-source prepared-data handoff for the live orchestration

Team B's missing data/science dependencies are environment prerequisites. Team A's local `data/manifest.json`, raw snapshot and prepared tables already exist, and the isolated Windows Omnigent environment has NumPy 2.5.3 and jarvis-tools 2026.6.12. Both real templates have run successfully through B's adapter in that environment.

Do not add raw/prepared data, `.nova/live_context.json`, credentials or live SQLite files to Git. The JARVIS source is public; the repository records the source attribution and checksum rather than distributing large local inputs. Team B can prepare locally from the same public archive, or receive an exact local copy through a separately agreed transfer route.

The user-authorized exact-copy transfer is now uploaded to the [private repository release](https://github.com/number8868/agentic-scientific-discovery/releases/tag/data-prepared-20261003-v1). Download `nova-prepared-jarvis-v1.zip` and its `.sha256` sidecar. The archive is 134,455,054 bytes (about 128 MiB), SHA256 `25fc3e46efff1b6a6e1f60f8453f40b92a3a81f23a630cb80fde0ecebdf48773`. GitHub reports both assets as uploaded and the same archive digest. All seven data members were matched byte-for-byte by hashes before upload. Extract at the repository root; install science dependencies and run the readiness check below. No runtime context, database, credentials or environments are included. The archive is a release asset, not a Git source-data commit.

## Prepare on Team B's Linux host

After pulling current main and creating the Omnigent environment, install the science packages without silently changing their versions:

```bash
.venv-omnigent/bin/python -m pip install -r requirements-science.txt
.venv-omnigent/bin/python scripts/nova.py prepare
.venv-omnigent/bin/python scripts/check_prepared_data.py
```

If the environment was created without pip, use `uv pip install --python .venv-omnigent/bin/python -r requirements-science.txt`. Preparation selects the official JARVIS `dft_3d` source and freezes its cache, composition representatives and split. If an existing local preparation disagrees with the reference, stop and investigate; do not replace the protocol or reroll the split to make the result pass.

The hash check reads file bytes and metadata only. It does not inspect holdout outcomes. The expected source archive is `jdft_3d-9-24-2025.json.zip`, 93,902 structures:

| Frozen artifact | Expected SHA256 |
|---|---|
| Original ZIP | `f9e0a3309f0000d5de1ec9e49c93963109ea45e63f451103f8f6595d2eabf7f5` |
| Original inner JSON | `9dacb55ac8371c7c2bf0332933b55c98e9cca6201e92eb9d6fcd03aab0975907` |
| Original protocol | `9497988f1f8443f66326fa66a976d7196e5671ad320a1cce8a638780a8fc64ac` |
| Composition representative CSV | `d7184816ea97e4daa860b1a93a387b56a82280d3758eb2f658fbfa7ab021fb50` |
| Split assignment | `96c9c210f77698d47bfdb68f9b3ad65673766a879785a6c7d983d7ee3777a58c` |

The snapshot reference is `docs/results/first_manifest.json`; the threshold extension remains independently pinned in `docs/THRESHOLD_PROTOCOL.json`.

## Start a fresh live run only after readiness passes

```bash
.venv-omnigent/bin/python scripts/prepare_live_run.py --db /tmp/nova-live-unique.sqlite --run-id live-unique
.venv-omnigent/bin/python scripts/check_live_config.py
PATH=.venv-tmux/bin:$PATH .venv-omnigent/bin/omnigent run agents/opensource-live.yaml
```

Choose a new database/run ID. These are B's controlled orchestration entrypoints, not A's earlier human-scripted launcher. The canonical Results, model/tool audit and stored review must all belong to this new run before claiming success. Copying a prior Result is not a substitute for a tool invocation.

## Windows / WSL boundary

Native Windows installation and scientific execution succeeded, but Omnigent 0.16.0's Codex session launch requires an exact POSIX 0700 private home and fails on the local Windows filesystem. The B live context also requires POSIX 0600. Do not weaken either check. A is validating the existing Ubuntu WSL environment; runtime/context state must be on its Linux filesystem, not the Windows drive mount. This platform distinction does not change the source data or scientific protocol.
