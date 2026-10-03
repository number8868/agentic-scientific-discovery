# Complete Luna live-run evidence

`luna-pilot-07` has a clean portable export in this directory. The SQLite live-evidence gate and the independent portable-export gate both pass: 13 ordered events, two discovery Results, two reviews, a frozen final protocol, and one closed holdout Spec. No holdout Result or outcome is present.

The requested route was `gpt-5.6-luna`. The audit records the requested model and SDK configuration, but it is not provider-attested evidence of the backend model identity.

The final Skeptic review contains a scientific language error: it calls the observed screening pass-rate difference a “missingness gap.” Missingness is a separate quantity in this study. The review must be preserved as emitted for provenance, but that wording must not be quoted or presented as a correct scientific interpretation.

The portable gate can be rerun with:

```text
python scripts/check_omnigent_luna_export.py docs/results/omnigent_complete_run
```
