# Paired OPT/MBJ Method Audit

Exploratory discovery-split screening audit on frozen JARVIS representatives. The report uses existing OPT/MBJ calculations and makes no new DFT or model calls.

## Three-arm comparison

Coverage is observed rows divided by all eligible rows. Observed pass rate uses only observed rows; missing property values remain unknown. The family delta is chalcogenide minus oxide for that arm.

| Arm | Family | Pass / observed | Eligible | Coverage | Observed rate | Family delta (percentage points) | 95% resampling interval (pp) | Status | Quality flags |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| opt_all | oxide | 3/7657 | 7657 | 100% | 0.039179835% | 0.150813831 pp | [0.011091442 pp, 0.322201832 pp] | supported_in_snapshot | chalcogenide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": true, "minimum_evaluable_count_pass": true}; endpoint_non_degenerate=true; interval_contains_zero=false; minimum_sample_and_coverage_pass=true; oxide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": true, "minimum_evaluable_count_pass": true}; paired_scope_conditional_only=false |
| opt_all | chalcogenide | 6/3158 | 3158 | 100% | 0.189993667% | 0.150813831 pp | [0.011091442 pp, 0.322201832 pp] | supported_in_snapshot | chalcogenide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": true, "minimum_evaluable_count_pass": true}; endpoint_non_degenerate=true; interval_contains_zero=false; minimum_sample_and_coverage_pass=true; oxide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": true, "minimum_evaluable_count_pass": true}; paired_scope_conditional_only=false |
| opt_paired | oxide | 1/1230 | 7657 | 16.063732532% | 0.081300813% | 0.167455406 pp | [-0.162601626 pp, 0.621890547 pp] | inconclusive | chalcogenide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": null, "minimum_evaluable_count_pass": true}; endpoint_non_degenerate=true; interval_contains_zero=true; minimum_sample_and_coverage_pass=true; oxide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": null, "minimum_evaluable_count_pass": true}; paired_scope_conditional_only=true |
| opt_paired | chalcogenide | 2/804 | 3158 | 25.459151362% | 0.248756219% | 0.167455406 pp | [-0.162601626 pp, 0.621890547 pp] | inconclusive | chalcogenide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": null, "minimum_evaluable_count_pass": true}; endpoint_non_degenerate=true; interval_contains_zero=true; minimum_sample_and_coverage_pass=true; oxide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": null, "minimum_evaluable_count_pass": true}; paired_scope_conditional_only=true |
| mbj_paired | oxide | 0/1230 | 7657 | 16.063732532% | 0% | 1.243781095 pp | [0.497512438 pp, 2.114427861 pp] | inconclusive | chalcogenide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": null, "minimum_evaluable_count_pass": true}; endpoint_non_degenerate=false; interval_contains_zero=false; minimum_sample_and_coverage_pass=true; oxide={"endpoint_has_pass_and_fail": false, "minimum_coverage_pass": null, "minimum_evaluable_count_pass": true}; paired_scope_conditional_only=true |
| mbj_paired | chalcogenide | 10/804 | 3158 | 25.459151362% | 1.243781095% | 1.243781095 pp | [0.497512438 pp, 2.114427861 pp] | inconclusive | chalcogenide={"endpoint_has_pass_and_fail": true, "minimum_coverage_pass": null, "minimum_evaluable_count_pass": true}; endpoint_non_degenerate=false; interval_contains_zero=false; minimum_sample_and_coverage_pass=true; oxide={"endpoint_has_pass_and_fail": false, "minimum_coverage_pass": null, "minimum_evaluable_count_pass": true}; paired_scope_conditional_only=true |

`opt_all` describes every evaluable OPT row; `opt_paired` and `mbj_paired` describe the same rows with both methods available. The `opt_paired` minus `opt_all` difference is a descriptive subset shift and has no causal interpretation. The paired comparison is conditional on paired rows; low paired coverage limits generalization to all eligible representatives.

### Descriptive OPT subset shift

| Family | OPT paired minus OPT all (percentage points) |
| --- | --- |
| oxide | 0.042120978 pp |
| chalcogenide | 0.058762552 pp |

The subset shift reflects selection into paired-data availability. It is shown separately from the within-row paired method change and should not be read as a causal effect.

## Paired method changes

