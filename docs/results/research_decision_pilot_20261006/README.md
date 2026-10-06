# Research decision pilot: no demonstrated multi-agent benefit

One prospective paired pilot completed eight new synthetic NOVA-MAT evidence-to-decision cases. Both arms requested `gpt-6-luna` with medium reasoning and three SDK turns per case. The single arm kept draft, critique and final in one persistent thread; the parallel arm used independent Planner and Skeptic followed by PI. Cases and grading were independently reviewed and frozen before execution.

The run completed operationally, with **48 unique reserved SDK turns, eight completed pairs, and 14/16 valid deliveries**. Operational completion does not mean every delivered answer passed its contract.

| Frozen descriptive measure | Persistent single | Parallel specialists + PI |
| --- | ---: | ---: |
| All answers correct and delivery valid, over all eight scheduled cases | 7/8 (87.5%) | 6/8 (75%) |
| Valid deliveries | 7/8 | 7/8 |
| Structured delivery utility, invalid delivery scored zero | 0.875 | 0.7917 |
| Mean delivery cost with invalid deliveries penalized at 150 seconds | 29.869 s | 30.064 s |

Across all eight paired delivery costs, the median relative saving `1 - parallel/single` was **−4.01%**. Parallel was faster on three cases, slower on four, and tied on the one case where both deliveries received the invalid-delivery penalty. The 150-second penalty is a scoring convention, not observed runtime. No speed or quality benefit is established.

The deterministic visible-state policy selected the accepted action on **8/8 cases**. It checks budget, blockers and completed templates; it does not evaluate conclusions or explanations, so its action accuracy is not comparable to the three-field full-decision endpoint. This result nevertheless shows that the action choices in these packets do not require multiple agents.

## Failure feedback

- **Provenance conflict, single:** final response had one extra trailing closing brace. It could not be parsed as the required JSON. The raw text visibly selected the expected answers, but remains invalid and unassessable by the frozen JSON grader.
- **Provenance conflict, parallel:** objective answers and citation set were correct; the explanation exceeded the visible 500-character limit. Delivery remains invalid.
- **Easy threshold, parallel:** action was correct, but the final answer chose `inconclusive` and disallowed the positive claim because it considered traceability unestablished. The frozen gold treats the packet's registered Result ID, fixed snapshot and registry audit as traceable and expects the narrowly supported claim. This is a possible over-abstention, with a rubric limitation: the packet does not precisely define what additional traceability proof is necessary. The scored difference must not be presented as a definitive scientific reasoning failure. A future evaluation should define this criterion prospectively.

No repair retry, JSON salvage or post-run rubric change was used. All responses and failure classifications are retained. An independent reviewer checked the durable reservations, final delivery classifications, thread identities and overlapping specialist timestamps. Per-turn process IDs are absent, so separate OS processes are implemented by the runtime but not independently attested by this report. This was not blinded prose adjudication.

## Per-case valid delivery times

| Case | Single | Parallel |
| --- | ---: | ---: |
| Duplicate diagnostic | 11.389 s | 13.452 s |
| Missing registered evidence | 8.244 s | 10.850 s |
| Missingness bound | 12.304 s | 9.122 s |
| Method/cohort confound | 13.897 s | 12.493 s |
| Threshold stability | 13.297 s | 14.364 s |
| Infeasible budget | 14.606 s | 12.636 s |
| Provenance conflict | Invalid | Invalid |
| Easy threshold | 15.216 s | 17.597 s |

## Reproduction and scope

See the [prospective protocol](../../RESEARCH_DECISION_TEST_PLAN.md). The exact run ID is `parallel-selftest-20261006T035321Z-e387bde1`; implementation was frozen at `ad04f65`. [report.json](report.json) contains raw model responses, role inputs, thread/session identities, timings, grade results and source hashes. [events.jsonl](events.jsonl) contains durable dispatch reservations and terminal events. All 16 arms reported verified cleanup; the launcher exited zero. Provider model identity, internal request count, token usage and billed cost remain unattested.

This small purposive synthetic pilot tests decisions on supplied evidence. It does not execute registered experiments, assess human rework, or benchmark the native scientific workflow. Public packets include already organized audit state, which reduces the remaining reasoning burden. There is one repetition per case, no confidence interval and no population superiority claim. Future tests should measure evidence acquisition and registration with the same tools for both arms, and include a strong single-agent baseline. The present result supports using simple policies or single-agent review for this tested workload, while treating conditional multi-agent review as an untested future option.

Integrity:

- Frozen manifest: `f8cd67f81060ddd3559fa68e75fa21f8524d8a4c150f7a49d5b2a45f7ffb6b39`
- Report SHA-256: `d8432f3b165ef9b8a5a40fbf123a91636b3b3c13d68ac9d02413381249b53a66`
- Events SHA-256: `720dcb74f4c379ef31fff3fc3c32a531812327610479406118ea56d07a8844a6`
