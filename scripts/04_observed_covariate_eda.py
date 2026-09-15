#!/usr/bin/env python3
"""Aggregate covariate EDA and model-feasibility screening for observed-pair analyses.

Preparation only. No clinical probability, interval, hypothesis test, regression fit,
outcome imputation, weighting or bound. Candidate selections are imported from the
accepted scripts and never redefined here. Impact flags mark where judgment is needed
and are never applied as exclusions.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import math
import sys
import warnings
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
WORKSPACE = HERE.parent
OUTPUT = HERE / 'evidence/OBSERVED_COVARIATE_EDA.json'
TEST_SCRIPT = HERE / 'tests/test_04_observed_covariate_eda.py'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


eda = module('covariate_eda_base', '02_eda_authoritative.py')
impact = module('covariate_impact_base', '03_conflict_impact.py')
ID = eda.ID
RELEASE = eda.RELEASE
COUNTRIES = ('Poland', 'United States')
BURDEN_LEVELS = ('one', 'two_or_more', 'quantity_uncertain')
KNOWN_BURDEN = ('one', 'two_or_more')
# Adult surgical plausibility screens. Flags only. No automatic exclusion is applied.
AGE_VALID_RANGE = (18.0, 100.0)
AGE_EXPECTED_RANGE = (30.0, 90.0)
# Accepted plan feasibility constants, restated so no gate result is hard coded.
MIN_PER_SLOPE = 10
MIN_PER_INTERACTION_CELL = 20
MIN_COUNTRY_PAIRS = 30
AGE_COMPLETE_CASE_LIMIT = 0.05
CANONICAL_LADDER = {'all_released': 1497, 'robotic': 1397, 'valid_dated_postoperative_continence': 5376,
                    'early_status_known': 644, 'early_users': 460, 'paired_early_year': 309,
                    'early_users_with_year': 226, 'year_padfree_observed_pairs': 86}
ALLOWLISTED_COLUMNS = {
    'patient_wide': ('master_patient_id', 'age', 'country', 'robotic_platform_used', 'surgery_date'),
    'continence_events_long': ('master_patient_id', 'event_index', 'country', 'surgery_date', 'event_date',
                               'days_from_surgery', 'event_phase', 'pad_free', 'pads_per_day',
                               'pads_per_day_min', 'pads_per_day_max', 'diaper_count_min', 'diaper_count_max',
                               'safety_pad_documented', 'usable_continence_observation',
                               'event_date_ambiguous', 'event_date_precision_source_derived'),
    'proms_long': ('master_patient_id', 'days_from_surgery', 'event_phase', 'usable_prom_observation',
                   'urinary_incontinence_score', 'epic26_urinary_incontinence_score', 'ipss_qol'),
}
# Named dedicated urinary continence quality-of-life candidates. Erectile-function instruments
# are excluded by name and can never substitute for a continence measure.
CONTINENCE_QOL_COLUMNS = ('urinary_incontinence_score', 'epic26_urinary_incontinence_score', 'ipss_qol')
EXCLUDED_INSTRUMENT_COLUMNS = ('iief_ef_domain', 'shim', 'sexual_score', 'epic26_sexual_score')


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def read_allowlisted(root, table):
    require(table in ALLOWLISTED_COLUMNS, 'TABLE_NOT_ALLOWLISTED')
    header = pd.read_csv(root / 'tables' / (table + '.csv'), dtype=str, nrows=0)
    wanted = [c for c in ALLOWLISTED_COLUMNS[table] if c in header.columns]
    return pd.read_csv(root / 'tables' / (table + '.csv'), dtype=str, keep_default_na=False,
                       usecols=wanted), tuple(header.columns)


def header_projection(columns, wanted):
    """Metadata-only availability check. No source value is read to answer it."""
    return {name: bool(name in columns) for name in wanted}


def age_summary(series):
    """Missing, nonnumeric and out-of-range evidence stay separate. Flags never exclude."""
    base = eda.stats(series)
    x = eda.numeric(series)
    finite = x.notna() & x.map(math.isfinite)
    y = x[finite].astype(float)
    lo, hi = AGE_VALID_RANGE
    elo, ehi = AGE_EXPECTED_RANGE
    out = dict(base)
    out['implausible_outside_18_to_100'] = int(((y < lo) | (y > hi)).sum())
    out['outside_expected_adult_surgical_30_to_90'] = int(((y < elo) | (y > ehi)).sum())
    out['nonmissing_but_unusable_for_a_numeric_covariate'] = int(base['nonnumeric_nonblank'] + base['nonfinite'])
    if not y.empty:
        q1, q3 = y.quantile([.25, .75])
        iqr = q3 - q1
        flagged = y[(y < q1 - 1.5 * iqr) | (y > q3 + 1.5 * iqr)]
        out['iqr_flagged_value_range'] = ({'min': eda.rounded(flagged.min()), 'max': eda.rounded(flagged.max())}
                                          if len(flagged) else {'min': None, 'max': None})
        out['extreme_low_decile_threshold'] = eda.rounded(y.quantile(.10))
        out['extreme_high_decile_threshold'] = eda.rounded(y.quantile(.90))
    out['flag_semantics'] = 'diagnostic_counts_and_ranges_only_no_exclusion_applied'
    return out


def numeric_summary(series):
    """Deterministic numeric profile through the accepted statistic helper.

    Values are rendered as text so a missing value is counted as missing rather than
    as an unparseable token.
    """
    values = list(pd.Series(series))
    text = pd.Series(['' if pd.isna(v) else repr(float(v)) for v in values], dtype=object)
    return eda.stats(text)


def count_profile(counts, cap=5):
    """Assessment-count profile with a capped top bin. Aggregate only."""
    profile = {}
    for value in counts:
        key = str(int(value)) if int(value) < cap else f'{cap}_or_more'
        profile[key] = profile.get(key, 0) + 1
    ordered = sorted(profile, key=lambda k: (k.endswith('or_more'), int(k.split('_')[0])))
    return {k: int(profile[k]) for k in ordered}


def coarse_year_counts(series):
    """Coarse calendar year only. No exact date is emitted and no coverage is inferred."""
    parsed = eda.dates(series)
    years = parsed.dt.year.dropna().astype(int)
    counts = years.value_counts().sort_index()
    return {'known_year': int(len(years)), 'missing_or_unparseable_date': int(len(series) - len(years)),
            'min_year': int(years.min()) if len(years) else None,
            'max_year': int(years.max()) if len(years) else None,
            'by_year': {str(int(k)): int(v) for k, v in counts.items()}}


def gate(key, label, events, nonevents, slope_df, minimum, extra_failures=()):
    """Recomputed feasibility gate. Never assume a pass from an overall event count."""
    required = int(slope_df) * int(minimum)
    failures = list(extra_failures)
    if int(events) < required:
        failures.append(f'events_{int(events)}_below_required_{required}')
    if int(nonevents) < required:
        failures.append(f'nonevents_{int(nonevents)}_below_required_{required}')
    return {'key': key, 'label': label, 'slope_degrees_of_freedom': int(slope_df),
            'minimum_per_slope_degree_of_freedom': int(minimum), 'required_each_arm': required,
            'events': int(events), 'nonevents': int(nonevents),
            'passes': not failures, 'failure_reasons': failures}


def design_matrix(frame):
    """Covariate-only candidate design matrices. No outcome or observation model is fitted."""
    age = eda.numeric(frame['_age'])
    columns = {
        'intercept': np.ones(len(frame)),
        'burden_two_or_more': frame['_burden'].eq('two_or_more').to_numpy(float),
        'burden_quantity_uncertain': frame['_burden'].eq('quantity_uncertain').to_numpy(float),
        'age_centred_65_per_10': ((age - 65.0) / 10.0).to_numpy(float),
        'country_united_states': frame['_country'].eq('United States').to_numpy(float),
    }
    return columns


def timing_columns(frame):
    return {'early_day_centred_90_per_30': ((eda.numeric(frame['_early_day']) - 90.0) / 30.0).to_numpy(float),
            'year_day_centred_365_per_30': ((eda.numeric(frame['_year_day']) - 365.0) / 30.0).to_numpy(float)}


def rank_diagnostics(columns):
    """Rank, conditioning and pairwise covariate correlation. No response variable is used."""
    names = list(columns)
    matrix = np.column_stack([columns[k] for k in names]) if names else np.zeros((0, 0))
    if matrix.size == 0 or not np.isfinite(matrix).all() or matrix.shape[0] == 0:
        return {'columns': names, 'rows': int(matrix.shape[0]) if matrix.ndim == 2 else 0,
                'full_column_rank': False, 'diagnostic_state': 'not_computable_empty_or_nonfinite'}
    rank = int(np.linalg.matrix_rank(matrix))
    singular = np.linalg.svd(matrix, compute_uv=False)
    smallest = float(singular[-1]) if singular.size else 0.0
    condition = float(singular[0] / smallest) if smallest > 0 else None
    zero_variance = [k for k in names if k != 'intercept' and float(np.std(columns[k])) == 0.0]
    correlations = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a == 'intercept' or b == 'intercept':
                continue
            sa, sb = float(np.std(columns[a])), float(np.std(columns[b]))
            correlations[f'{a}__{b}'] = (eda.rounded(float(np.corrcoef(columns[a], columns[b])[0, 1]))
                                         if sa > 0 and sb > 0 else None)
    strong = sorted(k for k, v in correlations.items() if v is not None and abs(v) >= 0.8)
    return {'columns': names, 'rows': int(matrix.shape[0]), 'column_count': len(names), 'rank': rank,
            'full_column_rank': rank == len(names),
            'condition_number': eda.rounded(condition) if condition is not None else None,
            'smallest_singular_value': eda.rounded(smallest),
            'zero_variance_columns': zero_variance, 'pairwise_correlations': correlations,
            'pairwise_absolute_correlation_at_least_0_8': strong,
            'diagnostic_state': 'covariate_structure_only_no_model_fitted'}


def cross_counts(frame, keys, levels):
    """Complete cross-tabulation over declared levels. Every cell is present, zeros included."""
    out, total = {}, 0
    for combination in _combinations(levels):
        mask = pd.Series(True, index=frame.index)
        for column, value in zip(keys, combination):
            mask &= frame[column].eq(value)
        n = int(mask.sum())
        out['|'.join(combination)] = n
        total += n
    out['declared_level_total'] = total
    out['rows_outside_declared_levels'] = int(len(frame) - total)
    return out


def _combinations(levels):
    if not levels:
        return [()]
    rest = _combinations(levels[1:])
    return [(value,) + tail for value in levels[0] for tail in rest]


def partition_counts(universe, named_sets):
    """Mutually exclusive bitmask accounting. No identity is lost or double counted."""
    names = list(named_sets)
    bins = {}
    for pid in universe:
        bit = ''.join('1' if pid in named_sets[name] else '0' for name in names)
        bins[bit] = bins.get(bit, 0) + 1
    require(sum(bins.values()) == len(set(universe)), 'PARTITION_FAILURE')
    return {'bit_order': names, 'patients': len(set(universe)),
            'bitmask_counts': {k: int(v) for k, v in sorted(bins.items())},
            'overlapping_reason_patients': {name: len(set(universe) & named_sets[name]) for name in names},
            'accounting_exact': True,
            'meaning': 'Flagged patients need judgment. No flag is an exclusion in this record.'}


def selection_frames(patients, events):
    """Import the accepted selection unchanged. This script never redefines a window rule."""
    d, masks, context, date_masks = impact.annotate(events, patients)
    robotic = set(patients.loc[eda.truth(patients.robotic_platform_used), ID])
    valid = d.loc[d._valid & d[ID].isin(robotic)].copy()
    candidate = valid.copy()
    candidate.loc[candidate._endpoint_bad, '_status'] = pd.NA
    selected = {k: eda.select_window(candidate, win)[0] for k, win in eda.WINDOWS.items()}
    return d, robotic, valid, candidate, selected, masks, context, date_masks


def cohort_sets(selected, robotic, patients, valid):
    early, year = selected['early'], selected['year']
    users = set(early.loc[early._status.eq(0), ID])
    pairs = set(early[ID]) & set(year[ID])
    pair_users = users & set(year[ID])
    free = pair_users & set(year.loc[year._status.eq(1), ID])
    return {'all_released': set(patients[ID]), 'robotic': robotic,
            'early_status_known': set(early[ID]), 'early_users': users,
            'paired_early_year': pairs, 'early_users_with_year': pair_users,
            'early_users_without_year': users - set(year[ID]),
            'year_padfree_observed_pairs': free}


def covariate_frame(patients, selected, cohorts):
    """One row per early pad user. Patient-level covariates joined by identity only."""
    early, year = selected['early'], selected['year']
    base = patients.loc[patients[ID].isin(cohorts['early_users'])].copy()
    early_index = early.set_index(ID)
    year_index = year.set_index(ID)
    base['_age'] = base.age
    base['_country'] = base.country
    base['_surgery_date'] = base.surgery_date
    base['_burden'] = base[ID].map(early_index._burden)
    base['_early_day'] = base[ID].map(early_index._day)
    base['_early_country_event'] = base[ID].map(early_index.country)
    base['_year_day'] = base[ID].map(year_index._day)
    observed = base[ID].isin(cohorts['early_users_with_year'])
    base['_observed_year'] = np.where(observed, 'observed_year_status', 'without_year_status')
    padfree = base[ID].isin(cohorts['year_padfree_observed_pairs'])
    base['_year_state'] = np.where(~observed, 'year_status_not_observed',
                                   np.where(padfree, 'year_pad_free', 'year_pad_use'))
    return base.sort_values(ID, kind='stable').reset_index(drop=True)


def age_blocks(patients, cohorts, covariates):
    """Age evidence by every requested stratum. Denominators are stated with each block."""
    robotic = patients.loc[patients[ID].isin(cohorts['robotic'])]
    blocks = {
        'all_robotic': age_summary(robotic.age),
        'early_status_selected': age_summary(patients.loc[patients[ID].isin(cohorts['early_status_known'])].age),
        'early_pad_users': age_summary(patients.loc[patients[ID].isin(cohorts['early_users'])].age),
        'observed_pairs': age_summary(patients.loc[patients[ID].isin(cohorts['early_users_with_year'])].age),
        'early_users_without_year_status': age_summary(patients.loc[patients[ID].isin(cohorts['early_users_without_year'])].age),
    }
    by_country = {}
    for country in COUNTRIES:
        by_country[country] = {
            'all_robotic': age_summary(robotic.loc[robotic.country.eq(country)].age),
            'early_pad_users': age_summary(covariates.loc[covariates._country.eq(country)].age),
            'observed_pairs': age_summary(covariates.loc[covariates._country.eq(country)
                                                         & covariates._observed_year.eq('observed_year_status')].age),
        }
    by_country['other_or_missing_country_all_robotic'] = age_summary(robotic.loc[~robotic.country.isin(COUNTRIES)].age)
    by_burden = {}
    for level in BURDEN_LEVELS:
        rows = covariates.loc[covariates._burden.eq(level)]
        by_burden[level] = {
            'early_pad_users': age_summary(rows.age),
            'observed_pairs': age_summary(rows.loc[rows._observed_year.eq('observed_year_status')].age),
        }
    blocks['by_country'] = by_country
    blocks['by_baseline_early_burden'] = by_burden
    return blocks


def burden_country_block(covariates, selected, cohorts, direct, impacts):
    """Burden and country evidence, then target-specific diagnostic flags kept separate."""
    observed = covariates.loc[covariates._observed_year.eq('observed_year_status')].copy()
    cells = cross_counts(observed, ['_country', '_burden', '_year_state'],
                         [COUNTRIES, BURDEN_LEVELS, ('year_pad_free', 'year_pad_use')])
    users_cells = cross_counts(covariates, ['_country', '_burden', '_observed_year'],
                               [COUNTRIES, BURDEN_LEVELS, ('observed_year_status', 'without_year_status')])
    early = selected['early']
    context_masks = impact.row_masks(early)[1]
    quantity_evidence = {}
    for name, members in (('early_users', cohorts['early_users']),
                          ('early_users_with_year', cohorts['early_users_with_year'])):
        eligible = early[ID].isin(members)
        quantity_evidence[name] = {
            'patients': int(eligible.sum()),
            'known_ordinary_quantity_both_bounds': int((eligible & ~context_masks['D3_at_least_one_bound_missing']).sum()),
            'at_least_one_bound_missing': int((eligible & context_masks['D3_at_least_one_bound_missing']).sum()),
            'no_numeric_ordinary_evidence': int((eligible & context_masks['D3_no_numeric_ordinary_evidence']).sum()),
            'interval_spans_one_and_two': int((eligible & context_masks['D3_range_spans_one_and_two']).sum()),
            'lower_bound_point_fallback_used': int((eligible & context_masks['D3_lower_fallback_used']).sum()),
            'upper_bound_point_fallback_used': int((eligible & context_masks['D3_upper_fallback_used']).sum()),
            'diaper_documented_not_an_ordinary_pad_quantity': int((eligible & context_masks['D2_positive_diaper']).sum()),
            'safety_pad_documented_not_an_ordinary_pad_quantity': int((eligible & context_masks['D2_safety_pad_true']).sum()),
        }
    flags = {}
    for scope, source in (('selected_day_fields_with_window_date_uncertainty', direct),
                          ('any_valid_day_in_target_window', impacts)):
        status = source['early']['status'] | source['year']['status']
        burden_flag = source['early']['burden']
        date_flag = source['early']['date'] | source['year']['date']
        numeric_fact = source['early']['numeric_fact']
        named = {'target_status_conflict_or_endpoint': status,
                 'early_burden_category_changing_or_invalid_quantity': burden_flag,
                 'date_selection_uncertainty': date_flag}
        flags[scope] = {
            'partitions': {name: partition_counts(cohorts[name], named)
                           for name in ('early_users', 'early_users_with_year', 'year_padfree_observed_pairs')},
            'numeric_fact_discordance_not_category_changing': {
                name: len(cohorts[name] & (numeric_fact - burden_flag))
                for name in ('early_users', 'early_users_with_year')},
            'by_country_and_burden': {
                f'{country}|{level}': {
                    reason: len(set(observed.loc[observed._country.eq(country) & observed._burden.eq(level), ID]) & ids)
                    for reason, ids in named.items()}
                for country in COUNTRIES for level in BURDEN_LEVELS},
        }
    return {'observed_pair_country_burden_year_state_cells': cells,
            'early_user_country_burden_observation_cells': users_cells,
            'ordinary_pad_quantity_evidence_on_selected_early_day': quantity_evidence,
            'target_specific_diagnostic_flags': flags,
            'country_field_agreement': {
                'patient_and_event_country_agree': int(covariates._country.eq(covariates._early_country_event).sum()),
                'patient_and_event_country_differ': int((covariates._country.ne(covariates._early_country_event)
                                                         & covariates._early_country_event.notna()).sum()),
                'event_country_unavailable': int(covariates._early_country_event.isna().sum())},
            'semantics': ('Quantity uncertainty is missing or interval evidence, not a contradiction. '
                          'The preserved event-index burden inventory is provisional, not an adjudicated exposure.')}


def timing_block(candidate, selected, covariates, cohorts, patients):
    """Timing, repetition and coarse calendar structure. No exact date is emitted."""
    early, year = selected['early'], selected['year']
    observed = covariates.loc[covariates._observed_year.eq('observed_year_status')].copy()
    gap = eda.numeric(observed._year_day) - eda.numeric(observed._early_day)
    per_patient = candidate.groupby(ID).size()
    known_per_patient = candidate.loc[candidate._status.notna()].groupby(ID).size()
    lo_e, hi_e, _ = eda.WINDOWS['early']
    lo_y, hi_y, _ = eda.WINDOWS['year']
    early_users_frame = early.loc[early[ID].isin(cohorts['early_users'])]
    year_frame = year.loc[year[ID].isin(cohorts['early_users_with_year'])]
    surgery_by_country = {}
    for country in COUNTRIES:
        ids = set(patients.loc[patients.country.eq(country), ID]) & cohorts['early_users']
        surgery_by_country[country] = coarse_year_counts(covariates.loc[covariates[ID].isin(ids), '_surgery_date'])
    surgery_by_observation = {
        state: coarse_year_counts(covariates.loc[covariates._observed_year.eq(state), '_surgery_date'])
        for state in ('observed_year_status', 'without_year_status')}
    return {
        'selected_assessment_days': {
            'early_selected_all_known_status': numeric_summary(early._day),
            'early_selected_pad_users': numeric_summary(early_users_frame._day),
            'year_selected_in_observed_pairs': numeric_summary(year_frame._day),
        },
        'paired_assessment_gap_days_observed_pairs': numeric_summary(gap),
        'implausibility_screens': {
            'early_selected_day_outside_declared_window': int((~eda.numeric(early._day).between(lo_e, hi_e)).sum()),
            'year_selected_day_outside_declared_window': int((~eda.numeric(year._day).between(lo_y, hi_y)).sum()),
            'observed_pairs_with_nonpositive_gap': int((gap <= 0).sum()),
            'observed_pairs_with_gap_below_150_days': int((gap < 150).sum()),
            'observed_pairs_with_missing_gap': int(gap.isna().sum()),
            'meaning': 'Screens describe distribution shape only. No observation is removed.'},
        'repeated_assessment_structure': {
            'candidate_valid_rows': int(len(candidate)),
            'patients_with_candidate_valid_rows': int(candidate[ID].nunique()),
            'candidate_rows_per_patient': numeric_summary(per_patient),
            'candidate_rows_per_patient_profile': count_profile(per_patient.values),
            'known_status_rows_per_patient_profile': count_profile(known_per_patient.values),
            'same_day_all_candidate_valid': eda.same_day_summary(candidate),
            'same_day_early_window': eda.same_day_summary(candidate.loc[candidate._day.between(lo_e, hi_e)]),
            'same_day_year_window': eda.same_day_summary(candidate.loc[candidate._day.between(lo_y, hi_y)])},
        'denominator_drift': {
            'early_status_known': len(cohorts['early_status_known']),
            'early_users': len(cohorts['early_users']),
            'early_users_with_year': len(cohorts['early_users_with_year']),
            'early_users_without_year': len(cohorts['early_users_without_year']),
            'early_users_with_usable_numeric_age': int(eda.numeric(covariates.age).notna().sum()),
            'observed_pairs_with_usable_numeric_age': int(eda.numeric(observed.age).notna().sum()),
            'observed_pairs_with_known_burden_and_usable_age': int(
                (observed._burden.isin(KNOWN_BURDEN) & eda.numeric(observed.age).notna()).sum()),
            'observed_pairs_with_declared_country': int(observed._country.isin(COUNTRIES).sum())},
        'coarse_surgery_calendar_year': {
            'early_users_all': coarse_year_counts(covariates._surgery_date),
            'by_country': surgery_by_country,
            'by_year_observation_state': surgery_by_observation,
            'meaning': ('Coarse year counts describe calendar composition of the candidate set. '
                        'They do not establish administrative observation coverage or a close date.')},
    }


def finite_numeric(series):
    return eda.numeric(series).replace([np.inf, -np.inf], np.nan)


def support_failures(frame):
    """Recompute cell and country support on the actual proposed model subset."""
    failures = []
    for country in COUNTRIES:
        n = int(frame._country.eq(country).sum())
        if n < MIN_COUNTRY_PAIRS:
            failures.append(f'country_{country.replace(" ", "_").lower()}_pairs_{n}_below_{MIN_COUNTRY_PAIRS}')
    for level in BURDEN_LEVELS:
        for outcome in ('year_pad_free', 'year_pad_use'):
            if not (frame._burden.eq(level) & frame._year_state.eq(outcome)).any():
                failures.append(f'empty_outcome_by_burden_cell_{level}|{outcome}')
    if (~frame._country.isin(COUNTRIES)).any():
        failures.append('country_outside_declared_model_levels')
    if (~frame._burden.isin(BURDEN_LEVELS)).any():
        failures.append('burden_outside_declared_model_levels')
    return failures


def feasibility_block(covariates):
    """Every gate is recomputed from present counts. Failed gates are preserved with reasons."""
    observed = covariates.loc[covariates._observed_year.eq('observed_year_status')].copy()
    events_mask = observed._year_state.eq('year_pad_free')
    age_usable = finite_numeric(observed.age).notna()
    country_usable = observed._country.isin(COUNTRIES)
    complete = observed.loc[age_usable & country_usable]
    gates, matrices = [], {}
    country_pairs = {c: int(observed._country.eq(c).sum()) for c in COUNTRIES}
    outcome_burden = cross_counts(observed, ['_burden', '_year_state'],
                                  [BURDEN_LEVELS, ('year_pad_free', 'year_pad_use')])
    empty_cells = sorted(k for k, v in outcome_burden.items()
                         if k not in ('declared_level_total', 'rows_outside_declared_levels') and v == 0)
    gates.append(gate('four_slope_all_observed_pairs',
                      'Burden two levels, age, country. Accepted plan slope, cell and country rules.',
                      int(events_mask.sum()), int((~events_mask).sum()), 4, MIN_PER_SLOPE,
                      support_failures(observed)))
    complete_events = complete._year_state.eq('year_pad_free')
    gates.append(gate('four_slope_age_complete_case',
                      'Same model on the age-complete denominator, with plan cell and country rules.',
                      int(complete_events.sum()), int((~complete_events).sum()), 4, MIN_PER_SLOPE,
                      support_failures(complete)))
    timing_usable = age_usable & country_usable & finite_numeric(observed._early_day).notna() & finite_numeric(observed._year_day).notna()
    timing = observed.loc[timing_usable]
    timing_events = timing._year_state.eq('year_pad_free')
    gates.append(gate('six_slope_timing_sensitivity',
                      'Adds early and year assessment day. Must pass the same rule independently.',
                      int(timing_events.sum()), int((~timing_events).sum()), 6, MIN_PER_SLOPE,
                      support_failures(timing)))
    interaction_cells = {}
    interaction_failures = []
    for country in COUNTRIES:
        for level in KNOWN_BURDEN:
            rows = observed.loc[observed._country.eq(country) & observed._burden.eq(level)]
            ev = int(rows._year_state.eq('year_pad_free').sum())
            nev = int(rows._year_state.eq('year_pad_use').sum())
            interaction_cells[f'{country}|{level}'] = {'events': ev, 'nonevents': nev}
            if ev < MIN_PER_INTERACTION_CELL:
                interaction_failures.append(f'cell_{country.replace(" ", "_").lower()}_{level}_events_{ev}_below_{MIN_PER_INTERACTION_CELL}')
            if nev < MIN_PER_INTERACTION_CELL:
                interaction_failures.append(f'cell_{country.replace(" ", "_").lower()}_{level}_nonevents_{nev}_below_{MIN_PER_INTERACTION_CELL}')
    known = observed.loc[observed._burden.isin(KNOWN_BURDEN)]
    known_events = known._year_state.eq('year_pad_free')
    gates.append(gate('country_by_burden_interaction_exploratory',
                      'Original interaction rule. The governing requirement is per country by known-burden cell.',
                      int(known_events.sum()), int((~known_events).sum()), 1, MIN_PER_INTERACTION_CELL,
                      sorted(set(interaction_failures))))
    matrices['four_slope_age_complete_case'] = rank_diagnostics(design_matrix(complete))
    six = dict(design_matrix(timing))
    six.update(timing_columns(timing))
    matrices['six_slope_timing_age_and_day_complete'] = rank_diagnostics(six)
    known_complete = known.loc[finite_numeric(known.age).notna() & known._country.isin(COUNTRIES)]
    interaction_columns = {
        'intercept': np.ones(len(known_complete)),
        'burden_two_or_more': known_complete._burden.eq('two_or_more').to_numpy(float),
        'country_united_states': known_complete._country.eq('United States').to_numpy(float),
    }
    interaction_columns['burden_two_or_more_x_country_united_states'] = (
        interaction_columns['burden_two_or_more'] * interaction_columns['country_united_states'])
    matrices['country_by_burden_interaction_known_burden_age_complete'] = rank_diagnostics(interaction_columns)
    missing_age = int((~age_usable).sum())
    limit_count = int(math.floor(AGE_COMPLETE_CASE_LIMIT * len(observed))) if len(observed) else 0
    return {
        'observed_pair_denominator': int(len(observed)),
        'events_year_pad_free': int(events_mask.sum()),
        'nonevents_year_pad_use': int((~events_mask).sum()),
        'outcome_by_burden_cells': outcome_burden,
        'empty_outcome_by_burden_cells': empty_cells,
        'country_observed_pairs': country_pairs,
        'country_by_known_burden_cells': interaction_cells,
        'gates': gates,
        'gates_passing': sorted(g['key'] for g in gates if g['passes']),
        'gates_failing': sorted(g['key'] for g in gates if not g['passes']),
        'candidate_design_matrices': matrices,
        'age_covariate_missingness': {
            'observed_pairs': int(len(observed)),
            'usable_numeric_age': int(age_usable.sum()),
            'missing_or_unusable_age': missing_age,
            'plan_complete_case_limit_count_at_5_percent': limit_count,
            'complete_case_permitted_by_plan_rule': missing_age <= limit_count,
            'declared_descriptive_missingness_fraction': eda.rounded(missing_age / len(observed)) if len(observed) else None,
            'meaning': 'Covariate missingness only. This is not an outcome probability.'},
        'scope': ('Counts and covariate structure only. No outcome model, observation model, interval, '
                  'test or standardised probability is computed here.'),
    }


def instrument_block(root, cohorts, columns_present):
    """Structured continence quality-of-life availability. Only if metadata exposes it."""
    available = header_projection(columns_present, CONTINENCE_QOL_COLUMNS)
    excluded = header_projection(columns_present, EXCLUDED_INSTRUMENT_COLUMNS)
    if not any(available.values()):
        return {'dedicated_continence_quality_of_life_variables_exposed': False,
                'metadata_projection': available,
                'reason': 'No dedicated continence quality-of-life column name is exposed by the released header.'}
    proms, _ = read_allowlisted(root, 'proms_long')
    day = eda.numeric(proms.days_from_surgery)
    postoperative = proms.event_phase.eq('postoperative')
    windows = {'early_days_60_120': postoperative & day.between(*eda.WINDOWS['early'][:2]),
               'year_days_305_425': postoperative & day.between(*eda.WINDOWS['year'][:2])}
    present = [c for c in CONTINENCE_QOL_COLUMNS if available[c]]
    result = {}
    for name in present:
        nonblank = proms[name].astype(str).str.strip().ne('')
        entry = {'rows_with_a_recorded_value': int(nonblank.sum())}
        for cohort in ('robotic', 'early_users', 'early_users_with_year'):
            members = proms[ID].isin(cohorts[cohort])
            entry[f'{cohort}_patients_with_any_recorded_value'] = int(proms.loc[nonblank & members, ID].nunique())
            for window, mask in windows.items():
                entry[f'{cohort}_patients_with_value_in_{window}'] = int(
                    proms.loc[nonblank & members & mask, ID].nunique())
        result[name] = entry
    return {'dedicated_continence_quality_of_life_variables_exposed': True,
            'metadata_projection': available,
            'erectile_function_instruments_present_but_never_used_as_continence_measures': excluded,
            'availability': result,
            'unused_candidate_explanation': ('Erectile-function instruments and non-urinary domain scores are named '
                                             'and excluded rather than inventoried. No further variable sweep is performed.'),
            'semantics': ('A blank instrument field is unknown. It does not establish that the item was never asked '
                          'and it is not a continence outcome.')}


def build_report(root):
    require(root.absolute() == RELEASE and not root.is_symlink() and root.resolve() == RELEASE,
            'SOURCE_ROOT_NOT_BOUND_RELEASE')
    manifest_path = HERE / 'evidence/SOURCE_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    require(manifest['release_relative_path'] == str(RELEASE.relative_to(WORKSPACE)), 'MANIFEST_ROOT_MISMATCH')
    before = eda.verify_sources(manifest)
    require(before == 122, 'BOUND_INPUT_COUNT_MISMATCH')
    tables = json.loads((root / 'MANIFEST.json').read_text())['tables']
    require(set(tables) == set(eda.TABLES), 'TABLE_SET_MISMATCH')
    formats = eda.preflight_module().parity(root, list(eda.TABLES))
    require(len(formats) == 17, 'FORMAT_PARITY_TABLE_COUNT')
    patients, patient_columns = read_allowlisted(root, 'patient_wide')
    events, _ = read_allowlisted(root, 'continence_events_long')
    _, prom_columns = read_allowlisted(root, 'proms_long')
    age_available = header_projection(patient_columns, ('age', 'country', 'robotic_platform_used', 'surgery_date'))
    require(age_available['age'], 'AGE_COLUMN_NOT_EXPOSED')
    require(patients[ID].ne('').all() and patients[ID].is_unique, 'PATIENT_KEY_CONTRACT_FAILURE')
    require(set(events[ID]) <= set(patients[ID]), 'ORPHAN_FAILURE')
    d, robotic, valid, candidate, selected, masks, context, date_masks = selection_frames(patients, events)
    cohorts = cohort_sets(selected, robotic, patients, valid)
    ladder = {k: len(v) for k, v in cohorts.items()}
    ladder['valid_dated_postoperative_continence'] = int(len(valid))
    require(all(ladder[k] == n for k, n in CANONICAL_LADDER.items()), 'CANONICAL_LADDER_FAILURE')
    require(ladder['early_users_without_year'] == CANONICAL_LADDER['early_users'] - CANONICAL_LADDER['early_users_with_year'],
            'WITHOUT_YEAR_LADDER_FAILURE')
    impacts, direct = {}, {}
    robotic_rows = d.loc[d[ID].isin(robotic)]
    for key in ('early', 'year'):
        groups = impact.group_diagnostics(candidate.loc[candidate['_in_' + key]])
        impacts[key] = impact.impact_sets(robotic_rows, selected[key], groups, key)
        direct[key] = impact.impact_sets(robotic_rows, selected[key], groups, key, True)
    covariates = covariate_frame(patients, selected, cohorts)
    require(len(covariates) == CANONICAL_LADDER['early_users'], 'COVARIATE_FRAME_DENOMINATOR_FAILURE')
    require(int(covariates._burden.isin(BURDEN_LEVELS).sum()) == len(covariates), 'BURDEN_LEVEL_CONTRACT_FAILURE')
    instruments = instrument_block(root, cohorts, prom_columns)
    after = eda.verify_sources(manifest)
    return {
        'record_kind': 'aggregate_observed_pair_covariate_eda_and_feasibility_preparation_only',
        'scope': ('Explanatory observed-pair covariate description and follow-up selection description. '
                  'Not a model fit, not final scope selection, not review, not science lock.'),
        'authority': ('The user-designated release is authoritative and read only. Candidate selections are imported '
                      'unchanged from the accepted preparation, EDA and impact scripts.'),
        'source_root': str(RELEASE.relative_to(WORKSPACE)),
        'source_verification': {'bound_inputs_before': before, 'bound_inputs_after': after, 'mismatches': 0,
                                'manifest_sha256': eda.sha(manifest_path), 'format_parity_tables': len(formats),
                                'format_parity': formats, 'source_writes_performed': False},
        'software': {'python': sys.version.split()[0], 'pandas': pd.__version__, 'numpy': np.__version__,
                     'duckdb': eda.duckdb.__version__},
        'code_sha256': {name: eda.sha(HERE / 'scripts' / name) for name in
                        ('00_preflight.py', '01_prepare_adjudication.py', '02_eda_authoritative.py',
                         '03_conflict_impact.py', '03_analysis_set_accounting.py', '04_observed_covariate_eda.py')},
        'test_sha256': eda.sha(TEST_SCRIPT),
        'context_sha256': {name: eda.sha(HERE / name) for name in
                           ('ANALYSIS_PLAN.md', 'evidence/VARIABLE_MAP.csv', 'evidence/EDA_AUTHORITATIVE_RELEASE.json',
                            'evidence/CONFLICT_IMPACT.json', 'evidence/ANALYSIS_SET_ACCOUNTING.json')},
        'workspace_context_sha256': {'manager_disposition': eda.sha(
            WORKSPACE / 'delegated_tasks/manuscript1_claude_clinical_path/MANAGER_DISPOSITION.md')},
        'source_table_sha256': {name: eda.sha(root / 'tables' / (name + '.csv'))
                                for name in ('patient_wide', 'continence_events_long', 'proms_long')},
        'context_provenance_note': ('This report preserves the original three-level candidate burden and four/six-slope '
                                    'feasibility screens. It does not evaluate the amended four-level exposure or its '
                                    'five/seven-slope models. Current plan bytes are bound without changing that scope.'),
        'allowlist': {'tables': sorted(ALLOWLISTED_COLUMNS), 'columns': {k: list(v) for k, v in ALLOWLISTED_COLUMNS.items()},
                      'metadata_projection_patient_wide': age_available,
                      'metadata_projection_proms_long': header_projection(prom_columns, CONTINENCE_QOL_COLUMNS)},
        'cohort_ladder': ladder,
        'age_evidence': age_blocks(patients, cohorts, covariates),
        'burden_and_country_evidence': burden_country_block(covariates, selected, cohorts, direct, impacts),
        'timing_and_selection_evidence': timing_block(candidate, selected, covariates, cohorts, patients),
        'model_feasibility_screening': feasibility_block(covariates),
        'structured_instrument_availability': instruments,
        'definitions': {
            'units': 'Patients, observation rows and patient-day groups are distinct. Overlapping flags are never summed.',
            'age_missing': 'Blank is missing. Nonnumeric nonblank tokens and nonfinite values are counted separately.',
            'age_flags': 'Range and interquartile flags are diagnostic counts and ranges. No age record is excluded.',
            'burden': 'Historical D3 mapping from a representative selected-day row, not a reconciliation of '
                      'all same-day evidence. The amended four-level day consensus is a separate exposure.',
            'impact_flags': 'Imported diagnostic semantics. A flag marks where investigator judgment is needed. '
                            'No flag removes a patient from any denominator in this record.',
            'coarse_year': 'Calendar year of surgery only. No exact date and no coverage inference.',
            'feasibility_gate': 'Recomputed from present counts each run. No gate result is assumed from an overall '
                                'event total.',
            'design_matrix': 'Covariate structure only. Rank and conditioning use no outcome or observation variable.',
            'source_unknown': 'Unknown is not absence and not never assessed.',
        },
        'limitations': [
            'Preparatory EDA only. No clinical probability, interval, test, model fit, bound, weight or imputation.',
            'The opportunity-conditioned primary remains held because administrative eligibility A is unknown.',
            'Observed-pair counts describe documented assessments under observed care, not population recovery.',
            'The event-index burden inventory is provisional and not an adjudicated exposure.',
            'Feasibility gates describe count adequacy under the accepted plan rule. They do not license a model.',
            'Instrument availability counts describe recorded values only. Blank fields remain unknown.',
        ],
        'privacy': {'aggregate_only': True, 'identifiers_emitted': False, 'exact_dates_emitted': False,
                    'row_exports': False, 'narratives_emitted': False, 'private_source_filenames_emitted': False,
                    'raw_dictionary_examples_emitted': False, 'restricted_inventories_read': False},
        'candidate_membership_changed': False, 'clinical_estimates_computed': False,
        'probabilities_or_intervals_emitted': False, 'model_fitted': False, 'science_lock': False,
    }


def serialise(result):
    return json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=RELEASE)
    ap.add_argument('--output', type=Path, default=OUTPUT)
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args(argv)
    output = args.output.absolute()
    require(not output.is_symlink() and output.resolve().is_relative_to(HERE / 'evidence')
            and not output.resolve().is_relative_to(RELEASE), 'OUTPUT_SCOPE_FAILURE')
    result = build_report(args.root)
    text = serialise(result)
    if args.verify:
        require(output.read_text() == text, 'SAVED_OBSERVED_COVARIATE_EDA_MISMATCH')
    else:
        output.write_text(text)
    print(json.dumps({
        'status': 'saved_observed_covariate_eda_recomputed_exactly' if args.verify else 'aggregate_observed_covariate_eda_written',
        'bound_inputs': result['source_verification']['bound_inputs_before'],
        'format_parity_tables': result['source_verification']['format_parity_tables'],
        'cohort_ladder': result['cohort_ladder'],
        'gates_passing': result['model_feasibility_screening']['gates_passing'],
        'gates_failing': result['model_feasibility_screening']['gates_failing'],
        'output_sha256': eda.sha(output)}))


def safe_main(argv=None):
    try:
        with warnings.catch_warnings():
            # Source parsing warnings can quote private field content. Never surface them.
            warnings.simplefilter('ignore')
            main(argv)
        return 0
    except Exception:
        print('OBSERVED_COVARIATE_EDA_FAILED_SOURCE_DETAIL_WITHHELD', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
