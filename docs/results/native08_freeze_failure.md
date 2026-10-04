# Native08: final explanation validation failure

Source: `21926d6`; run `native-adaptive-live-08`; original native CLI exit 1.
Actual primary and threshold follow-up Results completed, and final Skeptic
review was recorded. PI's freeze explanation exceeded the unchanged 500-character
host limit. The prompt said to freeze once, so PI declined a schema correction
and ended without a successful freeze. The launcher then reported missing final
PI response evidence, which is a downstream symptom, not the originating error.

Failure feedback confirms `final_protocol_frozen=false`, last confirmed stage
`final_review_submitted`, and no observed holdout execution event. No frozen
protocol or holdout attempt is claimed. The failed run, SQLite, audit and private
terminal capture remain preserved under `runs/native-adaptive-live-08/`.

Follow-up Result:
`nova-result-d9c7c4fc3eafe8a08bad14a7023db6f543718c62080aa619a46f972c0edbb579`.

This failure motivates explicit short-text prompt limits and one narrowly scoped
argument-length correction only before successful freeze. It does not justify
changing numerical criteria, retrying a holdout, reopening this run or claiming
the unknown cause of A's separate early failure has been established.