A gained row passes MBJ and fails OPT; a lost row passes OPT and fails MBJ. Mean change is MBJ pass minus OPT pass on identical JIDs. Intervals describe this snapshot, not replication or experimental validation.

| Family | Paired n | OPT passes | MBJ passes | Gained | Lost | Mean change (pp) | 95% resampling interval (pp) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| oxide | 1230 | 1 | 0 | 0 | 1 | -0.081300813 pp | [-0.243902439 pp, 0 pp] |
| chalcogenide | 804 | 2 | 10 | 10 | 2 | 0.995024876 pp | [0.248756219 pp, 1.865671642 pp] |

| Across-family contrast | Change (pp) | 95% resampling interval (pp) | Status | Quality flags |
| --- | --- | --- | --- | --- |
| chalcogenide − oxide paired change | 1.076325689 pp | [0.248756219 pp, 1.985317316 pp] | direction_positive | chalcogenide={"minimum_paired_rows_pass": true, "paired_differences_constant": false}; coverage_limits_generalization_to_all_eligible=true; interval_contains_zero=false; minimum_paired_rows_pass=true; oxide={"minimum_paired_rows_pass": true, "paired_differences_constant": false}; paired_differences_nonconstant=true |

## Paired pass transitions

| Family | Pass → pass | Pass → fail | Fail → pass | Fail → fail |
| --- | --- | --- | --- | --- |
| oxide | 0 | 1 | 0 | 1229 |
| chalcogenide | 0 | 2 | 10 | 792 |

## Candidate evidence list

Shortlisted 19 of 10815 eligible rows. The local full-row audit is in `audit_rows.csv`; this table contains only rows marked `shortlisted=true`.

| Family | JID | Reduced formula | OPT gap (eV) | MBJ gap (eV) | Ehull (eV/atom) | OPT | MBJ | Candidate label | Reason | Next validation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| chalcogenide | JVASP-107267 | Zn2TeSe | 0.385 | 1.684 | 0 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-120874 | BaZnSe | 1.709 | Unknown | 0.03 | pass | unknown | opt_pass_mbj_unknown | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap unavailable or non-finite; ehull within 0.05 eV/atom limit | Obtain the missing calculation for the same representative before a cross-method claim. |
| chalcogenide | JVASP-121313 | Rb3AuS | 1.243 | 2.55 | 0 | pass | fail | opt_only | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap above 1.8 eV window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-142134 | K6ZnSe4 | 1.568 | Unknown | 0 | pass | unknown | opt_pass_mbj_unknown | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap unavailable or non-finite; ehull within 0.05 eV/atom limit | Obtain the missing calculation for the same representative before a cross-method claim. |
| chalcogenide | JVASP-14574 | ErSe | 0 | 1.378 | 0.04 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-14731 | HoSe | 0 | 1.379 | 0.0364 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-151736 | KSe | 0.739 | 1.799 | 0.041 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-183565 | Na3AuS | 1.776 | 1.864 | 0 | pass | fail | opt_only | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap above 1.8 eV window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-185703 | Zn2S | 0.992 | 1.442 | 0 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-19759 | TbSe | 0 | 1.348 | 0.0204 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-19778 | TbS | 0 | 1.727 | 0.0314 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-19781 | ErS | 0 | 1.661 | 0.0384 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-19966 | TmS | 0 | 1.655 | 0.0439 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| chalcogenide | JVASP-35260 | Na6ZnSe4 | 1.755 | Unknown | 0 | pass | unknown | opt_pass_mbj_unknown | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap unavailable or non-finite; ehull within 0.05 eV/atom limit | Obtain the missing calculation for the same representative before a cross-method claim. |
| chalcogenide | JVASP-35264 | Na2ZnSe2 | 1.793 | Unknown | 0.0179 | pass | unknown | opt_pass_mbj_unknown | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap unavailable or non-finite; ehull within 0.05 eV/atom limit | Obtain the missing calculation for the same representative before a cross-method claim. |
| chalcogenide | JVASP-99009 | EuS | 0 | 1.563 | 0.0478 | fail | pass | mbj_only | OPT: gap below 1.1 eV window; ehull within 0.05 eV/atom limit; MBJ: gap within inclusive frozen window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |
| oxide | JVASP-144275 | KCuO | 1.299 | Unknown | 0 | pass | unknown | opt_pass_mbj_unknown | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap unavailable or non-finite; ehull within 0.05 eV/atom limit | Obtain the missing calculation for the same representative before a cross-method claim. |
| oxide | JVASP-151826 | KAgO | 1.525 | Unknown | 0.0395 | pass | unknown | opt_pass_mbj_unknown | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap unavailable or non-finite; ehull within 0.05 eV/atom limit | Obtain the missing calculation for the same representative before a cross-method claim. |
| oxide | JVASP-50168 | KRbO | 1.794 | 4.156 | 0 | pass | fail | opt_only | OPT: gap within inclusive frozen window; ehull within 0.05 eV/atom limit; MBJ: gap above 1.8 eV window; ehull within 0.05 eV/atom limit | Run a targeted method/convergence and structural-input check on the same JID. |

