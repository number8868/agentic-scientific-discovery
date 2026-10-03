# Databricks Omnigent live route

`agents/databricks-live.yaml` is the credential-free local configuration for
the B-owned live orchestration route. It uses the documented
`executor.auth.type: databricks` profile route and the repository-approved
`databricks-claude-sonnet-4-6` model. No token, workspace URL, or secret is
tracked.

The managed Omnigent UI is a separate route: it uses the session owner's
managed connection and does not consume this local profile field. Do not copy
managed connection details into the repository YAML.

Run the offline preflight before requesting a run:

```text
python scripts/check_databricks_live_config.py
```

It fails closed unless the local Databricks CLI, the named profile in the
user's `databrickscfg`, an executable Omnigent CLI, and the host-owned frozen
`data/manifest.json` plus `data/protocol.json` are present. The check never
contacts Databricks or Omnigent and never prints credential values. Set
`DATABRICKS_CONFIG_FILE`, `OMNIGENT_BIN`, or `NOVA_SCIENCE_DATA_ROOT` only in
the invoking environment when the defaults do not apply.

A failed preflight is an environment block, not evidence that the scientific
workflow ran.

The live configuration stops after the second discovery result: Skeptic records
`submit_final_review`, then PI calls `freeze_final`. It returns only the frozen
protocol identifier and `holdout_experiment_id`; it does not run the holdout,
because a controlled holdout Runner interface is not available yet.
