# Databricks route setup

`agents/databricks.yaml` is a tracked, credential-free Omnigent agent spec. It
uses the official `executor.auth.type: databricks` route and a named profile.
The profile is resolved by the user's Omnigent/Databricks configuration; the
repository does not contain a token, workspace URL, or profile secret.

This file targets the open-source/local Omnigent CLI with model calls routed
through Databricks. Databricks managed Omnigent is a separate execution route:
its workspace UI, repository attachment, custom Python callable availability,
and policy support must be checked in the actual hackathon workspace. Do not
claim that this local YAML has run in the managed service until that check is
recorded.

## Local preparation

1. Install and authenticate the Databricks CLI using your organization's normal
   method, or configure the profile consumed by Omnigent. Do not put a token in
   this repository.
2. Set `OMNIGENT_DATABRICKS_PROFILE` to the configured profile name.
3. Generate a local copy outside the tracked tree (the script defaults to
   `/tmp`):

```bash
export OMNIGENT_DATABRICKS_PROFILE=oss
python scripts/check_omnigent_config.py --generate /tmp/nova-mat-databricks.yaml
python scripts/check_omnigent_config.py /tmp/nova-mat-databricks.yaml
```

The generated file only changes the profile name. Keep it local and remove it
after testing; credentials remain in the user's CLI/Omnigent configuration.

## H2 validation procedure

The repository has not run Databricks or claimed a successful provider call.
After access is available, run the actual Omnigent CLI with the generated file,
capture the CLI version, exit code, selected profile (name only), model route,
and the tool-call record showing Runner called
`nova.tools.execute_registered_experiment` with only a registered ID. Confirm
that Planner exposes two proposals, Skeptic has no execution tool, and fixture
and live provenance remain distinct.

For the managed route, create a Sandbox session in the Databricks Omnigent UI,
attach or upload this repository using the supported workspace mechanism, and
first invoke a harmless registered fixture ID. If the managed environment
cannot import `nova.tools`, stop and fix packaging/import availability; do not
replace the tool call with a natural-language claim. Confirm whether custom
YAML policies are supported by that workspace before relying on the checked-in
policy as enforcement.

Success evidence is a redacted run log plus structured Result/event records;
never include tokens, workspace URLs, or raw authorization headers. A model
response alone is not sufficient evidence of the root-to-sub-agent-to-function
handoff.
