# Bounded real Luna pilot — verified two-round run

Run `luna-pilot-06` completed both real discovery experiments through Omnigent's Codex SDK with `gpt-6-luna`: nine model turns, six successful function calls, two scientific Results, one actual model-authored review and eleven live events. Three completely empty tool turns were repaired once each before advancing the role. The host never executed a missing model call itself. See [portable evidence](results/omnigent_luna_run) and [independent verification](results/omnigent_luna_verification.json).

The first result has 3/7,657 oxide and 6/3,158 chalcogenide passes. Its model review correctly identifies the small pass counts and broad interval as a reason to check threshold sensitivity. The follow-up spec cites that actual first Result and review. All three frozen thresholds reproduce the previously verified counts; the primary difference remains 0.15081 percentage points, with a 95% bootstrap interval of [0.01109, 0.32220]. This is a correlated sensitivity check within one snapshot. Holdout outcomes remain closed.

## Earlier incomplete attempts

Five earlier real attempts stopped when a role returned without invoking its registered tool. Their original evidence is preserved separately:

| Attempt | Successful function calls | Completed scientific Results | Stop |
|---|---:|---:|---|
| luna-pilot-01 | 5 | 1 | Second Runner made no tool call |
| luna-pilot-02 | 3 | 1 | Skeptic made no tool call |
| luna-pilot-03 | 4 | 1 | Second PI made no tool call |
| luna-pilot-04 | 1 | 0 | Initial PI made no tool call |
| luna-pilot-05 | 3 | 1 | Skeptic made no tool call after installing the host |

Portable records are in [the attempt exports](results/omnigent_luna_attempts). Their shared-record, model-audit and science-payload digests were independently checked, as were registered spec hashes and discovery split membership. The failure summaries are in [verification.json](results/omnigent_luna_attempts/verification.json). Original SQLite databases, live contexts and login files remain local.

## Scope and environment

The host fixes six role steps: Planner → initial PI → first Runner → Skeptic → second PI → second Runner. It exposes one function per role, accepts exactly one successful call, and uses B's registered decision and live-execution tools for durable transitions. A completely empty tool turn can receive one explicit repair prompt for the same role, with no host mutation. At most twelve model turns and six actual function calls are permitted. Tool errors, partial calls, timeouts and changed host state never receive this retry. It fixes `family_screen` followed by `threshold_sensitivity`; it does not test autonomous choice of an unrestricted research direction.

The verified environment is Ubuntu WSL, Python 3.12.13, Omnigent 0.16.0, Codex CLI 0.160.0, Node 24.15.0 and the frozen scientific dependencies. Windows Omnigent installation succeeded, but its SDK's POSIX private-home permission check prevents this pilot from starting natively on NTFS. Linux Codex and Node archives were checked against their official release digests.

The script uses Omnigent's internal `CodexExecutor`, pinned to 0.16.0. It disables native tools and web search via SDK configuration and filters skills to `none`. These settings and role checks establish the host's function boundary; this run does not independently verify a complete OS sandbox, the YAML multi-agent server or Databricks deployment.

Attempts 02 and 03 contain model responses reporting an unavailable function/code-mode host. Installing Node did not resolve that behavior. Attempt 04 disabled both `features.code_mode_host` and `features.code_mode` before app-server startup, but still produced a no-tool response. The SDK has no required-tool-choice control, so even a correctly configured role may finish without a function call. The bounded repair records this condition and prompts the same role once; it never retries an actual failed or partial tool execution. The exact cause of every earlier no-tool response is not established.

The original standalone CLI archive contained only `codex`. The matching separately shipped `codex-code-mode-host` was subsequently installed. Its Linux archive SHA256 is `ac6cd6288f0e39f46a33eba1cfd37711651f14f33dbc73d6a1b82eb45e038cac`, checked against the [official 0.160.0 release](https://github.com/openai/codex/releases/tag/rust-v0.160.0). The current script enables the host and forwards only an explicitly configured executable path through Omnigent's filtered child environment.

## Reproduction

Use a Linux filesystem checkout, the [same-source prepared dataset](A_DATA_HANDOFF.md), the pinned Omnigent/science environment and an existing local Codex login. Keep the SDK's private home on Linux with owner-only permissions. On this host we reused the existing login through a private local auth-only directory; no credential was placed in a repository or evidence export.

With `python`, `codex`, `node` and the relevant environment on PATH:

```bash
export CODEX_CODE_MODE_HOST_PATH=/absolute/path/to/codex-code-mode-host
python scripts/check_prepared_data.py
python scripts/run_omnigent_live.py \
  --database runs/new-luna-pilot/run.sqlite \
  --run-id new-luna-pilot
```

The database, audit and evidence paths must be new. If `.nova/live_context.json` belongs to an earlier run, verify its run/database identity and archive it privately before preparing another run. The script retains portable failure evidence and aborts if a clean no-tool reply persists after its one repair, rather than executing the missing step itself.

## Review and validation

All 145 tests passed on Linux after the process-boundary and bounded-repair changes, including twelve controlled-host tests. The process controller now drains the pipe concurrently, preventing large results from blocking a child while its parent waits for exit. An 8 MiB round-trip regression and actual timeout/reap test passed. One deadline covers execution, result receipt and worker exit after synchronous `Process.start()` returns; process creation and cleanup have separate costs.

After recording the run, main `f366048` was merged, including B's bounded YAML launcher and fresh-session checks. The Linux checkout's `.venv-omnigent` points to the installed Linux environment; the merged suite passes 154 tests. The recorded model run still describes the bounded SDK host, rather than a new execution of that YAML configuration.

Independent checks paired all six actual request/completion IDs and roles, checked the nine model-turn observations and three zero-call repairs, verified every exported record and scientific payload digest, validated registered-spec hashes and the parent/review links, and checked all primary and threshold counts. The successful review's actual model arguments match its stored text; its numerical interpretation was also checked by a human reviewer.

Attempt 03's Skeptic incorrectly called the observed pass-rate difference a missingness difference. The stored review is preserved as emitted; it should not be used as a scientifically correct presentation quote. The revised prompts explicitly distinguish the joint bandgap-plus-ehull screening endpoint from missingness and report actual coverage. The completed run's model review correctly uses the screening pass-rate endpoint.

The model audit retains backend-reported usage. Some reported total-token values differ from input plus output; do not infer billing from those sums. The discovery snapshot and all frozen pipeline/dependency hashes remain unchanged. Holdout outcomes remain closed.
