# Team B submission handoff

Status at main `7da9673` (PR #17 merged): B's bounded native final-review and
freeze path is implemented. The final response is captured before verification,
and a verifier failure does not write a completion event. The combined
regression suite recorded in [team status](TEAM_STATUS.md) passed 381 tests.
These implementation and regression results do not establish clean live-run
acceptance.

## What is implemented

- Two native Omnigent CLI sessions share the run/database binding, audit file,
  and original deadline. The second session performs a real final Skeptic
  review and PI freeze for the supported family-screen/threshold-sensitivity
  path.
- Freeze derives its parameters from registered immutable Specs and returns a
  registered, unexecuted holdout ID. Holdout execution is not exposed by this
  tranche.
- The launcher captures final CLI text before host verification; verification
  failure cannot silently turn into a completion event.

## Acceptance still open

- Structured final PI capture is implemented on 7e83952 (382 regression tests
  passed), preserving the exact TurnComplete text and linking it to the guarded
  successful freeze call. Fresh run 05 failed earlier: Runner's scientific tool
  completed, but its model turn failed and PI reported exhausted tool calls.
  Finalization was not entered; this does not live-validate the new capture.
  See [run 05 evidence](results/native_adaptive_live_05_runner_turn_failed/README.md).
- Native run 04 completed discovery, final review and freeze, but exited 1
  because the final CLI output did not match the guarded response metadata hash.
  The mismatch remains unexplained. The preserved failure and posthoc text
  checks are documented in [team status](TEAM_STATUS.md) and [run 04 evidence](results/native_adaptive_live_04_frozen_cli_failed/README.md).
- Structured raw PI response capture and diagnosis are in progress. This is
  follow-up work; it does not change the preserved run 04 failure or establish
  acceptance until a fresh run passes the full native checks.
- Do not call run 03 or run 04 a clean CLI success. The 381 passing tests are
  historical regression evidence, not a clean live acceptance run.
- A fresh-context native finalization run with preserved successful exit code,
  linked model/tool trace, second review, frozen protocol, and untouched
  holdout ID is still required for clean acceptance. Do not replay or reset a
  failed run, and do not execute holdout as a demonstration.
- Full challenge completion, three engineering rehearsals, a final demo gate,
  and measured speedup remain unestablished. Do not claim “10x” or any other
  acceleration without the paired measurement.

## Teammate setup and entrypoints

Clone GitHub, update `main`, and confirm it contains merged PR #17 (main was
`7da9673` when this handoff was written):

```bash
git clone https://github.com/number8868/agentic-scientific-discovery.git
cd agentic-scientific-discovery
git switch main
git pull --ff-only
git merge-base --is-ancestor 7da9673 HEAD
uv venv --python 3.12 .venv-omnigent
uv pip install --python .venv-omnigent/bin/python 'omnigent==0.16.0' -r requirements-science-lock.txt
.venv-omnigent/bin/python scripts/check_prepared_data.py
.venv-omnigent/bin/python scripts/run_native_adaptive.py --check-only
.venv-omnigent/bin/python scripts/prepare_adaptive_run.py --database runs/my-discovery/run.sqlite --run-id my-discovery
.venv-omnigent/bin/python scripts/run_native_adaptive.py --enable-native-live --model gpt-6-luna --remaining-seconds 600
```

The Omnigent installation and offline checks are documented in
[OPEN_SOURCE_OMNIGENT.md](OPEN_SOURCE_OMNIGENT.md). Scientific dependencies,
the frozen data archive, and its readiness check are in [A's data handoff](A_DATA_HANDOFF.md).
These are README's current fresh-discovery commands; the native CLI also needs
a matching executable code-mode host configured with `CODEX_CODE_MODE_HOST_PATH`.
The optional `--finalize-discovery` invocation and its fresh-run restrictions
are in [B's native finalization guide](B_NATIVE_FINALIZATION.md). Setup does
not itself authenticate a provider or establish live acceptance. Use new
run/database paths and an authorized local model login.

## Submission/demo checklist

- [ ] Use the two-minute structure in [LIVE_DEMO.md](LIVE_DEMO.md); show the
  actual run provenance and recorded artifacts.
- [ ] Label run 04 as failed CLI acceptance with an unexplained final hash
  mismatch; distinguish posthoc checks from a clean run.
- [ ] Say that the registered holdout remains unexecuted and its outcomes were
  not examined. A's data, statistical interpretation, and holdout decision
  remain A's scientific review responsibilities.
- [ ] Keep the sparse nine-pass result, snapshot scope, correlated threshold
  sensitivity, and screening-only meaning explicit. Do not imply a material
  performance result, clean success, or 10x acceleration.
- [ ] Keep `.nova/live_context.json`, local SQLite databases, prepared/raw data,
  credentials, private auth/session files, and local environments out of Git.
  Share private data only through the separately documented private release
  handoff; never add runtime-private state to submission evidence.
