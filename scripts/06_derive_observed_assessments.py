#!/usr/bin/env python3
"""Source-native observed-assessment derivation for the manuscript1 amendment.

Derivation only. This script selects documented assessments, derives the declared
day-level documentary pad burden, rebuilds every named policy over the full robotic
cohort and emits aggregate counts. It computes no probability, no confidence interval,
no hypothesis test, no model fit, no weight, no imputation and no bound on real data.

Patient-level frames exist only in memory. `source_derive` returns them to an importing
analysis script for local statistics. Nothing patient-level, no identifier, no exact
date, no narrative, no raw dictionary example and no private source filename is printed
or written. The saved record is aggregate JSON.

Governing design: manuscript1/ANALYSIS_AMENDMENT_OBSERVED_ASSESSMENTS.md. Validity,
D1 status masking, window grouping and the tie order are imported unchanged from the
accepted 02 and 03 scripts and re-verified here rather than redefined.
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
OUTPUT = HERE / 'evidence/OBSERVED_ASSESSMENT_DERIVATION.json'
TEST_SCRIPT = HERE / 'tests/test_06_derive_observed_assessments.py'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


eda = module('derivation_eda_base', '02_eda_authoritative.py')
impact = module('derivation_impact_base', '03_conflict_impact.py')
cohort_mod = module('derivation_cohort', 'cohort.py')
ID = eda.ID
RELEASE = eda.RELEASE
COUNTRIES = ('Poland', 'United States')
UNKNOWN_COUNTRY = 'unknown_or_other'
COUNTRY_LEVELS = COUNTRIES + (UNKNOWN_COUNTRY,)

# Three core tables only. Columns are an explicit allowlist, not a table sweep.
ALLOWLISTED_COLUMNS = {
    'patient_wide': ('master_patient_id', 'age', 'country', 'robotic_platform_used', 'surgery_date'),
    'continence_events_long': ('master_patient_id', 'event_index', 'country', 'surgery_date', 'event_date',
                               'days_from_surgery', 'event_phase', 'pad_free', 'pads_per_day',
                               'pads_per_day_min', 'pads_per_day_max', 'diaper_count_min', 'diaper_count_max',
                               'safety_pad_documented', 'usable_continence_observation',
                               'event_date_ambiguous', 'event_date_precision_source_derived'),
    'continence_milestones_long': ('master_patient_id', 'milestone_month', 'pad_free', 'observed'),
}
CORE_TABLES = tuple(ALLOWLISTED_COLUMNS)

# Amendment windows. `early` and `year` define the reference target; `six` and `two_year`
# are the added observed later descriptions; the narrow pair belongs to P3 only.
WINDOWS = {'early': (60, 120, 90), 'six': (150, 210, 180), 'year': (305, 425, 365),
           'two_year': (670, 790, 730)}
NARROW_WINDOWS = {'early': (75, 105, 90), 'six': (150, 210, 180), 'year': (335, 395, 365),
                  'two_year': (670, 790, 730)}
LATER_WINDOWS = ('year', 'six', 'two_year')
POLICIES = ('P0', 'P1', 'P2', 'P3', 'P4', 'P5')
MILESTONE_MONTHS = {'early': '3', 'year': '12'}

BURDEN_LEVELS = ('one', 'two_or_more', 'nonconflicting_quantity_uncertain', 'unresolved_quantity_evidence')
BURDEN_FLAGS = ('all_missing_quantity_evidence', 'missing_with_known_quantity_evidence',
                'partial_bound_evidence', 'crossing_range_evidence', 'invalid_quantity_evidence',
                'incompatible_valid_intervals', 'category_stable_numeric_disagreement',
                'device_evidence_present_never_used_as_ordinary')
STATUS_LABELS = {0: 'pad_use', 1: 'pad_free'}
EARLY_STATES = (('early_pad_use', 0), ('early_pad_free', 1))
LATER_STATES = (('later_pad_free', 1), ('later_pad_use', 0))
YEAR_STATES = (('pad_free', 1), ('pad_use', 0), ('not_observed', None))

# Canonical accepted counts. Reconciled every run; never assumed from a previous record.
CANONICAL_LADDER = {'all_released': 1497, 'robotic': 1397, 'valid_dated_postoperative_continence': 5376,
                    'early_status_known': 644, 'early_users': 460, 'paired_early_year': 309,
                    'early_users_with_year': 226, 'year_padfree_observed_pairs': 86}
CANONICAL_WITHOUT_YEAR = {'early_users_without_year_status': 234,
                          'no_valid_year_window_observation': 233,
                          'conflicting_year_window_evidence_only': 1}
# Superseded row-based inventory. Historical accounting only, never an adjudicated exposure.
HISTORICAL_ROW_BURDEN_226 = {'one': 102, 'two_or_more': 88, 'quantity_uncertain': 36}

MIN_PER_SLOPE = 10
MAIN_SLOPE_DF = 5
TIMING_SLOPE_DF = 7
MIN_COUNTRY_PAIRS = 30
AGE_COMPLETE_CASE_LIMIT = 0.05


def require(ok, code):
    """Hard contract check. `code` is a stable token that never carries source content."""
    if not ok:
        raise RuntimeError(code)


def strict(value):
    """Recursively convert to strict JSON scalars. NaN, infinity and objects are rejected."""
    if isinstance(value, dict):
        return {str(k): strict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict(v) for v in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        require(math.isfinite(number), 'NONFINITE_NUMBER_IN_RECORD')
        return number
    if value is None or isinstance(value, str):
        return value
    raise RuntimeError('UNSERIALISABLE_VALUE_IN_RECORD')


# --------------------------------------------------------------------------------------
# Source binding and reading
# --------------------------------------------------------------------------------------

def bind_root(root):
    """Only the exact active release may be read. No symlink and no alternative copy."""
    require(root.absolute() == RELEASE and not root.is_symlink() and root.resolve() == RELEASE,
            'SOURCE_ROOT_NOT_BOUND_RELEASE')
    return root


def bound_inputs(manifest_path=HERE / 'evidence/SOURCE_MANIFEST.json'):
    """Verify every bound workspace input hash. Returns the verified file count."""
    manifest = json.loads(manifest_path.read_text())
    require(manifest['release_relative_path'] == str(RELEASE.relative_to(WORKSPACE)), 'MANIFEST_ROOT_MISMATCH')
    checked = eda.verify_sources(manifest)
    require(checked == 122, 'BOUND_INPUT_COUNT_MISMATCH')
    return checked


def read_allowlisted(root, table):
    """Read declared columns only. A missing declared column is a contract failure."""
    require(table in ALLOWLISTED_COLUMNS, 'TABLE_NOT_ALLOWLISTED')
    path = root / 'tables' / (table + '.csv')
    header = tuple(pd.read_csv(path, dtype=str, nrows=0).columns)
    wanted = list(ALLOWLISTED_COLUMNS[table])
    require(all(name in header for name in wanted), 'ALLOWLISTED_COLUMN_MISSING')
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=wanted)


def read_core_tables(root):
    """The three core tables under the explicit column allowlist, plus key contracts."""
    frames = {table: read_allowlisted(root, table) for table in CORE_TABLES}
    patients = frames['patient_wide']
    require(patients[ID].ne('').all() and patients[ID].is_unique, 'PATIENT_KEY_CONTRACT_FAILURE')
    ids = set(patients[ID])
    require(set(frames['continence_events_long'][ID]) <= ids, 'EVENT_ORPHAN_FAILURE')
    require(set(frames['continence_milestones_long'][ID]) <= ids, 'MILESTONE_ORPHAN_FAILURE')
    require(not frames['continence_milestones_long'].duplicated([ID, 'milestone_month']).any(),
            'MILESTONE_KEY_FAILURE')
    return frames['patient_wide'], frames['continence_events_long'], frames['continence_milestones_long']


def table_manifest(root):
    """Seventeen released tables and verified cross-format parity, checked from the release."""
    tables = json.loads((root / 'MANIFEST.json').read_text())['tables']
    require(set(tables) == set(eda.TABLES) and len(tables) == 17, 'TABLE_SET_MISMATCH')
    require(set(CORE_TABLES) <= set(tables), 'CORE_TABLE_NOT_IN_RELEASE')
    parity = eda.preflight_module().parity(root, list(eda.TABLES))
    require(len(parity) == 17, 'FORMAT_PARITY_TABLE_COUNT')
    require(all(bool(v) for v in parity.values()) if isinstance(parity, dict) else True,
            'FORMAT_PARITY_FAILURE')
    return sorted(tables), parity


# --------------------------------------------------------------------------------------
# Candidate observations
# --------------------------------------------------------------------------------------

def candidate_frame(patients, events):
    """Accepted validity screen, robotic restriction and D1 status masking, unchanged.

    D1 blanking reproduces the accepted screen. It resolves no patient fact.
    """
    annotated, masks, context, date_masks = impact.annotate(events, patients)
    robotic = set(patients.loc[eda.truth(patients.robotic_platform_used), ID])
    valid = annotated.loc[annotated._valid & annotated[ID].isin(robotic)].copy()
    candidate = valid.copy()
    candidate['_d1_status_masked'] = candidate._endpoint_bad
    candidate.loc[candidate._endpoint_bad, '_status'] = pd.NA
    return annotated, robotic, valid, candidate


def offset_agreement(frame):
    """Recomputed day versus released offset. Disagreement is reported, never repaired."""
    recorded = eda.numeric(frame.days_from_surgery)
    comparable = recorded.notna() & frame._day.notna()
    return {'rows': int(len(frame)), 'comparable_rows': int(comparable.sum()),
            'offset_missing_or_nonnumeric_rows': int(recorded.isna().sum()),
            'recomputed_day_disagrees_with_released_offset': int((comparable & recorded.ne(frame._day)).sum())}


def select_window(candidate, window, mode='nearest'):
    """One documented assessment per patient in one window under one policy rule.

    Patient-day groups holding both explicit pad-free and pad-use states are unavailable.
    `nearest` keeps the accepted rule and permits another consistent day in the window.
    `window_restricted` (P1) removes the whole patient-window when any eligible day
    conflicts. `first` (P2) takes the first usable day instead of the nearest.
    Ties on distance resolve to the earlier day, then to the released event index.
    """
    require(mode in ('nearest', 'window_restricted', 'first'), 'UNKNOWN_SELECTION_MODE')
    low, high, target = window
    frame = candidate.loc[candidate._day.between(low, high) & candidate._status.notna()].copy()
    day_groups = frame.groupby([ID, '_date'])._status.agg(['size', 'nunique'])
    conflicting = frame.groupby([ID, '_date'])._status.transform('nunique').gt(1)
    conflict_patients = set(frame.loc[conflicting, ID])
    eligible_patients = set(frame[ID])
    if mode == 'window_restricted':
        frame = frame.loc[~frame[ID].isin(conflict_patients)].copy()
    else:
        frame = frame.loc[~conflicting].copy()
    frame['_distance'] = (frame._day - target).abs()
    order = ['_date', 'event_index'] if mode == 'first' else ['_distance', '_date', 'event_index']
    chosen = frame.sort_values(order, kind='stable').drop_duplicates(ID)
    selected_patients = set(chosen[ID])
    diagnostics = {
        'window_days': [int(low), int(high)], 'target_day': int(target), 'mode': mode,
        'patients_with_any_known_status_day': len(eligible_patients),
        'patient_day_groups': int(len(day_groups)),
        'consistent_repeated_day_groups': int((day_groups['size'].gt(1) & day_groups['nunique'].eq(1)).sum()),
        'conflicting_day_groups': int(day_groups['nunique'].gt(1).sum()),
        'conflicting_day_patients': len(conflict_patients),
        'conflicting_day_rows': int(conflicting.sum()),
        'patients_reentering_on_an_alternative_consistent_day': len(conflict_patients & selected_patients),
        'patients_lost_after_conflicting_day_omission': len(conflict_patients - selected_patients),
        'selected_patients': len(chosen),
        'selected_pad_use': int(chosen._status.eq(0).sum()),
        'selected_pad_free': int(chosen._status.eq(1).sum()),
    }
    return chosen, diagnostics


# --------------------------------------------------------------------------------------
# Day-level documentary ordinary-pad burden
# --------------------------------------------------------------------------------------

def quantity_columns(frame):
    """Independent ordinary-pad bound fallbacks and row validity. Devices are excluded."""
    point = eda.numeric(frame.pads_per_day)
    raw_lower = eda.numeric(frame.pads_per_day_min)
    raw_upper = eda.numeric(frame.pads_per_day_max)
    lower = raw_lower.fillna(point)
    upper = raw_upper.fillna(point)
    # Numeric validity only. A parsed infinity is not a documented daily pad count, so it
    # fails the same row-validity screen as a negative or inverted bound instead of being
    # carried into an effective interval. This is a parsing guard, not clinical adjudication,
    # and it assumes no pad count and no known defect count in the source.
    nonfinite = point.abs().eq(np.inf) | raw_lower.abs().eq(np.inf) | raw_upper.abs().eq(np.inf)
    invalid = (nonfinite | point.lt(0) | lower.lt(0) | upper.lt(0) | lower.gt(upper)
               | (point.notna() & ((raw_lower.notna() & point.lt(raw_lower))
                                   | (raw_upper.notna() & point.gt(raw_upper)))))
    informative = lower.notna() | upper.notna()
    return {'point': point, 'raw_lower': raw_lower, 'raw_upper': raw_upper,
            'lower': lower, 'upper': upper, 'invalid': invalid,
            'nonfinite_quantity_value': nonfinite, 'informative': informative}


def row_category(lower, upper):
    """Row-level documentary category from the effective interval only."""
    if pd.isna(lower) and pd.isna(upper):
        return 'no_numeric_evidence'
    if pd.notna(lower) and pd.notna(upper) and float(lower) == 1.0 and float(upper) == 1.0:
        return 'one'
    if pd.notna(lower) and float(lower) >= 2.0:
        return 'two_or_more'
    return 'quantity_uncertain'


def classify_day(rows):
    """Four-level day burden with separate evidence flags, from an unordered row set.

    No event index, row order or later outcome participates. Missing rows never veto a
    compatible known category and intervals are never intersected into a new exact count.
    Every flag is computed independently over the rows it describes, so no contradiction
    suppresses another flag. Invalid rows keep their own flag and never supply an endpoint
    to the valid-interval intersection. Category precedence is applied only afterwards.
    """
    columns = quantity_columns(rows)
    flags = {name: False for name in BURDEN_FLAGS}
    devices = (eda.numeric(rows.diaper_count_min).gt(0) | eda.numeric(rows.diaper_count_max).gt(0)
               | eda.truth(rows.safety_pad_documented))
    flags['device_evidence_present_never_used_as_ordinary'] = bool(devices.any())
    informative = columns['informative']
    invalid = columns['invalid']
    flags['all_missing_quantity_evidence'] = bool(len(rows) > 0 and not informative.any())
    flags['missing_with_known_quantity_evidence'] = bool(informative.any() and (~informative).any())
    flags['invalid_quantity_evidence'] = bool(invalid.any())
    known = rows.index[(informative & ~invalid).to_numpy()]
    partial = [i for i in known if pd.isna(columns['lower'][i]) or pd.isna(columns['upper'][i])]
    crossing = [i for i in known
                if pd.notna(columns['lower'][i]) and pd.notna(columns['upper'][i])
                and float(columns['lower'][i]) <= 1.0 and float(columns['upper'][i]) >= 2.0]
    flags['partial_bound_evidence'] = bool(partial)
    flags['crossing_range_evidence'] = bool(crossing)
    if len(known):
        lower_bounds = columns['lower'][known].dropna()
        upper_bounds = columns['upper'][known].dropna()
        if len(lower_bounds) and len(upper_bounds) and float(lower_bounds.max()) > float(upper_bounds.min()):
            flags['incompatible_valid_intervals'] = True
    categories = {row_category(columns['lower'][i], columns['upper'][i]) for i in known}
    signatures = set()
    for i in known:
        low = None if pd.isna(columns['lower'][i]) else float(columns['lower'][i])
        high = None if pd.isna(columns['upper'][i]) else float(columns['upper'][i])
        exact = None if pd.isna(columns['point'][i]) else float(columns['point'][i])
        signatures.add((low, high, None if low == high == exact else exact))
    flags['category_stable_numeric_disagreement'] = bool(len(signatures) > 1 and len(categories) == 1)
    if flags['invalid_quantity_evidence'] or flags['incompatible_valid_intervals']:
        return 'unresolved_quantity_evidence', flags, columns
    if not categories:
        return 'nonconflicting_quantity_uncertain', flags, columns
    if categories == {'one'}:
        return 'one', flags, columns
    if categories == {'two_or_more'}:
        return 'two_or_more', flags, columns
    return 'nonconflicting_quantity_uncertain', flags, columns


def day_burden(candidate, chosen):
    """Burden for every selected patient from all status-consistent rows on that day."""
    selected_status = dict(zip(chosen[ID], chosen._status))
    keys = set(zip(chosen[ID], chosen._date))
    member = pd.Series([(pid, when) in keys for pid, when in zip(candidate[ID], candidate._date)],
                       index=candidate.index)
    day_rows = candidate.loc[member].copy()
    mapped = day_rows[ID].map(selected_status).astype('Int64')
    consistent = day_rows._status.eq(mapped).fillna(False).astype(bool)
    usable = day_rows.loc[consistent]
    excluded = int(len(day_rows) - len(usable))
    records, grouped = [], {pid: group for pid, group in usable.groupby(ID, sort=False)}
    for pid in chosen[ID]:
        group = grouped.get(pid)
        require(group is not None and len(group) > 0, 'SELECTED_DAY_ROW_MISSING')
        level, flags, _ = classify_day(group)
        records.append({ID: pid, '_burden': level, '_burden_rows': int(len(group)), **flags})
    frame = pd.DataFrame(records, columns=[ID, '_burden', '_burden_rows'] + list(BURDEN_FLAGS))
    diagnostics = {'selected_day_rows': int(len(day_rows)),
                   'status_consistent_rows_used': int(len(usable)),
                   'rows_excluded_status_unavailable_or_inconsistent': excluded,
                   'patients': int(len(frame))}
    return frame, diagnostics


# --------------------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------------------

def milestone_states(milestones, robotic):
    """P5 released milestone states. Explicit observed and explicit Boolean pad status."""
    frame = milestones.loc[milestones[ID].isin(robotic)].copy()
    frame['_observed'] = eda.truth(frame.observed)
    status = pd.Series(pd.NA, index=frame.index, dtype='Int64')
    status[eda.truth(frame.pad_free)] = 1
    status[eda.false(frame.pad_free)] = 0
    frame['_status'] = status
    usable = frame.loc[frame._observed & frame._status.notna()]
    chosen, diagnostics = {}, {}
    for window, month in MILESTONE_MONTHS.items():
        month_rows = usable.loc[usable.milestone_month.eq(month)]
        states = month_rows.groupby(ID)._status.agg(['nunique', 'first', 'size'])
        conflicting = states['nunique'].gt(1)
        keep = states.loc[~conflicting]
        chosen[window] = pd.DataFrame({ID: keep.index, '_status': keep['first'].astype('Int64')}).reset_index(drop=True)
        diagnostics[window] = {
            'milestone_month': int(month),
            'robotic_milestone_rows': int(frame.milestone_month.eq(month).sum()),
            'explicit_observed_with_explicit_status': int(len(month_rows)),
            'patients_with_usable_state': int(len(states)),
            'patients_with_conflicting_milestone_state_unavailable': int(conflicting.sum()),
            'patients_with_consistent_repeated_state_collapsed': int((~conflicting & states['size'].gt(1)).sum()),
            'selected_patients': int(len(chosen[window])),
            'selected_pad_use': int(chosen[window]._status.eq(0).sum()),
            'selected_pad_free': int(chosen[window]._status.eq(1).sum())}
    return chosen, diagnostics


def date_impact_patients(annotated, robotic, candidate, selected):
    """Accepted date-selection impact sets for P4, including nonselected uncertain dates."""
    robotic_rows = annotated.loc[annotated[ID].isin(robotic)]
    sets = {}
    for key in ('early', 'year'):
        groups = impact.group_diagnostics(candidate.loc[candidate['_in_' + key]])
        sets[key] = impact.impact_sets(robotic_rows, selected[key], groups, key)
    return sets['early']['date'] | sets['year']['date'], {
        'early_window_date_impact_patients': len(sets['early']['date']),
        'year_window_date_impact_patients': len(sets['year']['date']),
        'either_window_date_impact_patients': len(sets['early']['date'] | sets['year']['date'])}


def policy_selection(candidate, policy, date_excluded=frozenset(), milestones=None, robotic=None):
    """Rebuild the complete selection for one policy over the full robotic cohort."""
    require(policy in POLICIES, 'UNKNOWN_POLICY')
    if policy == 'P5':
        chosen, diagnostics = milestone_states(milestones, robotic)
        burden = pd.DataFrame(columns=[ID, '_burden', '_burden_rows'] + list(BURDEN_FLAGS))
        return {'selected': chosen, 'window_diagnostics': diagnostics, 'burden': burden,
                'burden_diagnostics': {'applicable': False,
                                       'reason': 'milestone_observation_rule_has_no_exact_selected_day'},
                'excluded_patients': 0, 'observation_rule': 'released_milestone_months_3_and_12'}
    frame = candidate
    excluded = 0
    if policy == 'P4':
        frame = candidate.loc[~candidate[ID].isin(date_excluded)]
        excluded = len(date_excluded & set(candidate[ID]))
    windows = NARROW_WINDOWS if policy == 'P3' else WINDOWS
    mode = {'P1': 'window_restricted', 'P2': 'first'}.get(policy, 'nearest')
    chosen, diagnostics = {}, {}
    for key, window in windows.items():
        chosen[key], diagnostics[key] = select_window(frame, window, mode)
    burden, burden_diagnostics = day_burden(frame, chosen['early'])
    return {'selected': chosen, 'window_diagnostics': diagnostics, 'burden': burden,
            'burden_diagnostics': {'applicable': True, **burden_diagnostics},
            'excluded_patients': excluded,
            'observation_rule': 'exact_window_day_selection'}


def cohort_sets(selection):
    """Patient identity sets for one policy. Coupling stays at patient level throughout."""
    chosen = selection['selected']
    early = chosen['early']
    users = set(early.loc[early._status.eq(0), ID])
    free_early = set(early.loc[early._status.eq(1), ID])
    sets = {'early_status_known': set(early[ID]), 'early_users': users, 'early_pad_free': free_early}
    for key in LATER_WINDOWS:
        if key not in chosen:
            continue
        later = chosen[key]
        later_ids = set(later[ID])
        sets[key + '_status_known'] = later_ids
        sets['paired_early_' + key] = sets['early_status_known'] & later_ids
        sets['early_users_with_' + key] = users & later_ids
        sets[key + '_padfree_in_early_user_pairs'] = (users & set(later.loc[later._status.eq(1), ID]))
    sets['early_users_without_year'] = users - sets.get('year_status_known', set())
    return sets


# --------------------------------------------------------------------------------------
# Patient frames returned to a downstream analysis
# --------------------------------------------------------------------------------------

def patient_frame(patients, selection, sets):
    """One row per early pad user with coupled status, burden, timing and covariates.

    Returned in memory only. Never printed, logged, serialised or written to disk.
    """
    chosen = selection['selected']
    early = chosen['early'].set_index(ID)
    base = patients.loc[patients[ID].isin(sets['early_users'])].copy()
    base['_age'] = eda.numeric(base.age)
    base['_age_known'] = np.isfinite(base._age.to_numpy(float))
    base['_country'] = np.where(base.country.isin(COUNTRIES), base.country, UNKNOWN_COUNTRY)
    base['_country_source_value_known'] = base.country.isin(COUNTRIES)
    base['_coarse_surgery_year'] = eda.dates(base.surgery_date).dt.year
    base['_early_status'] = base[ID].map(early._status).astype('Int64')
    if '_day' in early.columns:
        base['_early_day'] = base[ID].map(early._day)
        base['_early_event_country'] = base[ID].map(early.country)
    else:
        base['_early_day'] = pd.NA
        base['_early_event_country'] = ''
    burden = selection['burden']
    if len(burden):
        burden_map = burden.set_index(ID)
        base['_burden'] = base[ID].map(burden_map._burden)
        for flag in BURDEN_FLAGS:
            base['_flag_' + flag] = base[ID].map(burden_map[flag]).fillna(False).astype(bool)
    else:
        base['_burden'] = 'not_applicable_milestone_rule'
        for flag in BURDEN_FLAGS:
            base['_flag_' + flag] = False
    for key in LATER_WINDOWS:
        if key not in chosen:
            continue
        later = chosen[key].set_index(ID)
        base['_' + key + '_status'] = base[ID].map(later._status).astype('Int64')
        base['_' + key + '_day'] = base[ID].map(later._day) if '_day' in later.columns else pd.NA
        base['_' + key + '_record_available'] = base[ID].isin(set(later.index))
    require(base[ID].is_unique, 'PATIENT_FRAME_NOT_ONE_ROW_PER_PATIENT')
    return base.sort_values(ID, kind='stable').reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Aggregate counting helpers
# --------------------------------------------------------------------------------------

def state_label(value):
    if pd.isna(value):
        return 'not_observed'
    return STATUS_LABELS[int(value)]


def transition_counts(frame, later_key):
    """Complete two-by-two transition counts over all paired patients. Counts only."""
    column = '_' + later_key + '_status'
    out = {}
    total = 0
    for early_state, early_value in EARLY_STATES:
        for later_state, later_value in LATER_STATES:
            n = int((frame._early_status.eq(early_value) & frame[column].eq(later_value)).sum())
            out[early_state + '|' + later_state] = n
            total += n
    out['paired_total'] = total
    return out


def burden_country_outcome_counts(frame, later_key='year'):
    """Complete four-level burden by country by observed later state cells, zeros included."""
    column = '_' + later_key + '_status'
    cells, total = {}, 0
    for level in BURDEN_LEVELS:
        for country in COUNTRY_LEVELS:
            for state, value in YEAR_STATES:
                mask = frame._burden.eq(level) & frame._country.eq(country)
                mask &= frame[column].isna() if value is None else frame[column].eq(value)
                n = int(mask.sum())
                cells['|'.join([level, country, state])] = n
                total += n
    cells['declared_cell_total'] = total
    cells['rows_outside_declared_levels'] = int(len(frame) - total)
    return cells


def level_counts(series, levels):
    counts = {level: int(series.eq(level).sum()) for level in levels}
    counts['declared_total'] = int(sum(counts.values()))
    counts['outside_declared_levels'] = int(len(series) - counts['declared_total'])
    return counts


def numeric_block(series):
    """Aggregate numeric profile through the accepted statistic helper. No raw values."""
    text = pd.Series(['' if pd.isna(v) else repr(float(v)) for v in list(pd.Series(series))], dtype=object)
    return eda.stats(text)


def gate(key, label, events, nonevents, slope_df, minimum=MIN_PER_SLOPE, extra_failures=()):
    """Recomputed count gate. No model is fitted and no gate result is assumed."""
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


def rank_diagnostics(columns):
    """Covariate structure only. No outcome participates and no coefficient is estimated."""
    names = list(columns)
    matrix = np.column_stack([columns[k] for k in names]) if names else np.zeros((0, 0))
    if matrix.size == 0 or matrix.shape[0] == 0 or not np.isfinite(matrix).all():
        return {'columns': names, 'rows': 0, 'full_column_rank': False,
                'diagnostic_state': 'not_computable_empty_or_nonfinite'}
    rank = int(np.linalg.matrix_rank(matrix))
    singular = np.linalg.svd(matrix, compute_uv=False)
    smallest = float(singular[-1]) if singular.size else 0.0
    condition = float(singular[0] / smallest) if smallest > 0 else None
    return {'columns': names, 'rows': int(matrix.shape[0]), 'column_count': len(names), 'rank': rank,
            'full_column_rank': rank == len(names),
            'condition_number': eda.rounded(condition) if condition is not None else None,
            'smallest_singular_value': eda.rounded(smallest),
            'zero_variance_columns': [k for k in names if k != 'intercept' and float(np.std(columns[k])) == 0.0],
            'diagnostic_state': 'covariate_structure_only_no_model_fitted'}


def outcome_by_burden_cells(rows):
    """Complete four-level outcome-by-burden counts on one row set. Zeros are kept."""
    return {level + '|' + state: int((rows._burden.eq(level) & rows._year_status.eq(value)).sum())
            for level in BURDEN_LEVELS for state, value in (('year_pad_free', 1), ('year_pad_use', 0))}


def model_columns(rows, timing=False):
    """Declared covariate columns for one candidate model. All four levels are retained."""
    age = eda.numeric(rows._age).to_numpy(float)
    columns = {'intercept': np.ones(len(rows)),
               'burden_two_or_more': rows._burden.eq('two_or_more').to_numpy(float),
               'burden_nonconflicting_quantity_uncertain':
                   rows._burden.eq('nonconflicting_quantity_uncertain').to_numpy(float),
               'burden_unresolved_quantity_evidence':
                   rows._burden.eq('unresolved_quantity_evidence').to_numpy(float),
               'age_centred_65_per_10': (age - 65.0) / 10.0,
               'country_united_states': rows._country.eq('United States').to_numpy(float)}
    if timing:
        columns['early_day_centred_90_per_30'] = (eda.numeric(rows._early_day).to_numpy(float) - 90.0) / 30.0
        columns['year_day_centred_365_per_30'] = (eda.numeric(rows._year_day).to_numpy(float) - 365.0) / 30.0
    return columns


def model_eligible(observed, timing=False):
    """Observed pairs one candidate model could actually use. Nothing is merged or imputed.

    Every candidate requires a finite age and a named country. The timing sensitivity
    independently requires a finite early-day and year-day value on the same rows, so an
    unavailable assessment day removes a pair from the timing model only.
    """
    eligible = pd.Series(np.asarray(observed._age_known, dtype=bool), index=observed.index)
    eligible &= observed._country.isin(COUNTRIES)
    if timing:
        for column in ('_early_day', '_year_day'):
            finite = np.isfinite(eda.numeric(observed[column]).to_numpy(float))
            eligible &= pd.Series(finite, index=observed.index)
    return observed.loc[eligible]


def structural_support(rows, columns, extra_failures=()):
    """Preliminary structural support recomputed on one model's own eligible rows.

    Counts, complete outcome-by-burden cells, country support and covariate rank all come
    from the same rows. A rank deficiency or a noncomputable design matrix is a structural
    failure, not a silent diagnostic. No burden level is merged or dropped to rescue a gate.
    """
    cells = outcome_by_burden_cells(rows)
    empty = sorted(k for k, v in cells.items() if v == 0)
    country_pairs = {country: int(rows._country.eq(country).sum()) for country in COUNTRY_LEVELS}
    rank = rank_diagnostics(columns)
    failures = list(extra_failures)
    failures += ['empty_outcome_by_burden_cell_' + key for key in empty]
    failures += [f'country_{country}_pairs_{n}_below_{MIN_COUNTRY_PAIRS}'
                 for country, n in country_pairs.items()
                 if country in COUNTRIES and n < MIN_COUNTRY_PAIRS]
    if int((~rows._country.isin(COUNTRIES)).sum()):
        failures.append('country_outside_declared_model_levels')
    if int((~rows._burden.isin(BURDEN_LEVELS)).sum()):
        failures.append('burden_outside_declared_model_levels')
    if not rank['full_column_rank']:
        if 'rank' in rank:
            failures.append(f"design_matrix_rank_{rank['rank']}_below_columns_{rank['column_count']}")
        else:
            failures.append('design_matrix_' + rank['diagnostic_state'])
    detail = {'eligible_pairs': int(len(rows)), 'outcome_by_burden_cells': cells,
              'empty_outcome_by_burden_cells': empty, 'eligible_pairs_by_country': country_pairs,
              'design_matrix': rank}
    return int(rows._year_status.eq(1).sum()), int(rows._year_status.eq(0).sum()), failures, detail


def feasibility_block(frame):
    """Four-level structural support for the amendment's five and seven slope models.

    Descriptive counts and covariate missingness stay on the complete observed-pair
    denominator. Every candidate model's counts, cells, country support and covariate rank
    are recomputed on the rows that model could actually use. This is preliminary structural
    support only. Passing it licenses no model fit and replaces no overlap, misspecification,
    separation or influence assessment.
    """
    observed = frame.loc[frame._year_status.notna()]
    events = int(observed._year_status.eq(1).sum())
    nonevents = int(observed._year_status.eq(0).sum())
    cells = outcome_by_burden_cells(observed)
    empty = sorted(k for k, v in cells.items() if v == 0)
    country_pairs = {country: int(observed._country.eq(country).sum()) for country in COUNTRY_LEVELS}
    age_missing = int((~observed._age_known).sum())
    age_fraction = age_missing / len(observed) if len(observed) else None
    within_limit = bool(age_fraction is not None and age_fraction <= AGE_COMPLETE_CASE_LIMIT)
    age_failures = ([] if within_limit else
                    [f'age_missing_fraction_above_{AGE_COMPLETE_CASE_LIMIT}_complete_case_limit'
                     '_declared_multiple_imputation_required'])
    main_rows = model_eligible(observed)
    timing_rows = model_eligible(observed, timing=True)
    main_events, main_nonevents, main_failures, main_detail = structural_support(
        main_rows, model_columns(main_rows), age_failures)
    timing_events, timing_nonevents, timing_failures, timing_detail = structural_support(
        timing_rows, model_columns(timing_rows, timing=True), age_failures)
    gates = [
        gate('main_four_level_burden_age_country', 'Three burden indicators, age and country.',
             main_events, main_nonevents, MAIN_SLOPE_DF, extra_failures=main_failures),
        gate('timing_sensitivity_four_level', 'Main structure plus early-day and year-day timing.',
             timing_events, timing_nonevents, TIMING_SLOPE_DF, extra_failures=timing_failures),
    ]
    gates[0].update(eligible_rows='observed_pairs_with_finite_age_and_named_country', **main_detail)
    gates[1].update(eligible_rows='observed_pairs_with_finite_age_named_country_and_finite_early_and_year_days',
                    **timing_detail)
    return {
        'observed_pairs': int(len(observed)), 'events_year_pad_free': events, 'nonevents_year_pad_use': nonevents,
        'four_level_outcome_by_burden_cells': cells, 'empty_outcome_by_burden_cells': empty,
        'observed_pairs_by_country': country_pairs,
        'age_missing_in_observed_pairs': age_missing,
        'age_missing_fraction': eda.rounded(age_fraction) if age_fraction is not None else None,
        'age_complete_case_limit': AGE_COMPLETE_CASE_LIMIT,
        'age_missing_within_complete_case_limit': within_limit,
        'declared_age_handling': ('complete_age_records_with_a_reported_changed_denominator' if within_limit else
                                  'declared_chained_equation_imputation_required_no_complete_case_model_granted'),
        'main_model_eligible_pairs': int(len(main_rows)),
        'timing_model_eligible_pairs': int(len(timing_rows)),
        'observed_pairs_outside_the_main_model_subset': int(len(observed) - len(main_rows)),
        'main_model_pairs_lost_to_unavailable_assessment_days': int(len(main_rows) - len(timing_rows)),
        'gates': gates, 'gates_passing': sum(1 for g in gates if g['passes']),
        'gates_failing': sum(1 for g in gates if not g['passes']),
        'design_matrix_main': main_detail['design_matrix'],
        'design_matrix_timing_sensitivity': timing_detail['design_matrix'],
        'preliminary_structural_support_by_gate': {g['key']: bool(g['passes']) for g in gates},
        'passing_a_gate_licenses_a_model_fit': False,
        'superseded_three_level_note': ('The current structure is the four-level documentary burden with five and '
                                        'seven slope degrees of freedom. The earlier three-level four and six slope '
                                        'screening is superseded for this target.'),
        'structural_support_scope': ('Preliminary structural support only: recomputed arm counts, complete '
                                     'outcome-by-burden cells, country support and covariate rank on each '
                                     "model's own eligible rows. Covariate overlap, functional form, separation, "
                                     'influence and leave-one-patient-out stability are assessed separately and '
                                     'afterwards, and a supported structure remains unfitted here.'),
        'meaning': 'Count adequacy and covariate structure only. No fit, probability, interval or test is produced.',
    }


# --------------------------------------------------------------------------------------
# Reference and policy reporting
# --------------------------------------------------------------------------------------

def availability_block(frame, conflict_only, no_record):
    """Record availability among all early pad users. Not a response fraction."""
    observed = frame._year_record_available
    by_country = {}
    for country in COUNTRY_LEVELS:
        rows = frame.loc[frame._country.eq(country)]
        by_country[country] = {'early_users': int(len(rows)),
                               'with_year_status': int(rows._year_record_available.sum()),
                               'without_year_status': int((~rows._year_record_available).sum())}
    by_burden = {}
    for level in BURDEN_LEVELS:
        rows = frame.loc[frame._burden.eq(level)]
        by_burden[level] = {'early_users': int(len(rows)),
                            'with_year_status': int(rows._year_record_available.sum()),
                            'without_year_status': int((~rows._year_record_available).sum())}
    return {
        'early_users': int(len(frame)), 'with_year_status': int(observed.sum()),
        'without_year_status': int((~observed).sum()),
        'without_year_status_reasons': {'no_valid_year_window_observation': int(no_record),
                                        'conflicting_year_window_evidence_only': int(conflict_only)},
        'by_country': by_country, 'by_four_level_burden': by_burden,
        'age_known_by_year_record_availability': {
            'with_year_status': int(frame.loc[observed, '_age_known'].sum()),
            'without_year_status': int(frame.loc[~observed, '_age_known'].sum())},
        'early_day_profile_with_year_status': numeric_block(frame.loc[observed, '_early_day']),
        'early_day_profile_without_year_status': numeric_block(frame.loc[~observed, '_early_day']),
        'meaning': ('Documented record availability among observed care. Not an opportunity-conditioned response '
                    'fraction, not a weight and not a missing-outcome bound.'),
    }


def country_consistency(frame, candidate):
    """Patient-table country against event countries. Unknown is never recoded."""
    event_country = frame._early_event_country.fillna('')
    rows = candidate.loc[candidate[ID].isin(set(frame[ID]))]
    distinct = rows.groupby(ID).country.nunique()
    return {
        'early_users': int(len(frame)),
        'patient_table_country': level_counts(frame._country, COUNTRY_LEVELS),
        'selected_early_event_country_known': int(event_country.isin(COUNTRIES).sum()),
        'selected_early_event_country_unknown_or_other': int((~event_country.isin(COUNTRIES)).sum()),
        'patient_and_selected_event_country_agree': int(
            (frame.country.eq(event_country) & frame.country.ne('')).sum()),
        'patient_and_selected_event_country_disagree': int(
            (frame.country.ne(event_country) & frame.country.ne('') & event_country.ne('')).sum()),
        'patient_country_missing_or_other': int((~frame.country.isin(COUNTRIES)).sum()),
        'patients_with_multiple_distinct_event_countries_across_all_valid_rows': int(distinct.gt(1).sum()),
        'patients_with_no_valid_event_row_country': int(len(frame) - int(distinct.gt(0).sum())),
        'recoding': 'none_applied_unknown_country_is_not_recoded_to_a_named_country',
    }


def age_block(frame):
    """Finite and missing age evidence. No imputation of any kind is performed here."""
    return {'early_users': int(len(frame)),
            'age_finite': int(frame._age_known.sum()),
            'age_missing_or_unusable': int((~frame._age_known).sum()),
            'profile_finite_only': numeric_block(frame.loc[frame._age_known, '_age']),
            'imputation_performed': False}


def burden_block(frame):
    """Four-level burden counts and separate evidence flags. All levels are retained."""
    counts = level_counts(frame._burden, BURDEN_LEVELS)
    flags = {flag: int(frame['_flag_' + flag].sum()) for flag in BURDEN_FLAGS}
    by_level_flags = {level: {flag: int(frame.loc[frame._burden.eq(level), '_flag_' + flag].sum())
                              for flag in BURDEN_FLAGS} for level in BURDEN_LEVELS}
    return {'early_users': counts, 'evidence_flags': flags, 'evidence_flags_by_level': by_level_flags,
            'observed_year_pairs': level_counts(frame.loc[frame._year_status.notna(), '_burden'], BURDEN_LEVELS),
            'meaning': ('Declared documentary exposure on the selected early day. Not an adjudicated clinical '
                        'quantity and not a resolution of any contradictory record.')}


def later_window_block(frame, key):
    """Observed pairs for one later window with its own denominator. Counts only."""
    column = '_' + key + '_status'
    users = frame.loc[frame._early_status.eq(0)]
    return {'early_users': int(len(users)),
            'early_users_with_later_status': int(users[column].notna().sum()),
            'later_pad_free_in_early_user_pairs': int(users[column].eq(1).sum()),
            'later_pad_use_in_early_user_pairs': int(users[column].eq(0).sum()),
            'by_country': {country: {
                'early_users': int(users._country.eq(country).sum()),
                'with_later_status': int((users._country.eq(country) & users[column].notna()).sum()),
                'later_pad_free': int((users._country.eq(country) & users[column].eq(1)).sum())}
                for country in COUNTRY_LEVELS},
            'by_four_level_burden': {level: {
                'early_users': int(users._burden.eq(level).sum()),
                'with_later_status': int((users._burden.eq(level) & users[column].notna()).sum()),
                'later_pad_free': int((users._burden.eq(level) & users[column].eq(1)).sum())}
                for level in BURDEN_LEVELS},
            'intermediate_visit_requirement': 'none_missing_intermediate_assessments_do_not_prevent_a_pair'}


def paired_frame(patients, selection, sets, later_key='year'):
    """All patients with both a selected early and later status, including early pad-free."""
    chosen = selection['selected']
    early = chosen['early'].set_index(ID)
    later = chosen[later_key].set_index(ID)
    ids = sets['early_status_known'] & set(later.index)
    base = patients.loc[patients[ID].isin(ids)].copy()
    base['_early_status'] = base[ID].map(early._status).astype('Int64')
    base['_' + later_key + '_status'] = base[ID].map(later._status).astype('Int64')
    base['_country'] = np.where(base.country.isin(COUNTRIES), base.country, UNKNOWN_COUNTRY)
    return base.sort_values(ID, kind='stable').reset_index(drop=True)


def selection_maps(selection):
    """Per-patient selected state, day and burden for one policy, keyed by patient identity."""
    chosen = selection['selected']
    early = chosen['early'].set_index(ID)
    year = chosen['year'].set_index(ID)
    burden = selection['burden'].set_index(ID)._burden if len(selection['burden']) else pd.Series(dtype=object)
    empty = pd.Series(dtype=object)
    return {'early_status': early._status, 'year_status': year._status,
            'early_day': early._day if '_day' in early.columns else empty,
            'year_day': year._day if '_day' in year.columns else empty,
            'burden': burden}


def changed(reference, policy, patients_shared, key, labeller=str):
    return int(sum(1 for pid in patients_shared
                   if labeller(reference[key].get(pid)) != labeller(policy[key].get(pid))))


def policy_comparison(reference_selection, reference_sets, selection, sets, applicable):
    """Membership, status, day and burden changes against the reference policy P0.

    Every comparison keeps the patient as the unit, so status, day and burden stay coupled.
    """
    out = {}
    for name in ('early_status_known', 'early_users', 'early_pad_free', 'year_status_known',
                 'paired_early_year', 'early_users_with_year', 'year_padfree_in_early_user_pairs'):
        a, b = reference_sets.get(name, set()), sets.get(name, set())
        out[name] = {'reference_p0': len(a), 'policy': len(b), 'intersection': len(a & b),
                     'entering_under_policy': len(b - a), 'exiting_under_policy': len(a - b)}
    reference, policy = selection_maps(reference_selection), selection_maps(selection)
    shared_early = sorted(reference_sets['early_status_known'] & sets['early_status_known'])
    shared_users = sorted(reference_sets['early_users'] & sets['early_users'])
    comparison = {
        'patients_selected_in_the_early_window_under_both': len(shared_early),
        'early_status_changed': changed(reference, policy, shared_early, 'early_status', state_label),
        'patients_selected_as_early_users_under_both': len(shared_users),
        'year_status_label_changed_including_availability':
            changed(reference, policy, shared_users, 'year_status', state_label),
    }
    if applicable:
        comparison.update(
            selected_early_day_changed=changed(reference, policy, shared_early, 'early_day'),
            selected_year_day_changed=changed(reference, policy,
                                              sorted(reference_sets['year_status_known'] & sets['year_status_known']),
                                              'year_day'),
            coupled_early_burden_level_changed=changed(reference, policy, shared_users, 'burden'))
    else:
        comparison.update(selected_early_day_changed=None, selected_year_day_changed=None,
                          coupled_early_burden_level_changed=None,
                          not_applicable_reason='milestone_rule_has_no_exact_day_or_borrowed_burden')
    out['coupled_patient_changes'] = comparison
    return out


def policy_block(patients, selection, sets, frame, reference_selection, reference_sets, applicable):
    """Complete denominators and comparisons for one policy. No estimate is computed."""
    block = {
        'observation_rule': selection['observation_rule'],
        'window_diagnostics': selection['window_diagnostics'],
        'burden_diagnostics': selection['burden_diagnostics'],
        'excluded_patients_before_selection': int(selection['excluded_patients']),
        'denominators': {name: len(ids) for name, ids in sorted(sets.items())},
        'early_status_counts': {'pad_use': len(sets['early_users']), 'pad_free': len(sets['early_pad_free'])},
        'comparison_with_p0': policy_comparison(reference_selection, reference_sets, selection, sets, applicable),
    }
    if applicable:
        block['four_level_burden'] = level_counts(frame._burden, BURDEN_LEVELS)
        block['burden_by_country_by_year_state'] = burden_country_outcome_counts(frame, 'year')
    paired = paired_frame(patients, selection, sets, 'year')
    block['all_paired_transitions_including_early_pad_free'] = transition_counts(paired, 'year')
    block['early_user_subset_year_counts'] = {
        'early_users_with_year_status': int(frame._year_status.notna().sum()),
        'year_pad_free': int(frame._year_status.eq(1).sum()),
        'year_pad_use': int(frame._year_status.eq(0).sum())}
    return block


# --------------------------------------------------------------------------------------
# Public derivation API
# --------------------------------------------------------------------------------------

def derive(patients, events, milestones, policy='P0', cohort=cohort_mod.DEFAULT_COHORT):
    """Complete in-memory derivation for one policy. Frames are never emitted from here."""
    filtered_patients, eligible_robotic, cohort_info = cohort_mod.apply_cohort(
        patients, cohort, id_col=ID)
    annotated, robotic, valid, candidate = candidate_frame(filtered_patients, events)
    require(robotic == eligible_robotic, 'COHORT_ROBOTIC_SET_MISMATCH')
    reference = {key: select_window(candidate, window, 'nearest')[0] for key, window in WINDOWS.items()}
    excluded, date_diagnostics = (date_impact_patients(annotated, robotic, candidate, reference)
                                  if policy == 'P4' else (frozenset(), {}))
    selection = policy_selection(candidate, policy, excluded, milestones, robotic)
    sets = cohort_sets(selection)
    frame = patient_frame(filtered_patients, selection, sets)
    return {'policy': policy, 'selection': selection, 'sets': sets, 'patients': frame,
            'candidate': candidate, 'valid': valid, 'annotated': annotated, 'robotic': robotic,
            'date_impact_diagnostics': date_diagnostics, 'cohort': cohort_info}


def source_derive(root=RELEASE, policy='P0', cohort=cohort_mod.DEFAULT_COHORT,
                  include_all_operations=False):
    """Bound-source derivation API for a downstream local statistics script.

    Verifies all bound input hashes before and after reading, exactly as the CLI does.
    Returns in-memory patient frames. The caller must not print or export them.
    """
    root = bind_root(root)
    before = bound_inputs()
    table_manifest(root)
    patients, events, milestones = read_core_tables(root)
    result = derive(patients, events, milestones, policy, cohort=cohort)
    if include_all_operations and cohort != cohort_mod.COHORT_ALL_OPERATIONS:
        all_result = derive(patients, events, milestones, policy, cohort=cohort_mod.COHORT_ALL_OPERATIONS)
        result['all_operations_patients'] = all_result['patients']
    after = bound_inputs()
    require(before == after == 122, 'BOUND_INPUT_VERIFICATION_FAILURE')
    result['source_verification'] = {'bound_inputs_before': before, 'bound_inputs_after': after,
                                     'mismatches': 0, 'source_writes_performed': False}
    return result


# --------------------------------------------------------------------------------------
# Aggregate record
# --------------------------------------------------------------------------------------

def derivation_blocks(patients, events, milestones, cohort=cohort_mod.DEFAULT_COHORT,
                      record_gates=False, check_gates=True):
    """Every derived aggregate block. A pure function of the three core source tables."""
    reference = derive(patients, events, milestones, 'P0', cohort=cohort)
    candidate, valid, robotic = reference['candidate'], reference['valid'], reference['robotic']
    sets, frame = reference['sets'], reference['patients']
    offsets = offset_agreement(candidate)
    require(offsets['recomputed_day_disagrees_with_released_offset'] == 0, 'OFFSET_AGREEMENT_FAILURE')

    ladder = {'all_released': len(patients), 'robotic': len(robotic),
              'valid_dated_postoperative_continence': len(valid),
              'early_status_known': len(sets['early_status_known']), 'early_users': len(sets['early_users']),
              'paired_early_year': len(sets['paired_early_year']),
              'early_users_with_year': len(sets['early_users_with_year']),
              'year_padfree_observed_pairs': len(sets['year_padfree_in_early_user_pairs'])}

    low, high, _ = WINDOWS['year']
    year_window_rows = candidate.loc[candidate._day.between(low, high) & candidate._status.notna()]
    without = sets['early_users_without_year']
    conflict_only = len(without & set(year_window_rows[ID]))
    no_record = len(without) - conflict_only

    early_selected = reference['selection']['selected']['early']
    historical = early_selected.loc[early_selected[ID].isin(sets['early_users_with_year']), '_burden']
    historical_counts = {level: int(historical.eq(level).sum()) for level in HISTORICAL_ROW_BURDEN_226}

    if check_gates:
        observed_gates = {
            **ladder,
            'early_users_without_year_status': len(without),
            'no_valid_year_window_observation': no_record,
            'conflicting_year_window_evidence_only': conflict_only,
            'historical_selected_row_burden_one': historical_counts['one'],
            'historical_selected_row_burden_two_or_more': historical_counts['two_or_more'],
            'historical_selected_row_burden_quantity_uncertain': historical_counts['quantity_uncertain'],
        }
        cohort_mod.check_or_record_gates(
            '06_derive_observed_assessments', cohort, observed_gates, record=record_gates)

    # The generalised selector must reproduce the accepted window selection exactly.
    for key, window in WINDOWS.items():
        require(eda.WINDOWS[key] == window, 'WINDOW_CONTRACT_MISMATCH')
        accepted = eda.select_window(candidate, window)[0]
        mine = reference['selection']['selected'][key]
        require(set(zip(accepted[ID], accepted._date, accepted._status, accepted.event_index))
                == set(zip(mine[ID], mine._date, mine._status, mine.event_index)),
                'ACCEPTED_SELECTION_IDENTITY_MISMATCH')

    paired_year = paired_frame(patients, reference['selection'], sets, 'year')
    policies = {}
    for policy in POLICIES:
        if policy == 'P0':
            result, applicable = reference, True
        else:
            result = derive(patients, events, milestones, policy, cohort=cohort)
            applicable = policy != 'P5'
        policies[policy] = policy_block(patients, result['selection'], result['sets'], result['patients'],
                                        reference['selection'], sets, applicable)
        if policy == 'P4':
            policies[policy]['date_impact_diagnostics'] = result['date_impact_diagnostics']
        if policy == 'P5':
            policies[policy]['milestone_note'] = ('Released milestone observation rule. No exact-window early burden '
                                                  'is borrowed and no day is selected.')
    canonical_ladder = (dict(CANONICAL_LADDER) if cohort == cohort_mod.COHORT_ALL_OPERATIONS
                        else dict(ladder))
    return {
        'recomputed_day_versus_released_offset': offsets,
        'baseline_reconciliation': {
            'cohort_ladder': ladder, 'canonical_ladder': canonical_ladder, 'ladder_matches_accepted_counts': True,
            'early_users_without_year_status': {'total': len(without),
                                                'no_valid_year_window_observation': no_record,
                                                'conflicting_year_window_evidence_only': conflict_only,
                                                'reconciles': True},
            'historical_selected_row_burden_in_observed_pairs': historical_counts,
            'historical_inventory_status': ('Superseded row-based inventory retained as historical accounting only. '
                                            'It is not an adjudicated exposure and is not used for any grouping here.'),
            'generalised_selector_reproduces_accepted_selection': True},
        'p0_reference': {
            'window_diagnostics': reference['selection']['window_diagnostics'],
            'burden_diagnostics': reference['selection']['burden_diagnostics'],
            'four_level_burden': burden_block(frame),
            'burden_by_country_by_year_state': burden_country_outcome_counts(frame, 'year'),
            'all_paired_transitions_including_early_pad_free': transition_counts(paired_year, 'year'),
            'early_user_subset_year_transitions': transition_counts(
                paired_year.loc[paired_year._early_status.eq(0)], 'year'),
            'six_month_pairs': later_window_block(frame, 'six'),
            'two_year_pairs': later_window_block(frame, 'two_year'),
            'six_month_all_paired_transitions': transition_counts(
                paired_frame(patients, reference['selection'], sets, 'six'), 'six'),
            'two_year_all_paired_transitions': transition_counts(
                paired_frame(patients, reference['selection'], sets, 'two_year'), 'two_year'),
            'record_availability': availability_block(frame, conflict_only, no_record),
            'country_consistency': country_consistency(frame, candidate),
            'age_evidence': age_block(frame),
            'coarse_surgery_year_counts': {str(int(year)): int(n) for year, n
                                           in sorted(frame._coarse_surgery_year.dropna().astype(int)
                                                     .value_counts().items())},
            'coarse_surgery_year_unknown': int(frame._coarse_surgery_year.isna().sum()),
        },
        'policies': policies,
        'feasibility_count_gates': feasibility_block(frame),
        'definitions': {
            'units': 'Patients, observation rows and patient-day groups are distinct and are never summed together.',
            'selection': ('Nearest target day inside the window, ties to the earlier day, then released event index. '
                          'A patient-day holding both explicit states is unavailable; P0 permits another consistent '
                          'day in the same window and flags the re-entry.'),
            'status': 'Explicit Boolean pad status only, after the accepted D1 endpoint and device mask.',
            'burden': ('Four-level documentary category from every status-consistent record on the selected early '
                       'day. Independent bound fallbacks, no interval intersection, no event index and no later '
                       'outcome participate. Devices never supply ordinary-pad quantities.'),
            'unresolved_quantity_evidence': ('Invalid selected-day quantity evidence or valid intervals with an '
                                             'empty intersection, including disjoint exact counts.'),
            'nonconflicting_quantity_uncertain': ('Compatible or all-missing evidence, including a crossing range '
                                                  'beside a precise record. Missing rows never veto a compatible '
                                                  'known category.'),
            'policies': ('P1 window restriction, P2 first usable day, P3 narrow windows, P4 date-impact exclusion '
                         'including nonselected uncertain dates, P5 released milestone rule. Each rebuilds the full '
                         'robotic cohort. Differences combine measurement and population change.'),
            'availability': 'Record availability among observed care, not a response probability among eligible patients.',
            'unknown': 'Unknown country or age remains unknown. Nothing is recoded and nothing is imputed.',
        },
        'limitations': [
            'Derivation only. No probability, confidence interval, hypothesis test, model fit or bound on real data.',
            'The opportunity-conditioned original primary remains held because administrative eligibility A is unknown.',
            'Selected assessments describe documented care. They do not establish the true state on any day.',
            'Policy differences are not confidence bounds, identification bounds or a range of clinical truth.',
            'Count gates describe adequacy under the amendment rule. They license no model and no claim.',
            'The superseded row-based burden inventory is historical accounting only.',
        ],
        'privacy': {'aggregate_only': True, 'identifiers_emitted': False, 'exact_dates_emitted': False,
                    'row_exports': False, 'narratives_emitted': False, 'raw_dictionary_examples_emitted': False,
                    'private_source_filenames_emitted': False, 'patient_frames_returned_in_memory_only': True},
        'probabilities_or_intervals_emitted': False, 'model_fitted': False,
        'clinical_estimates_computed': False, 'candidate_membership_changed': False, 'science_lock': False,
    }


def serialise(result):
    return json.dumps(strict(result), sort_keys=True, indent=2, allow_nan=False) + '\n'


def build_report(root, cohort=cohort_mod.DEFAULT_COHORT, record_gates=False):
    """Bound-source aggregate record: provenance, then every derived block.

    Bound input hashes are verified before and after reading. Every derived quantity is
    recomputed from reversed source tables and must agree exactly, so no aggregate here
    can depend on source row order.
    """
    cohort_mod.validate_cohort_name(cohort)
    root = bind_root(root)
    manifest_path = HERE / 'evidence/SOURCE_MANIFEST.json'
    before = bound_inputs(manifest_path)
    tables, parity = table_manifest(root)
    patients, events, milestones = read_core_tables(root)
    _, _, cohort_info = cohort_mod.apply_cohort(patients, cohort, id_col=ID)
    blocks = derivation_blocks(patients, events, milestones, cohort=cohort, record_gates=record_gates)
    reversed_blocks = derivation_blocks(
        patients.iloc[::-1], events.iloc[::-1], milestones.iloc[::-1], cohort=cohort, record_gates=False)
    require(serialise(blocks) == serialise(reversed_blocks), 'SOURCE_ROW_ORDER_INVARIANCE_FAILURE')
    after = bound_inputs(manifest_path)
    offsets = blocks.pop('recomputed_day_versus_released_offset')
    code_files = ['00_preflight.py', '02_eda_authoritative.py', '03_conflict_impact.py',
                  '06_derive_observed_assessments.py']
    if cohort == cohort_mod.COHORT_COMPLETED_WINDOW:
        code_files.append('cohort.py')
    report = {
        'record_kind': 'aggregate_source_native_observed_assessment_derivation_only',
        'scope': ('Documented assessment selection, four-level documentary burden and named policy rebuilds. '
                  'No probability, interval, hypothesis test, model fit, weight, imputation or bound on real data.'),
        'authority': ('The user-designated release is authoritative and read only. Validity, D1 status masking, '
                      'window grouping and tie order are imported unchanged from the accepted 02 and 03 scripts. '
                      'The governing design is the observed-assessment amendment, which authorises no clinical fact.'),
        'source_root': str(RELEASE.relative_to(WORKSPACE)),
        'source_verification': {'bound_inputs_before': before, 'bound_inputs_after': after, 'mismatches': 0,
                                'manifest_sha256': eda.sha(manifest_path), 'release_tables': len(tables),
                                'format_parity_tables': len(parity), 'format_parity': parity,
                                'source_writes_performed': False,
                                'recomputed_day_versus_released_offset': offsets},
        'source_row_order_reversal_aggregate_invariance': True,
        'software': {'python': sys.version.split()[0], 'pandas': pd.__version__, 'numpy': np.__version__,
                     'duckdb': eda.duckdb.__version__},
        'code_sha256': {name: eda.sha(HERE / 'scripts' / name) for name in code_files},
        'test_sha256': eda.sha(TEST_SCRIPT),
        'additional_test_sha256': {'test_06_derivation_edge_regression.py':
                                    eda.sha(HERE / 'tests/test_06_derivation_edge_regression.py')},
        'context_sha256': {name: eda.sha(HERE / name) for name in
                           ('ANALYSIS_AMENDMENT_OBSERVED_ASSESSMENTS.md', 'ANALYSIS_PLAN.md',
                            'evidence/EDA_AUTHORITATIVE_RELEASE.json', 'evidence/CONFLICT_IMPACT.json')},
        'context_provenance_note': ('Only accepted, settled context is bound by hash. The concurrently owned '
                                    'covariate EDA record is not bound, so its expected rebuilds cannot fail this '
                                    'verification for reasons unrelated to this derivation.'),
        'source_table_sha256': {name: eda.sha(root / 'tables' / (name + '.csv')) for name in CORE_TABLES},
        'allowlist': {'tables': list(CORE_TABLES),
                      'columns': {k: list(v) for k, v in ALLOWLISTED_COLUMNS.items()},
                      'release_tables': tables},
        **blocks,
    }
    if cohort == cohort_mod.COHORT_COMPLETED_WINDOW:
        report['cohort'] = cohort_info
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description='Aggregate observed-assessment derivation.')
    ap.add_argument('--root', type=Path, default=RELEASE)
    ap.add_argument('--output', type=Path, default=None)
    ap.add_argument('--verify', action='store_true',
                    help='Recompute and compare with the saved record. Never writes.')
    cohort_mod.add_cohort_args(ap)
    args = ap.parse_args(argv)
    raw_output = args.output if args.output is not None else cohort_mod.output_path(OUTPUT, args.cohort)
    output = raw_output.absolute()
    require(not output.is_symlink()
            and output.resolve().is_relative_to(HERE / 'evidence')
            and not output.resolve().is_relative_to(RELEASE), 'OUTPUT_SCOPE_FAILURE')
    if not args.verify:
        cohort_mod.assert_writable_output(output)
    result = build_report(args.root, cohort=args.cohort, record_gates=args.record_gates)
    text = serialise(result)
    max_float_diff = 0.0
    if args.verify:
        require(output.is_file(), 'SAVED_DERIVATION_MISMATCH')
        if args.cohort == cohort_mod.COHORT_ALL_OPERATIONS:
            ok, _reason, max_float_diff = cohort_mod.compare_records_ignoring_provenance(
                json.loads(output.read_text()), json.loads(text),
                ignore_keys=('code_sha256', 'software'), float_tol=1e-12)
            require(ok, 'SAVED_DERIVATION_MISMATCH')
        else:
            require(output.read_text() == text, 'SAVED_DERIVATION_MISMATCH')
    else:
        output.write_text(text)
    print(json.dumps({
        'status': 'saved_derivation_recomputed_exactly' if args.verify else 'aggregate_derivation_written',
        'cohort': args.cohort,
        'bound_inputs': result['source_verification']['bound_inputs_before'],
        'format_parity_tables': result['source_verification']['format_parity_tables'],
        'cohort_ladder': result['baseline_reconciliation']['cohort_ladder'],
        'four_level_burden': result['p0_reference']['four_level_burden']['early_users'],
        'policies': sorted(result['policies']),
        'max_float_diff': max_float_diff,
        'output_sha256': eda.sha(output)}))


def safe_main(argv=None):
    try:
        with warnings.catch_warnings():
            # Parser and source exceptions can quote private field content. Never surface them.
            warnings.simplefilter('ignore')
            main(argv)
        return 0
    except cohort_mod.GateError as error:
        print(error.code, file=sys.stderr)
        return 1
    except RuntimeError as error:
        code = str(error)
        if code and code.replace('_', '').isalnum() and code.isupper():
            print(code, file=sys.stderr)
        else:
            print('OBSERVED_ASSESSMENT_DERIVATION_FAILED_SOURCE_DETAIL_WITHHELD', file=sys.stderr)
        return 1
    except Exception:
        print('OBSERVED_ASSESSMENT_DERIVATION_FAILED_SOURCE_DETAIL_WITHHELD', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
