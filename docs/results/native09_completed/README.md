# Native09: complete bounded native validation

Source `19a1c91`; run `native-adaptive-live-09`. The original native launcher
returned exit 0. Discovery choice, Runner feedback, final Skeptic review, PI
freeze, dedicated holdout Runner and evidence export all completed under one
600-second parent deadline (approximately 188 seconds from trace start to final
model turn). The initial hypothesis/family screen remained host-seeded.

The final freeze explanation passed on its first call. The native holdout stage
contains a real guarded `execute_frozen_native_holdout` call and completed model
feedback, not a model-only completion claim. Eight executor PIDs and thirteen
completed model turns are recorded across three CLI sessions.

- Discovery follow-up Spec: `NOVA-0fcce1f550b846ed`.
- Discovery follow-up Result: `nova-result-0ebf806b3bd6a00b78d742d0cf5c5e34f655aa4c5b3a726c8f7b7489679c15b9`.
- Final protocol SHA: `016efccbe5a473d4101a42ad7109cde5e8662feeae835109f235e40a594d16e5`.
- Holdout Spec: `NOVA-HOLDOUT-f4c48d7913f24919`.
- Holdout Result: `nova-result-ec1717ee5923f960e1b69964ef1da537043547da6bedfeb9d350f3397009a210`.
- The sole SQLite holdout claim is `succeeded`, bound to that Result.

The stored scientific status is `direction_consistent_inconclusive`, not
`replicated_in_snapshot`. At the primary threshold, oxide has 1 pass among
3,282 observed representatives; chalcogenide has 3 among 1,354, with 100%
coverage in both. The contrast is 0.19110 percentage points and its resampling
interval is [-0.03047, 0.48652] percentage points, crossing zero. All three
frozen threshold comparisons retain the same inconclusive validation status.
A remains responsible for independent scientific acceptance and interpretation.
No further holdout computation should be launched to improve this result.

Published files contain the scientific export, host-returned holdout Result,
sanitized native audit and runtime manifest. `hashes.json` covers the package;
`manifest.json` covers the exported artifacts. Exact raw final PI response and
SQLite remain private locally. Portable files are recorded evidence, not runtime
authorization or independent attestation of provider identity/OS confinement.
Original CLI exit is reported from the root's observed command result, not
inferred solely from portable hashes.

Final offline regression: 426 passed, zero failures/skips, 23.22 seconds.
Native08's pre-freeze length failure and native07's repaired discovery-only run
remain separate preserved records. This run establishes engineering completion,
not a baseline speedup or scientifically replicated discovery. Matched baseline,
recording and submission packaging remain pending.
