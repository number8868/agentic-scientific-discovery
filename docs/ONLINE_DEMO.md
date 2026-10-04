# NOVA-MAT online demo

The public demo is live at
[NOVA-MAT evidence replay](https://nova-mat-scientific-demo.hy75252882.chatgpt.site).
Use this URL for the competition's **working demo** field.

Visitors can start or pause the recorded native09 replay, select a workflow
stage or recorded actor, switch between discovery and controlled holdout
results at the three frozen thresholds, and inspect or download the aggregate
evidence and its lineage. The page uses a navy/teal visual system, an abstract
lattice, responsive layouts and reduced-motion support. JARVIS-DFT/NIST and
the source's CC BY 4.0 license are attributed in the footer.

This is a functioning browser-local explorer of an existing completed real
run. It does not launch another Omnigent session, science experiment or
holdout. Counts, intervals, classifications and registered identifiers retain
their exported values. Presentation values round to five decimals; the
downloadable JSON preserves their full values. No model credential, running
database or raw/prepared materials row is hosted.

## Verification and hosting

Sites production version 1 was published from isolated source commit
`0502755fdcf1e149b05bdc868c659657fff62ec1`. The deployment archive contains
only four reviewed assets and its hosting manifest. The website source is in
[web/demo](../web/demo/README.md); the exact checks and asset hashes are in
[online_validation.json](demo/online_validation.json).

A checked all six threshold/cohort aggregates, 26 event metadata records,
three Result mappings, parent/freeze links and source hashes. JavaScript
syntax, 20 static selector bindings, local HTTP serving and anonymous
production HTTP access pass. Published JavaScript, CSS and JSON byte-match
the reviewed files. Sites adds platform markup to the entry HTML.

Browser interaction and visual layout were not exercised: the installed
Tabbit launcher exited 69 before a browser task could start. Standard browser
request headers return HTTP 200 anonymously; the default Python urllib user
agent returned 403. That is a transport observation, not a browser test.

The isolated hosting checkout, archive, source credentials and preview server
remain outside Git. Frozen scientific source/dependency bytes and historical
results were preserved; no new science or model call was needed.
