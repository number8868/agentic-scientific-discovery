# H2 Databricks fixture handoff

This runbook prepares a local fixture database and prints the next command. It
does not contact Databricks and does not launch an external process.

1. Verify the user-selected Databricks profile first:

   ```bash
   databricks current-user me -p <profile>
   ```

2. Generate a local credential-free YAML copy using the profile setup described
   in `docs/DATABRICKS_SETUP.md`:

   ```bash
   export OMNIGENT_DATABRICKS_PROFILE=<profile>
   python scripts/check_omnigent_config.py --generate /tmp/nova-mat-databricks.yaml
   ```

3. Prepare the offline fixture run:

   ```bash
   python scripts/prepare_h2_fixture.py --db /tmp/nova-h2.sqlite --run-id h2-fixture-01
   ```

   The output includes the fixture run ID, canonical `family_screen` experiment
   ID, suggested `NOVA_RUN_DB`/`NOVA_RUN_ID`/`NOVA_MODE` values, and the next command. It never
   prints a token or workspace URL. The expected future bridge callable is
   `nova.omnigent_bridge.execute_fixture_registered_experiment`; the bridge is
   is wired into the tracked H2 fixture YAML.

4. Export the three printed environment values in the same shell, then run the
   generated local config with:

   ```bash
   omnigent run /tmp/nova-mat-databricks.yaml
   ```

## Success evidence

The preparation step is successful only when the SQLite database contains the
canonical spec and three `mode=fixture` events (`run_created`,
`hypothesis_frozen`, `selection`). H2 itself is successful only when the actual
function-tool result is recorded with the registered experiment ID and fixture
provenance. A model's text claiming it ran an experiment is not evidence.

Do not report Databricks connectivity, model output, or a live Result until the
function tool has actually returned a structured result and the run log has
been redacted of credentials and host details.
