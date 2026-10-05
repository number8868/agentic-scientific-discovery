# Quality decision-audit benchmark

`scripts/run_quality_benchmark.py` compares three bounded ways to make a
decision from the same visible case packet:

- `single_once`: one independent answer.
- `single_self_review`: an initial answer, same-role audit, and final answer;
  each is a fresh session and the next turn receives the prior structured
  output.
- `multi_role`: Planner, Skeptic, then PI, also in fresh sessions with prior
  structured output passed forward.

The two three-call arms have equal requested model, reasoning setting,
per-turn `max_tokens=1200` request, packet, no-tools policy, generic audit
instructions, and call budget. The pinned executor does not expose a verified
provider-side hard token cap, so 1200 is recorded as the requested limit, not a
guaranteed hard cap.
Role framing is the intended difference. The one-shot arm is a lower-cost
reference. There are at most six frozen cases, two repetitions, 84 requests,
45 seconds per call, four seconds reserved for bounded cleanup, and a 900
second wall-clock cap. Calls are never retried. The runner records the
pre-shuffled arm order (seed 1729), visible packet, prompt hashes, frozen
corpus digest, script digest, commit/environment metadata, raw sanitized
responses, per-turn usage when available, errors, and incremental checkpoints.

By default the runner is offline and writes a manifest with all planned groups
and arms. To run the model comparison, explicitly pass
`--enable-model-calls`. Output is always a new JSON file under `runs/`; existing
files are never overwritten. `--case-limit` is reserved for small test runs
and marks the report scope incomplete. A failed attempted arm scores zero in
the planned-group aggregate. An unstarted arm is explicitly marked and left
unscored, so missing work is not mistaken for an observed zero. Paired
summaries retain failed attempted pairs and identify unstarted unmatched rows.
Both whole-arm elapsed time and the sum of turn times are reported.

The rubric is held host-side: prompts receive only `visible_packet(case)` and
prior structured model outputs. Scoring reports the frozen rubric's numeric
quality score and exact pass. The primary comparison is multi-role minus
self-review, paired within case/repetition. Repeat-pair signs are descriptive;
inferential signs are computed on six case-mean deltas to avoid treating
repetitions as independent cases. A quality gain is considered established
only if the mean delta is positive, a case-cluster bootstrap 95% interval
excludes zero, and the exact two-sided casewise sign test has `p < 0.05`.
Otherwise the comparison is descriptive. No efficiency claim is made unless
paired elapsed-time reduction has an interval above zero and quality is
non-inferior within a predeclared 0.02 margin; score-per-second by itself is
not evidence.

This is a decision-audit benchmark, not the separate NOVA-MAT native workflow
benchmark. It measures neither native tool dispatch nor experiments,
scientific discovery quality, nor end-to-end speedup. Any results are limited
to this small fixed corpus and model configuration; they should not be
generalized as scientific-discovery speedup.

Example:

```sh
python scripts/run_quality_benchmark.py
python scripts/run_quality_benchmark.py --enable-model-calls
```