### Candidate label counts

| Label | All families |
| --- | --- |
| passes_both_methods | 0 |
| opt_only | 3 |
| mbj_only | 10 |
| opt_pass_mbj_unknown | 6 |
| mbj_pass_opt_unknown | 0 |
| neither_passes | 2021 |
| no_current_pass_incomplete_evidence | 8775 |
| insufficient_evidence | 0 |

| Label | Oxide | Chalcogenide |
| --- | --- | --- |
| passes_both_methods | 0 | 0 |
| opt_only | 1 | 2 |
| mbj_only | 0 | 10 |
| opt_pass_mbj_unknown | 2 | 4 |
| mbj_pass_opt_unknown | 0 | 0 |
| neither_passes | 1229 | 792 |
| no_current_pass_incomplete_evidence | 6425 | 2350 |
| insufficient_evidence | 0 | 0 |

## Interpretation limits

- This is an exploratory discovery-only extension. The holdout remains untouched.
- OPT and MBJ are computational screening methods; MBJ is not ground truth. Passing both is screen agreement, not validation.
- Candidate labels prioritize evidence status. They do not establish synthesizability, physical performance, or new-material discovery.
- Subset availability can change the observed composition mix. Paired estimates apply only to rows with both method values and valid stability data.
- The run is manually selected and uses no new model calls. No autonomous selection or speedup is claimed.

<details>
<summary>Run metadata, timing, and source hashes</summary>

| Field | Value |
| --- | --- |
| schema_version | 1 |
| template | method_sensitivity |
| execution_status | success |
| split | discovery |
| dataset_sha256 | f9e0a3309f0000d5de1ec9e49c93963109ea45e63f451103f8f6595d2eabf7f5 |
| parent_protocol_sha256 | 9497988f1f8443f66326fa66a976d7196e5671ad320a1cce8a638780a8fc64ac |
| protocol_sha256 | ef09b94e6eebec20974ae4d05647f718471880e44cecb0bbaee55f2c2d050b03 |
| representative_compositions_csv_sha256 | d7184816ea97e4daa860b1a93a387b56a82280d3758eb2f658fbfa7ab021fb50 |
| split_assignment_sha256 | 96c9c210f77698d47bfdb68f9b3ad65673766a879785a6c7d983d7ee3777a58c |
| started_at | 2026-10-04T00:14:21.635300+00:00 |
| finished_at | 2026-10-04T00:14:22.584616+00:00 |
| elapsed_seconds | 0.9493156 |
| interpretation_scope | Observed JARVIS representatives in the frozen discovery split; MBJ is a computational method, not ground truth. |
| selection_mode | human_selected |
| no_new_model_calls | true |
| timing_seconds.computation | 0.4384755 |
| timing_seconds.prepared_data_validation | 0.51027 |
| timing_seconds.protocol_validation | 0.0005328 |
| timing_seconds.total | 0.9493156 |
| source_sha256 | ac00178c36f9d017f2321b2cab64362dff54bbdb27d8134ecb10dc40882da60b |
| source_hashes.nova/data/pipeline.py | 944c23f9c7f8b8cb4d68c0e23c4e197181b33e39ffa352fcc3a9b22339f6be0a |
| source_hashes.nova/experiments/method_sensitivity.py | ac00178c36f9d017f2321b2cab64362dff54bbdb27d8134ecb10dc40882da60b |
| source_hashes.nova/statistics.py | cf5663ba26a3c5212493eb6c8b1445018dcb3e666a1520fe18eaa37c23e6597b |

</details>
