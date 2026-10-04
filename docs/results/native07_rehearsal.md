# Native07 discovery/finalization rehearsal

Source: main `433bdf5`; run `native-adaptive-live-07`.
Original native launcher exited 0 after approximately 195 seconds under its
600-second deadline. Six executor PIDs completed ten model turns. The
host-seeded primary and actual native threshold follow-up completed, followed
by final Skeptic review and PI freeze. Exact PI response and trace verification
passed. Holdout execution was not enabled and remains unexecuted.

Follow-up Spec: `NOVA-e6352c874d8aa73f`.
Result: `nova-result-62cf44fcdd171847402e8e062cf03ed5aa0985305ebec01715be02de735238dc`.
Final protocol: `NOVA-FINAL-c802129f7cd9b983`.
Registered unexecuted holdout: `NOVA-HOLDOUT-0746f8316498b20c`.

The first freeze explanation exceeded the host's 500-character bound. A
shortened explanation succeeded in the same bounded workflow. This is not
an error-free/no-repair rehearsal, and not final holdout acceptance.
Private SQLite, native audit, exact PI response and sanitized scientific
export are retained locally under `runs/native-adaptive-live-07/`.

Independent source review found that the separate holdout PI prompt omitted
explicit async completion-notice/inbox instructions. This is a prompt-contract
gap, not an established explanation for teammate A's earlier failure: A
reported no freeze or holdout claim, so that attempt never reached this stage.
