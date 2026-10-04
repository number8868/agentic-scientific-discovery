# Scientific submission wording and evidence

Prepared from published discovery evidence after the method audit. This is
submission material for the verified scientific component; it is not a
recording, a new computation or evidence that the complete agent workflow
succeeded. Keep the run-specific orchestration claims separate.

## Claims that the current evidence supports

| Claim | Exact scientific reading | Evidence |
| --- | --- | --- |
| Primary OPT screen | 3/7,657 oxide and 6/3,158 chalcogenide representatives pass the inclusive 1.1–1.8 eV gap window and energy above hull <=0.05 eV/atom. The difference is 0.15081 percentage points; its 95% resampling interval is [0.01109, 0.32220] percentage points. Status: `supported_in_snapshot`. | [Original result](results/first_family_screen.json), [registered evidence](results/registered_method_integration/README.md) |
| Fixed threshold diagnostic | At 0.025 / 0.05 / 0.10 eV/atom, oxide passes are 2 / 3 / 3 and chalcogenide passes are 5 / 6 / 8. All three statuses are `supported_in_snapshot`. The original primary point remains 0.05. | [Historical verification](results/two_round_verification.json), [latest stored-result audit](results/science_closeout/independent_verification.json) |
| Method-dependent shortlist | The union has 19 candidates: 0 pass both screens, 3 pass OPT only, 10 pass MBJ only, and 6 pass OPT with MBJ unknown. All 13 paired shortlist candidates have discordant screening decisions. | [Candidate CSV](results/paired_method_audit/candidates.csv), [method report](results/paired_method_audit/README.md) |
| Limited paired scope | The paired subset is 1,230/7,657 oxides (16.06%) and 804/3,158 chalcogenides (25.46%). Both paired family comparisons are `inconclusive`. MBJ's zero oxide passes make that endpoint degenerate despite a positive interval. | [Three-arm result](results/paired_method_audit/result.json) |
| Separate method-change contrast | The chalcogenide-minus-oxide contrast in paired MBJ-minus-OPT screening changes is +1.07633 percentage points, with interval [0.24876, 1.98532]. Its separate status is `direction_positive`. | [Method report](results/paired_method_audit/README.md) |
| Scientific integration | Registered execution, immutable payload linkage, candidate citations and structured reviewer fact validation have been implemented and checked. | [Registered integration](results/registered_method_integration/README.md), [review readiness](results/method_review_readiness/README.md) |

The counts describe already reported computational records and the frozen
representative selection. They do not establish new materials, synthesis,
device performance or experimental truth. MBJ is an alternative computational
method. A positive method-change contrast is a different estimand from the
family comparison and is not independent validation. The three threshold
points reuse the same compositions and are correlated.

## Three material examples for the demonstration

These examples illustrate evidence categories, not a performance ranking.
Each row uses the same representative JID for both methods. Source:
[the verified shortlist](results/paired_method_audit/candidates.csv).

| Representative | OPT gap (eV) | MBJ gap (eV) | Energy above hull (eV/atom) | Screening evidence | Next useful validation |
| --- | ---: | ---: | ---: | --- | --- |
| JVASP-50168, KRbO | 1.794 | 4.156 | 0.00 | OPT passes; MBJ fails the gap window | Check methods, convergence and structural inputs for this same JID. |
| JVASP-107267, Zn2TeSe | 0.385 | 1.684 | 0.00 | MBJ passes; OPT fails the gap window | Check methods, convergence and structural inputs for this same JID. |
| JVASP-120874, BaZnSe | 1.709 | Unknown | 0.03 | OPT passes; comparator evidence is missing | Obtain the missing MBJ calculation before a cross-method claim. |

The final column is proposed work. No new DFT calculation or material
validation has been performed for these examples.

## Short scientific narration

This text is intended for the scientific part of a short video. It still
needs a timed rehearsal and recording; no video-duration check is claimed.

> NOVA-MAT audits whether a materials screening conclusion survives a change
> in computational evidence. In our frozen JARVIS discovery snapshot, three
> oxide and six chalcogenide representatives pass the original OPT screen.
> The positive family difference persists across three fixed stability
> thresholds, with sparse, correlated outcomes. Pairing OPT and MBJ on the
> same representative IDs exposes thirteen discordant candidates and six
> OPT candidates with missing MBJ evidence. None passes both screens.
> Paired coverage is only about sixteen and twenty-five percent, and both
> paired family comparisons remain inconclusive. We preserve unknowns,
> statistical states and exact evidence references. This is a computational
> evidence audit; holdout and workflow speed claims remain unverified.

## Run-specific statements for the final presentation

| Evidence | Statement permitted now | Evidence still needed |
| --- | --- | --- |
| [Native finalization run 03](results/native_adaptive_live_03_frozen_cli_failed/README.md) | Real second Skeptic review and PI freeze produced an unexecuted holdout Spec. Six guarded processes completed seven model turns. Original CLI exit 1 at a now-fixed host role-map check remains preserved. | Clean fresh CLI acceptance and persisted final-stage PI prose; actual authorized holdout remains unexecuted. |
| [Adaptive live run 02](results/adaptive_live_verification.json) | One bounded Omnigent model choice selected a threshold follow-up from recorded alternatives and the host executed it. | Independent reviewer invocation and supervisor receiving the new Result before its next decision. |
| [Native discovery run 02](results/native_adaptive_live_02_recovered/README.md) | Four specialist processes completed five model turns, with recorded review/choice, two discovery Results and a PI final response. Original CLI exit 1 was followed by hash-bound host-only validation recovery; no model/science rerun. | A fresh clean-CLI run, initial hypothesis autonomy and final scientific review/freeze integration. No full-workflow or OS-confinement claim. |
| [Review readiness kit](results/method_review_readiness/README.md) | A's structured reviewer validator accepts correct engineering fixtures and rejects incorrect facts/references. | An actual independent model response and a scientific reading of its free text. |
| [Holdout interface](HOLDOUT_VALIDATION.md) | The controlled frozen-protocol interface has synthetic verification. | The single real execution from the original valid native frozen run and its exported comparison evidence. |
| [Baseline protocol](BASELINE_COMPARISON_PLAN.md) | A benchmark design and pending measurement format are available. | Matched complete runs, actual model latency/usage and cost provenance. |

Before publishing a stronger statement, replace the corresponding row with
the exact new evidence and audit. The latest native failure is preserved;
fixing response handling must not relabel or rerun that failed attempt.
