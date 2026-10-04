# Independent acceptance of the failed native run's science

The stored scientific records in `native-adaptive-live-01` pass A's
independent hash, arithmetic and historical-value checks. **The native
workflow remains failed.** This audit reads published discovery artifacts
only; it does not retry a worker, invoke a model, inspect prepared properties,
read holdout outcomes, or reconstruct native authorization.

Source: [B's unmodified published bundle](../native_adaptive_live_01_failed/manifest.json)
at `fe02c2a`, incorporated into the A/B integration base `9cda56f`.
The [independent verification](independent_verification.json) records the
checks and limitations. It verifies 11 manifest entries and all 12 entries
in the source `hashes.json` inventory, which additionally covers the manifest.
Source bytes and the six protected scientific source hashes are unchanged.

## Registered identity and scientific identity

| Template | Registered Spec SHA256 (prefix) | Computation Spec SHA256 (prefix) | Persisted Result |
| --- | --- | --- | --- |
| `family_screen` | `18d3c69254b8475a` | `f5eaf8c139baa0f7` | `nova-result-13c98cb8a52d8ec707c385f5bdd057aba53674c16b1c1eaf14eba9b7c812c0b5` |
| `threshold_sensitivity` | `ecc07dd876b916ae` | `6bd6307e8d56b6ba` | `nova-result-6ba5a4a44b20423060e1527444aecc710cbb7609c350d38755660fd44057826c` |

The registered hash includes experiment identity and registration metadata. The computation
hash describes the minimized scientific input, including the frozen threshold
extension where applicable. They are intentionally different. Independently
reconstructed both hashes, verified each against its matching payload field,
checked content-addressed Result IDs, and compared canonical stored Result
facts with the science payloads. Full digests are in the verification JSON.

For B's response validator, compare `Result.spec_sha256` and payload
`registered_spec_sha256` to the registered Spec hash. Compare the inner
`science_result.spec_sha256` and payload `computation_spec_sha256` to the
expected minimized computation hash. A's existing
`nova.holdout_bridge._artifact_payload` already implements that distinction
for discovery payload checking; calling that checker is not holdout execution.
Do not overwrite either hash or discard/rerun the completed science to repair
the feedback envelope.

B's reported failure message is operator-supplied rather than a captured
native traceback. The artifact checks verify the two identities and are
consistent with B's diagnosis; they cannot independently reconstruct the
exact uncaptured failing call. See [the runtime limits](../../NATIVE_ADAPTIVE_BLOCKERS.md).

## Scientific facts and stored interpretation

The primary Result exactly matches the original published discovery scientific
fields. Every threshold point and the full stored bootstrap metadata, flags,
intervals and primary summary match the earlier checked threshold result.
Counts/rates/differences were also checked arithmetically. This is comparison
of stored evidence; it is not a new raw-data or bootstrap recomputation.

| Frozen threshold (eV/atom) | Oxide passes / 7,657 | Chalcogenide passes / 3,158 | Difference (percentage points) | 95% resampling interval (percentage points) | Status |
| --- | ---: | ---: | ---: | --- | --- |
| 0.025 | 2 | 5 | 0.13221 | [0.00555, 0.29054] | `supported_in_snapshot` |
| **0.050, primary** | **3** | **6** | **0.15081** | **[0.01109, 0.32220]** | `supported_in_snapshot` |
| 0.100 | 3 | 8 | 0.21415 | [0.04830, 0.39859] | `supported_in_snapshot` |

All discovery coverage rates are 100%. The missingness bounds collapse to the
observed rates; the contrast is a screening pass-rate difference, not a
missingness gap. The positive threshold direction is supported within this
snapshot, with only 7–11 passes per point. The grid is correlated sensitivity,
not independent replication or a performance claim.

The saved review's four field references resolve to its actual parent Result.
Its rounded delta/interval and 3-versus-6 sparse-count concern are correct.
The selected follow-up cites that parent and responds to the recorded
threshold-robustness concern. Its 60-second feasibility figure is a planning
estimate, not observed model or workflow latency. Human scientific reading
accepts these stored statements; it does not attest model authorship.

No method audit request/result exists in this run. It supplies no candidate-JID
model review or OPT/MBJ selection evidence. The separately published
[method result](../paired_method_audit/README.md) remains independent of that
orchestration claim.

## Remaining runtime and validation boundaries

- The 18 host events end with Runner failure and orchestration failure after
  the second science Result. No supervisor return is evidenced.
- The five native-audit records contain a startup header and four host
  function-completion entries; no captured model request, tool completion or
  completed model turn exists. Role identity and runtime guard enforcement
  remain unverified.
- Host native-start to failure markers span 114.805177 seconds. This excludes
  primary setup and does not isolate model latency. Complete model usage and
  billed cost are unknown; there is no baseline pair or speedup claim.
- Original family/threshold freeze, native lineage and the single-attempt
  gate are still required for real holdout. This failed run has no substitute
  authorization and must remain failed.

Use [the scientific submission wording](../../SCIENCE_SUBMISSION_BRIEF.md)
and [baseline comparison plan](../../BASELINE_COMPARISON_PLAN.md) while B
completes its runtime repair. Current audit activity makes zero new model or
science calls and claims no browser verification.

## Reproduce the portable audit

From a Linux/WSL source checkout using the existing Linux environment:

```sh
.venv-omnigent/bin/python scripts/audit_discovery_bundle.py \
  --evidence-dir docs/results/native_adaptive_live_01_failed \
  --output runs/science-audit-01
```

Choose a fresh output directory. The source package is read-only; the command
writes just `audit.json` and `manifest.json` after every check passes. It
checks Spec/run metadata before outcomes, hashes/counts all allowlisted
manifest files, and validates temporary copies of the payloads with the
existing discovery checker. Every grid point must preserve the parent's total
and evaluable counts, and passes must not decrease as the hull limit widens.
It creates no accepted output for rejected evidence.

The existing checker requires POSIX private-file modes. Full validation is
performed on Linux/WSL; the new CLI does not replace shared guards to simulate
that check on Windows. It is a local evidence utility, not an ID-only execution
tool or a native authorization gate.

The [CLI report](audit.json) and [output manifest](manifest.json) reproduce
the distinct identities and grid consistency. Independently compared their
12 source digests and factual output to the earlier manual check. The report
does not authenticate the raw dataset, recompute bootstrap intervals, verify
model-role identity, interpret every prose statement, or certify native
completion. The separate human reading in this document has that narrower
stored-text scope. Zero-model counters refer to scientific-role/runtime
calls; the coding helper used `gpt-6-luna` / `max` separately.

The final [regression record](validation.json) reports **336 Linux tests
passed without skips**, including 14 new audit cases and the direct clean-root
CLI test. Re-signed wrong contract hashes, altered stored facts, changed
primary/grid counts, nonmonotonic passes, ownership errors, missing/traversal
paths, strict JSON errors and premature holdout are rejected. Windows covers
six preflight/error cases and skips eight POSIX-only cases, all exercised on
Linux. Initial Linux failures were three error-message test expectations;
the final tests prove the underlying guard reason and generic public error.
