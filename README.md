# Code and aggregate outputs

Daily pad count three months after robot-assisted radical prostatectomy predicts pad freedom at one year: a two-country cohort study.

The archive contains analysis code and aggregate outputs only. No patient-level rows, identifiers or source documents are included. The patient-level research database is restricted under institutional approvals and cannot be shared.

## Contents

- `scripts/`: Python analysis scripts, run in numeric order against the restricted research database.
  - `06_derive_observed_assessments.py`: assessment selection and pad-count classification.
  - `07_observed_status_estimates.py`: proportions, differences, alternative assessment rules and later windows.
  - `10_posthoc_twogroup_analyses.py`: adjusted models and exact-count and questionnaire restrictions.
  - `11_selection_followup_sensitivity.py`: follow-up opportunity, record availability and missing-outcome analyses.
  - `15_clinical_adjustment.py`: clinically adjusted, weighted, treatment-excluded and United States models.
  - `16_strengthening_analyses.py`: pad-count gradient, risk ratio and E-values, heterogeneity, prognostic value, record-availability weighting, bounds, EPIC agreement, outcome definitions and Firth refits.
  - `13_build_submission_package.py` and `14_package_privacy_scan.py`: package build and privacy scan.
  - `02`–`05`, `08` and `09`: supporting exploratory, estimator, reproduction and lineage scripts.
- `aggregate_outputs/`: aggregate evidence records written by the scripts (JSON), plus the field maps of the variables used (`VARIABLE_MAP.csv`, and `VARIABLE_MAP_CLINICAL_ADJUSTMENT.csv` and `VARIABLE_MAP_STRENGTHENING.csv` for the added analyses).
- `display_code/`: R and Python code that draws the figures and tables from the aggregate outputs.

## Environment

Python 3.14.3 with pandas 2.3.3, NumPy 2.5.2, statsmodels 0.14.6 and DuckDB 1.5.5. R 4.6.1 with ggplot2 4.0.3 and patchwork.

## Reproduction

With access to the restricted database, run each analysis script from the manuscript workspace root, for example `python -B scripts/11_selection_followup_sensitivity.py --verify`. Each script checks its input hashes, fails when calibration counts do not reproduce, and in `--verify` mode recomputes its aggregate record without writing it. Figures and tables can be rebuilt from `aggregate_outputs/` alone. The display code expects the paths set at the top of each file.

## Citation and licence

This repository accompanies the manuscript named above, submitted to European Urology Open Science. Cite the published article once available. Code is released under the MIT licence (see `LICENSE`). Aggregate outputs may be reused with attribution to the article.
