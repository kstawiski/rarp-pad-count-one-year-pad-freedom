# Code and aggregate outputs

Daily pad count three months after robot-assisted radical prostatectomy and pad freedom at one year.

This repository holds analysis code and aggregate outputs only. It contains no patient-level rows, identifiers or source documents. The patient-level research database is restricted under institutional approvals and cannot be shared.

## Contents

- `scripts/`: Python analysis scripts, run against the restricted research database.
  - `cohort.py`: the study cohort rule. A man enters the study cohort when postoperative day 425, the last day of the one-year assessment window, fell before 1 April 2026 (`--cohort completed_window`, the default). The option `--cohort all_operations` keeps every operation and serves the sensitivity analysis that adds later operations.
  - `06_derive_observed_assessments.py`: assessment selection and pad-count classification.
  - `07_observed_status_estimates.py`: proportions, differences, alternative assessment rules and later windows.
  - `10_posthoc_twogroup_analyses.py`: adjusted models and the exact-count and questionnaire restrictions.
  - `11_selection_followup_sensitivity.py`: record availability and missing-outcome analyses.
  - `15_clinical_adjustment.py`: clinically adjusted, weighted, treatment-excluded and United States models.
  - `16_strengthening_analyses.py`: pad-count gradient, risk ratio and E-values, heterogeneity between countries, prognostic value, weighting for record availability, alternative assignments of unclear counts, questionnaire agreement, outcome definitions and Firth refits.
  - `18_one_year_pad_category.py`: pad use at one year (pad-free, at most one pad per day, more than one pad per day) by pad count at three months, by country and by six-month status.
  - `19_documentation_and_timing.py`: what the records held in each assessment window, recording of safety pads and diapers, pad freedom by day of the three-month assessment, the lowest and highest difference over all assignments of unclear counts, and use of more than one pad per day at one year when one-year records are missing.
  - `run_cohort_rebase.sh`: runs the scripts in order, to record or to verify the aggregate records.
  - `02`–`05`, `08`, `09` and `14`: supporting exploratory, estimator, reproduction, lineage and privacy-scan scripts.
- `aggregate_outputs/`: aggregate records written by the scripts (JSON). The records describe the study cohort, and the sensitivity analysis that adds later operations is stored inside them. `COHORT_GATES.json` holds the counts each script must reproduce before it writes a record. `VARIABLE_MAP*.csv` list the database fields used.
- `display_code/`: R and Python code that draws the figures and tables from the aggregate outputs. `build_manuscript_tables.py` writes the tables of the article and its supporting information from the same records, with the Wilson score intervals of Table 2; it reads the manuscript text, which is not part of this repository.

## Environment

Python 3.14.10 with pandas 3.1.1, NumPy 2.5.5, statsmodels 0.15.0, SciPy 1.18.1 and DuckDB 2.0.1. R 4.6.1 with ggplot2 4.0.4.

## Reproduction

With access to the restricted database, run each analysis script from the manuscript workspace root, for example `python -B scripts/19_documentation_and_timing.py --cohort completed_window --verify`. Each script checks its input hashes, stops when its calibration counts do not reproduce, and in `--verify` mode recomputes its aggregate record and compares it with the saved one without writing. Figures and tables can be rebuilt from `aggregate_outputs/` alone. The display code expects the paths set at the top of each file.

## Citation and licence

This repository accompanies the manuscript named above. Cite the published article once it is available. Code is released under the MIT licence (see `LICENSE`). Aggregate outputs may be reused with attribution to the article.
