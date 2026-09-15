#!/usr/bin/env python3
"""Aggregate descriptive estimation for the observed-assessment amendment of manuscript1.

Estimation only. This script computes documented proportions, one declared burden
contrast, row-conditional transition descriptions and record-availability descriptions
from the patient frames rebuilt by the accepted derivation. It fits no model, performs
no standardisation, computes no P value, applies no weight, imputes nothing and produces
no identification bound.

Every interval comes from the accepted numerical helpers in `05_observed_estimators.py`.
No interval formula is restated here. Every selection, burden and policy rule comes from
`06_derive_observed_assessments.py`. No selection rule is restated here.

Patient-level frames exist only in memory and are never printed, logged or serialised.
No identifier, exact date, narrative, record or private source filename leaves this
module. The saved record is aggregate strict JSON with a flattened view of its own
blocks for table assembly.

Governing design: manuscript1/ANALYSIS_AMENDMENT_OBSERVED_ASSESSMENTS.md. The reported
quantities describe documented care under a declared documentary rule. They are not
treatment effects, not clinical probabilities and not adjudicated patient facts.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import math
import re
import sys
import warnings

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
WORKSPACE = HERE.parent
OUTPUT = HERE / 'evidence/OBSERVED_STATUS_ESTIMATES.json'
DERIVATION_RECORD = HERE / 'evidence/OBSERVED_ASSESSMENT_DERIVATION.json'
TEST_SCRIPT = HERE / 'tests/test_07_observed_status_estimates.py'
GENERIC_FAILURE = 'OBSERVED_STATUS_ESTIMATES_FAILED_SOURCE_DETAIL_WITHHELD'
STABLE_CODE = re.compile(r'^[A-Z0-9_]{4,64}$')
DATE_SHAPED = re.compile(r'\d{4}-\d{2}-\d{2}')


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


E = module('observed_estimators', '05_observed_estimators.py')
D = module('observed_assessment_derivation', '06_derive_observed_assessments.py')

ID = D.ID
RELEASE = D.RELEASE
POLICIES = D.POLICIES
REFERENCE_POLICY = 'P0'
BURDEN_LEVELS = D.BURDEN_LEVELS
COUNTRY_LEVELS = D.COUNTRY_LEVELS
LATER_WINDOWS = D.LATER_WINDOWS
REFERENCE_LATER_WINDOWS = ('six', 'two_year')

# The amendment fixes these. They are read from the helper and re-asserted, never retyped.
CONFIDENCE = E.CONFIDENCE_DEFAULT
BOOTSTRAP_RESAMPLES = E.BOOTSTRAP_RESAMPLES_DEFAULT
BOOTSTRAP_SEED = E.BOOTSTRAP_SEED_DEFAULT
MAX_INVALID_FRACTION = E.MAX_INVALID_FRACTION_DEFAULT
GROUP_A, GROUP_B = 'one', 'two_or_more'

BOUND_INPUT_COUNT = 122
RELEASE_TABLE_COUNT = 17
CANONICAL_BASELINE = {'early_users': 460, 'early_users_with_year': 226,
                      'year_padfree_observed_pairs': 86}
# Binding set declared by the accepted derivation record. A key that appears on one side
# only is itself a mismatch, so a changed derivation binding can never pass unnoticed.
DERIVATION_CODE_BINDINGS = ('00_preflight.py', '02_eda_authoritative.py', '03_conflict_impact.py',
                            '06_derive_observed_assessments.py')
DERIVATION_CONTEXT_BINDINGS = ('ANALYSIS_AMENDMENT_OBSERVED_ASSESSMENTS.md', 'ANALYSIS_PLAN.md',
                               'evidence/EDA_AUTHORITATIVE_RELEASE.json', 'evidence/CONFLICT_IMPACT.json')

WILSON_METHOD = 'wilson_score_two_sided'
DENOMINATOR_MEANING = ('Early pad users under this policy who also have a selected later status. '
                       'The numerator is a selected later pad-free status. Patients without a '
                       'selected later status are described separately as record availability.')


def require(ok, code):
    """Hard contract check. `code` is a stable token that never carries source content."""
    if not ok:
        raise RuntimeError(code)


require(CONFIDENCE == 0.95, 'CONFIDENCE_NOT_THE_ADOPTED_LEVEL')
require(BOOTSTRAP_RESAMPLES == 2000 and BOOTSTRAP_SEED == 20260907, 'BOOTSTRAP_SETTINGS_NOT_ADOPTED')
require(MAX_INVALID_FRACTION == 0.05, 'INVALID_FRACTION_TOLERANCE_NOT_ADOPTED')


# --------------------------------------------------------------------------------------
# Validated analysis units
# --------------------------------------------------------------------------------------

def status_value(value):
    """Strictly binary later status, or None when no later assessment was selected.

    A missing value means no selected assessment. Nothing else is treated as missing and
    nothing malformed is coerced to a status. A Boolean, a finite float, a string or any
    other object is a contract failure, not a pad-use record.
    """
    if isinstance(value, (bool, np.bool_)):
        raise RuntimeError('LATER_STATUS_NOT_BINARY')
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (int, np.integer)):
        number = int(value)
        require(number in (0, 1), 'LATER_STATUS_NOT_BINARY')
        return number
    raise RuntimeError('LATER_STATUS_NOT_BINARY')


def category_value(value, levels, code):
    """A declared stratum label. An undeclared or missing level is never absorbed."""
    require(isinstance(value, str) and value in levels, code)
    return value


def analysis_units(frame, status_column, categories=()):
    """One validated `(stratum, status)` tuple per patient, ready for the helper module.

    Patient uniqueness is asserted here rather than assumed from any upstream frame. The
    key is used only to prove one row per patient and never leaves this function; a
    duplicate or blank key raises a stable code carrying no identifier.
    """
    require(isinstance(frame, pd.DataFrame), 'ANALYSIS_FRAME_NOT_A_FRAME')
    require(ID in frame.columns, 'ANALYSIS_FRAME_MISSING_PATIENT_KEY')
    require(status_column in frame.columns, 'ANALYSIS_FRAME_MISSING_STATUS_COLUMN')
    keys = frame[ID]
    require(keys.notna().all() and keys.astype(str).str.strip().ne('').all(), 'ANALYSIS_UNIT_KEY_BLANK')
    require(keys.is_unique, 'ANALYSIS_UNIT_NOT_UNIQUE')
    for column, _, _ in categories:
        require(column in frame.columns, 'ANALYSIS_FRAME_MISSING_CATEGORY_COLUMN')
    columns = [list(frame[column]) for column, _, _ in categories]
    units = []
    for position, raw in enumerate(list(frame[status_column])):
        status = status_value(raw)
        parts = [category_value(columns[i][position], levels, code)
                 for i, (_, levels, code) in enumerate(categories)]
        units.append(('|'.join(parts) if parts else None, status))
    return units


def counts(units, stratum=None):
    """Numerator and denominator for one stratum. Unselected later status is excluded."""
    denominator = sum(1 for label, status in units if status is not None
                      and (stratum is None or label == stratum))
    numerator = sum(1 for label, status in units if status == 1
                    and (stratum is None or label == stratum))
    return numerator, denominator


def observed_rows(units):
    """Complete patient tuples with a selected later status, in helper input form."""
    return [(label, status) for label, status in units if status is not None]


# --------------------------------------------------------------------------------------
# Intervals from the accepted helper module
# --------------------------------------------------------------------------------------

def finite_or_none(block, keys, code):
    for key in keys:
        value = block.get(key)
        require(value is None or (isinstance(value, float) and math.isfinite(value)), code)
    return block


def interval_block(numerator, denominator, **meta):
    """One Wilson score interval with its stratum labels. Empty strata stay visible.

    A zero denominator returns an explicit not-estimable stratum with null endpoints
    rather than a dropped row, a zero or a nonfinite value.
    """
    block = E.wilson_interval(int(numerator), int(denominator), CONFIDENCE)
    finite_or_none(block, ('estimate', 'lower', 'upper'), 'NONFINITE_PROPORTION_VALUE')
    require(block['estimable'] == (block['denominator'] > 0), 'INTERVAL_ESTIMABLE_STATE_INCONSISTENT')
    require(block['estimable'] or block['not_estimable_reason'] is not None, 'MISSING_NOT_ESTIMABLE_REASON')
    require(block['method'] == WILSON_METHOD, 'UNEXPECTED_INTERVAL_METHOD')
    block.update(meta)
    return block


def stratum_intervals(units, levels, *, stratum_kind, **meta):
    """Every declared level, including levels with no observed patient."""
    return {level: interval_block(*counts(units, level), stratum_kind=stratum_kind, stratum=level, **meta)
            for level in levels}


def proportion_set(frame, window, policy, *, burden_applicable):
    """Later pad-free proportion among selected pairs, overall and by declared stratum."""
    column = '_' + window + '_status'
    meta = {'analysis': 'later_pad_free_among_selected_pairs', 'policy': policy, 'window': window}
    overall = analysis_units(frame, column)
    country = analysis_units(frame, column, (('_country', COUNTRY_LEVELS, 'COUNTRY_LEVEL_NOT_DECLARED'),))
    out = {
        'denominator_definition': DENOMINATOR_MEANING,
        'selected_pairs': counts(overall)[1],
        'later_pad_free_records': counts(overall)[0],
        'overall': interval_block(*counts(overall), stratum_kind='overall', stratum='overall', **meta),
        'by_country': stratum_intervals(country, COUNTRY_LEVELS, stratum_kind='country', **meta),
    }
    if not burden_applicable:
        out['by_four_level_burden'] = {
            'applicable': False,
            'reason': 'milestone_observation_rule_has_no_exact_selected_day_burden',
            'burden_borrowed_from_another_policy': False}
        out['by_burden_and_country'] = dict(out['by_four_level_burden'])
        return out
    burden = analysis_units(frame, column, (('_burden', BURDEN_LEVELS, 'BURDEN_LEVEL_NOT_DECLARED'),))
    joint = analysis_units(frame, column, (('_burden', BURDEN_LEVELS, 'BURDEN_LEVEL_NOT_DECLARED'),
                                           ('_country', COUNTRY_LEVELS, 'COUNTRY_LEVEL_NOT_DECLARED')))
    out['by_four_level_burden'] = stratum_intervals(burden, BURDEN_LEVELS, stratum_kind='four_level_burden', **meta)
    out['by_burden_and_country'] = stratum_intervals(
        joint, tuple(level + '|' + country_level for level in BURDEN_LEVELS for country_level in COUNTRY_LEVELS),
        stratum_kind='four_level_burden_by_country', **meta)
    return out


# --------------------------------------------------------------------------------------
# The declared central contrast
# --------------------------------------------------------------------------------------

def level_population(rows):
    """Every declared burden level with its resampled patient count, zeros included."""
    observed = {level: 0 for level in BURDEN_LEVELS}
    for label, _ in rows:
        require(label in observed, 'BURDEN_LEVEL_NOT_DECLARED')
        observed[label] += 1
    return observed


NO_RESAMPLING_REASONS = ('GROUP_ABSENT_IN_OBSERVED_ROWS', 'NO_ROWS')


def bootstrap_qualification(central):
    """Failed-draw accounting and the reporting rule the amendment attaches to it.

    A contrast with an absent group is never resampled at all. That state is reported as
    an explicit no-resampling stratum with its declared settings, not as zero failures.
    """
    block = central.get('bootstrap')
    if block is None:
        require(not central['estimable'] and central['not_estimable_reason'] in NO_RESAMPLING_REASONS,
                'BOOTSTRAP_BLOCK_MISSING')
        return {'resamples_requested': BOOTSTRAP_RESAMPLES, 'resamples_successful': 0, 'resamples_failed': 0,
                'failed_draw_reasons': {}, 'seed': BOOTSTRAP_SEED,
                'max_invalid_fraction': MAX_INVALID_FRACTION, 'observed_invalid_fraction': None,
                'resampling_performed': False,
                'not_performed_reason': central['not_estimable_reason'],
                'any_failed_draws': False, 'interval_conditional_on_successful_draws': False,
                'interval_held_for_repair_or_method_amendment': False,
                'deterministic_score_interval_reported_alongside': True,
                'reporting_rule': ('A stratum without both declared groups is reported as not estimable. '
                                   'No resampling is attempted and no interval is implied.')}
    require(isinstance(block, dict), 'BOOTSTRAP_BLOCK_MISSING')
    failed = int(block['resamples_invalid'])
    fraction = float(block['observed_invalid_fraction'])
    require(math.isfinite(fraction), 'NONFINITE_INVALID_FRACTION')
    held = (not central['estimable']
            and central['not_estimable_reason'] == 'BOOTSTRAP_INVALID_FRACTION_EXCEEDED')
    return {
        'resamples_requested': int(block['resamples_requested']),
        'resamples_successful': int(block['resamples_successful']),
        'resamples_failed': failed,
        'failed_draw_reasons': block['invalid_reasons'],
        'seed': int(block['seed']),
        'max_invalid_fraction': float(block['max_invalid_fraction']),
        'observed_invalid_fraction': fraction,
        'quantile_rule': block['quantile_rule'],
        'resampling_unit': block['resampling_unit'],
        'resampling_population': block['resampling_population'],
        'resampling_performed': True,
        'any_failed_draws': failed > 0,
        'interval_conditional_on_successful_draws': bool(failed > 0 and central['estimable']),
        'interval_held_for_repair_or_method_amendment': bool(held),
        'deterministic_score_interval_reported_alongside': True,
        'reporting_rule': ('Any failed draw makes the percentile interval conditional on successful draws '
                           'and requires the deterministic score interval beside it. More than the declared '
                           'invalid fraction holds the percentile interval for repair or an explicit method '
                           'amendment. Successful-only resampling is never presented as complete.'),
    }


def burden_contrast(frame, window, policy, *, stratum_kind='overall', stratum='overall', restrict=None):
    """One-pad minus at-least-two-pad documented proportions with its declared intervals.

    The percentile bootstrap resamples whole patients, so early burden and later status
    never separate, and all four declared levels stay in the resampling population. The
    Newcombe score interval is the named deterministic sensitivity, not a replacement
    chosen after seeing a result. Leave-one-patient-out influence is aggregate only.
    """
    working = frame if restrict is None else frame.loc[restrict].copy()
    units = analysis_units(working, '_' + window + '_status',
                           (('_burden', BURDEN_LEVELS, 'BURDEN_LEVEL_NOT_DECLARED'),))
    rows = observed_rows(units)
    central = E.proportion_difference(rows, GROUP_A, GROUP_B, method=E.METHOD_BOOTSTRAP,
                                      confidence=CONFIDENCE, resamples=BOOTSTRAP_RESAMPLES,
                                      seed=BOOTSTRAP_SEED, max_invalid_fraction=MAX_INVALID_FRACTION)
    sensitivity = E.proportion_difference(rows, GROUP_A, GROUP_B, method=E.METHOD_NEWCOMBE,
                                          confidence=CONFIDENCE)
    influence = E.leave_one_out_influence(rows, GROUP_A, GROUP_B)
    for block in (central, sensitivity):
        finite_or_none(block, ('estimate', 'lower', 'upper'), 'NONFINITE_CONTRAST_VALUE')
    finite_or_none(influence, ('base_estimate', 'max_abs_change', 'min_estimate', 'max_estimate'),
                   'NONFINITE_INFLUENCE_VALUE')
    require(central['estimate'] == sensitivity['estimate'], 'CONTRAST_POINT_ESTIMATE_DISAGREEMENT')
    return {
        'analysis': 'one_minus_two_or_more_documented_burden_contrast',
        'policy': policy, 'window': window, 'stratum_kind': stratum_kind, 'stratum': stratum,
        'contrast': 'proportion_one_minus_proportion_two_or_more',
        'group_a': GROUP_A, 'group_b': GROUP_B,
        'analysis_patients': len(rows),
        'declared_level_population': level_population(rows),
        'central_interval_method': E.METHOD_BOOTSTRAP,
        'central': central,
        'interval_method_sensitivity': sensitivity,
        'bootstrap_qualification': bootstrap_qualification(central),
        'leave_one_patient_out_influence': influence,
        'meaning': ('A difference between two rule-defined documented-burden groups. It is not a '
                    'difference between the corresponding unknown true clinical burdens, not an '
                    'adjusted association and not a treatment effect.'),
    }


def country_contrasts(frame, window, policy):
    """The same declared contrast inside every country level, reported for all levels."""
    out = {}
    for level in COUNTRY_LEVELS:
        out[level] = burden_contrast(frame, window, policy, stratum_kind='country', stratum=level,
                                     restrict=frame._country.eq(level))
    out['reporting'] = ('Every country level is reported, including the unknown or other level and any '
                        'not-estimable stratum. These are descriptive stratum-specific contrasts. No '
                        'interaction is tested and no stratum is selected by its result.')
    return out


# --------------------------------------------------------------------------------------
# Transitions
# --------------------------------------------------------------------------------------

def transition_estimates(paired, window, policy):
    """Complete two-by-two documented transitions with row-conditional intervals.

    Both later states are described inside each row, so an initially pad-free patient
    with a later pad-use record is reported as explicitly as the reverse direction. A
    later record does not establish relapse, recovery or any date of change.
    """
    later_column = '_' + window + '_status'
    analysis_units(paired, later_column)
    analysis_units(paired, '_early_status')
    cells = D.transition_counts(paired, window)
    require(int(cells['paired_total']) == len(paired), 'TRANSITION_COUNTS_INCOMPLETE')
    meta = {'analysis': 'transition_row_conditional', 'policy': policy, 'window': window}
    rows = {}
    for early_state, _ in D.EARLY_STATES:
        row = {later_state: int(cells[early_state + '|' + later_state]) for later_state, _ in D.LATER_STATES}
        denominator = sum(row.values())
        rows[early_state] = {
            'row_denominator': denominator,
            'counts': row,
            **{later_state: interval_block(row[later_state], denominator, stratum_kind='transition_row',
                                           stratum=early_state + '->' + later_state, **meta)
               for later_state, _ in D.LATER_STATES},
        }
    return {
        'paired_patients': int(cells['paired_total']),
        'cell_counts': {key: int(value) for key, value in cells.items()},
        'row_conditional': rows,
        'row_denominator_definition': ('Patients in the given selected early-status row who also have a '
                                       'selected later status. Each early-status row has its own denominator.'),
        'includes_initially_pad_free_patients': True,
        'intermediate_visit_requirement': 'none_missing_intermediate_assessments_do_not_prevent_a_pair',
        'meaning': ('Documented state at two selected assessments. It is not a clinical trajectory, not a '
                    'relapse or recovery event and not evidence that pad freedom is permanent.'),
    }


# --------------------------------------------------------------------------------------
# Record availability
# --------------------------------------------------------------------------------------

def availability_units(frame, categories=()):
    """Availability of a selected year status per patient, validated against the status."""
    require('_year_record_available' in frame.columns, 'AVAILABILITY_COLUMN_MISSING')
    flags = list(frame._year_record_available)
    for value in flags:
        require(isinstance(value, (bool, np.bool_)), 'RECORD_AVAILABILITY_NOT_BOOLEAN')
    statuses = analysis_units(frame, '_year_status', categories)
    units = []
    for (label, status), flag in zip(statuses, flags):
        require(bool(flag) == (status is not None), 'AVAILABILITY_AND_STATUS_DISAGREE')
        units.append((label, int(bool(flag))))
    return units


def availability_reasons(result):
    """Why an early user has no selected year status, by patient identity, not subtraction."""
    candidate, sets = result['candidate'], result['sets']
    low, high, _ = D.WINDOWS['year']
    window_rows = candidate.loc[candidate._day.between(low, high) & candidate._status.notna()]
    conflicting = set(window_rows[ID])
    without = sets['early_users'] - sets.get('year_status_known', set())
    return {'without_year_status': len(without),
            'conflicting_year_window_evidence_only': len(without & conflicting),
            'no_valid_year_window_observation': len(without - conflicting),
            'derivation': ('Recomputed from patient identity against the candidate year-window rows. '
                           'Not inferred by subtracting published totals.')}


def record_availability(frame, result, policy):
    """Documented year-record availability among all early pad users under this policy."""
    meta = {'analysis': 'observed_record_availability', 'policy': policy, 'window': 'year'}
    overall = availability_units(frame)
    country = availability_units(frame, (('_country', COUNTRY_LEVELS, 'COUNTRY_LEVEL_NOT_DECLARED'),))
    burden = availability_units(frame, (('_burden', BURDEN_LEVELS, 'BURDEN_LEVEL_NOT_DECLARED'),))
    return {
        'early_users': len(overall),
        'with_year_status': counts(overall)[0],
        'without_year_status': len(overall) - counts(overall)[0],
        'without_year_status_reasons': availability_reasons(result),
        'overall': interval_block(*counts(overall), stratum_kind='overall', stratum='overall', **meta),
        'by_country': stratum_intervals(country, COUNTRY_LEVELS, stratum_kind='country', **meta),
        'by_four_level_burden': stratum_intervals(burden, BURDEN_LEVELS, stratum_kind='four_level_burden', **meta),
        'quantity': 'observed_record_availability',
        'meaning': ('The documented fraction of early pad users with a selected year status. It is not a '
                    'response fraction among administratively eligible patients, not conditional on the '
                    'unknown opportunity A, not a weight and not a missing-outcome bound. Structured blanks '
                    'remain unknown and do not mean never assessed or untreated.'),
        'missingness_causes_asserted': False,
        'covariate_description': ('Age and assessment timing are described in the separate covariate EDA '
                                  'record and are not restated or re-derived here.'),
    }


# --------------------------------------------------------------------------------------
# Model disposition
# --------------------------------------------------------------------------------------

def model_disposition(frame):
    """Current count-gate diagnostics with an explicit not-fitted state and held analyses."""
    gates = D.feasibility_block(frame)
    supported = [entry['key'] for entry in gates['gates'] if entry['passes']]
    return {
        'model_fitted': False,
        'model_standardisation_performed': False,
        'firth_or_any_penalised_fit_performed': False,
        'state': 'explicitly_not_fitted_in_this_analysis',
        'support_label': 'preliminary_count_support_only',
        'burden_levels_retained': list(BURDEN_LEVELS),
        'current_gate_diagnostics': gates,
        'supported_model_candidates': supported,
        'supported_candidate_disposition': ('pending_downstream_implementation' if supported
                                            else 'no_candidate_meets_the_current_count_gates'),
        'outstanding_before_any_fit': [
            'The gate diagnostics come from the current source-verified derivation and are preliminary '
            'structural support only, including actual-subset counts, cells, country support and rank.',
            'A failed structural gate holds its candidate model. No burden level is dropped or merged to rescue it.',
            'Final covariate overlap, functional shape and influence review is a separate outstanding step and '
            'is not satisfied by any count gate.',
        ],
        'held_analyses': [
            'The original opportunity-conditioned primary target P(Y=1 | E=1, A=1, O=1) remains unestimated.',
            'Opportunity-targeted weighting remains held.',
            'Missing-outcome pattern-mixture analyses and identification bounds remain held.',
            'Imputation of the outcome and of early burden remains prohibited.',
        ],
    }


# --------------------------------------------------------------------------------------
# Policy assembly
# --------------------------------------------------------------------------------------

def policy_inputs(patients, events, milestones):
    """Rebuild every named policy over the full cohort. Frames stay in memory only."""
    derived = {}
    for policy in POLICIES:
        result = D.derive(patients, events, milestones, policy)
        result['paired'] = {key: D.paired_frame(patients, result['selection'], result['sets'], key)
                            for key in LATER_WINDOWS if key in result['selection']['selected']}
        derived[policy] = result
    require(set(derived) == set(POLICIES), 'POLICY_SET_INCOMPLETE')
    return derived


def policy_estimates(policy, result, reference):
    """Own denominators, coupled comparisons and estimates for one complete policy."""
    frame, sets = result['patients'], result['sets']
    applicable = policy != 'P5'
    block = {
        'observation_rule': result['selection']['observation_rule'],
        'burden_applicable': applicable,
        'excluded_patients_before_selection': int(result['selection']['excluded_patients']),
        'denominators': {name: len(ids) for name, ids in sorted(sets.items())},
        'early_status_counts': {'pad_use': len(sets['early_users']), 'pad_free': len(sets['early_pad_free'])},
        'comparison_with_p0': D.policy_comparison(reference['selection'], reference['sets'],
                                                  result['selection'], sets, applicable),
        'year_estimates': proportion_set(frame, 'year', policy, burden_applicable=applicable),
        'all_paired_transitions_year': transition_estimates(result['paired']['year'], 'year', policy),
    }
    if applicable:
        block['four_level_burden_counts'] = D.level_counts(frame._burden, BURDEN_LEVELS)
        block['central_burden_contrast'] = burden_contrast(frame, 'year', policy)
    else:
        block['four_level_burden_counts'] = {
            'applicable': False, 'reason': 'milestone_observation_rule_has_no_exact_selected_day'}
        block['central_burden_contrast'] = {
            'applicable': False,
            'reason': 'milestone_observation_rule_has_no_exact_selected_day_burden',
            'burden_borrowed_from_another_policy': False,
            'reported_quantities': 'overall_and_country_status_and_transition_estimates_only'}
    return block


def estimate_blocks(derived, *, baseline=None):
    """Every reported block. A pure function of the rebuilt in-memory policy frames."""
    require(set(derived) == set(POLICIES), 'POLICY_SET_INCOMPLETE')
    reference = derived[REFERENCE_POLICY]
    frame, sets = reference['patients'], reference['sets']
    observed_baseline = {'early_users': len(sets['early_users']),
                         'early_users_with_year': len(sets['early_users_with_year']),
                         'year_padfree_observed_pairs': len(sets['year_padfree_in_early_user_pairs'])}
    if baseline is not None:
        require(observed_baseline == dict(baseline), 'BASELINE_RECONCILIATION_FAILURE')
    policies = {policy: policy_estimates(policy, derived[policy], reference) for policy in POLICIES}
    require(set(policies) == set(POLICIES), 'POLICY_SET_INCOMPLETE')
    p0 = {
        'baseline_counts': observed_baseline,
        'four_level_burden_counts': D.level_counts(frame._burden, BURDEN_LEVELS),
        'country_specific_burden_contrasts': country_contrasts(frame, 'year', REFERENCE_POLICY),
        'observed_record_availability': record_availability(frame, reference, REFERENCE_POLICY),
        'early_user_year_pairs': policies[REFERENCE_POLICY]['year_estimates']['selected_pairs'],
    }
    for window in REFERENCE_LATER_WINDOWS:
        p0[window + '_pairs'] = proportion_set(frame, window, REFERENCE_POLICY, burden_applicable=True)
        p0[window + '_all_paired_transitions'] = transition_estimates(reference['paired'][window], window,
                                                                      REFERENCE_POLICY)
    blocks = {
        'reference_policy': REFERENCE_POLICY,
        'estimand': {
            'target': ('The documented proportion of selected later pad-free status among patients whose '
                       'selected early status documents pad use and who have a selected later status.'),
            'unit': 'one_patient_one_row_per_analysis',
            'confidence': CONFIDENCE,
            'interval': 'wilson_score_two_sided_for_every_proportion',
            'central_contrast': 'one_minus_two_or_more_documented_burden_groups',
            'central_contrast_interval': E.METHOD_BOOTSTRAP,
            'central_contrast_sensitivity': E.METHOD_NEWCOMBE,
            'bootstrap_resamples': BOOTSTRAP_RESAMPLES,
            'bootstrap_seed': BOOTSTRAP_SEED,
            'administrative_opportunity_conditioning': 'none_the_original_A_conditional_target_remains_held',
            'uncertainty_scope': E.UNCERTAINTY_SCOPE,
        },
        'p0_reference': p0,
        'policies': policies,
        'model_disposition': model_disposition(frame),
        'definitions': {
            'selection_and_burden': ('Imported unchanged from the accepted derivation. No selection, day, '
                                     'burden or policy rule is redefined in this estimation script.'),
            'four_level_burden': ('All four declared levels are retained everywhere, including levels with no '
                                  'observed patient. No level is merged, dropped or intersected.'),
            'unknown_country': ('The unknown or other country level is retained in every accounting and in '
                                'every stratum table. Nothing is recoded.'),
            'record_availability': ('Documented availability among observed care, not a response fraction '
                                    'among administratively eligible patients.'),
            'policies': ('P0 is the reference definition. P1 to P5 are complete named alternatives, each '
                         'rebuilt over the full cohort with its own denominators. Differences combine '
                         'measurement and population change and are not bounds of any kind.'),
        },
        'limitations': [
            'Descriptive estimation of documented care. No treatment effect and no causal quantity.',
            'Intervals describe sampling uncertainty only. They do not cover measurement error, date '
            'uncertainty, documentary rule choice or follow-up selection.',
            'A documented-burden contrast compares rule-defined documentary groups, not true clinical burdens.',
            'Policy differences are not confidence bounds, identification bounds or a range of clinical truth.',
            'A later pad-use record after early pad freedom does not establish relapse or any date of change.',
            'No model is fitted here and no count gate licenses one.',
        ],
        'reporting_discipline': {
            'p_values_emitted': False,
            'significance_labelling_applied': False,
            'interval_method_selected_by_result': False,
            'policy_reported_regardless_of_direction': True,
            'empty_strata_retained_as_not_estimable': True,
            'declared_levels_never_silently_removed': True,
            'truth_or_identification_bounds_emitted': False,
            'causal_or_recovery_language_used': False,
        },
        'privacy': {
            'aggregate_only': True, 'identifiers_emitted': False, 'exact_dates_emitted': False,
            'row_exports': False, 'narratives_emitted': False, 'private_source_filenames_emitted': False,
            'patient_frames_held_in_memory_only': True,
            'leave_one_out_output_is_aggregate_only': True,
        },
        'model_fitted': False, 'weights_applied': False, 'imputation_performed': False,
        'bounds_emitted': False, 'science_lock': False,
    }
    blocks['estimate_table'] = estimate_table(blocks)
    return blocks


# --------------------------------------------------------------------------------------
# Flattened view of this record's own blocks
# --------------------------------------------------------------------------------------

TABLE_COLUMNS = ('analysis', 'policy', 'window', 'stratum_kind', 'stratum',
                 'numerator', 'denominator', 'estimate', 'lower', 'upper',
                 'estimable', 'not_estimable_reason')


def collect_intervals(node, found):
    if isinstance(node, dict):
        if node.get('method') == WILSON_METHOD and 'analysis' in node:
            found.append(node)
            return found
        for value in node.values():
            collect_intervals(value, found)
    elif isinstance(node, list):
        for value in node:
            collect_intervals(value, found)
    return found


def estimate_table(blocks):
    """Deterministic tabular view flattened from the same blocks, not a separate analysis."""
    rows = [[block[column] for column in TABLE_COLUMNS] for block in collect_intervals(blocks, [])]
    rows.sort(key=lambda row: tuple(str(value) for value in row[:5]))
    keys = [tuple(row[:5]) for row in rows]
    require(len(set(keys)) == len(keys), 'ESTIMATE_TABLE_KEY_NOT_UNIQUE')
    return {'columns': list(TABLE_COLUMNS), 'rows': rows, 'row_count': len(rows),
            'provenance': 'flattened_from_the_proportion_blocks_of_this_record',
            'contains_patient_rows': False}


# --------------------------------------------------------------------------------------
# Derivation binding verification
# --------------------------------------------------------------------------------------

def binding_expectations():
    """Current hashes of every artefact the accepted derivation record binds."""
    return {'code_sha256': {name: D.eda.sha(HERE / 'scripts' / name) for name in DERIVATION_CODE_BINDINGS},
            'context_sha256': {name: D.eda.sha(HERE / name) for name in DERIVATION_CONTEXT_BINDINGS},
            'test_sha256': D.eda.sha(D.TEST_SCRIPT),
            'additional_test_sha256': {'test_06_derivation_edge_regression.py':
                                       D.eda.sha(HERE / 'tests/test_06_derivation_edge_regression.py')}}


def binding_check(saved, expected):
    """Pure comparison of a saved derivation record against current bindings.

    A key on one side only is a mismatch, so an added, removed or changed binding cannot
    pass. Only workspace artefact names appear in the mismatch tokens.
    """
    mismatches = []
    for group in ('code_sha256', 'context_sha256', 'additional_test_sha256'):
        declared = saved.get(group) or {}
        want = expected.get(group, {})
        require(isinstance(declared, dict), 'DERIVATION_RECORD_BINDING_MALFORMED')
        for name in sorted(set(declared) | set(want)):
            if declared.get(name) != want.get(name):
                mismatches.append(group + ':' + name)
    if saved.get('test_sha256') != expected['test_sha256']:
        mismatches.append('test_sha256')
    verification = saved.get('source_verification') or {}
    for key, value in (('bound_inputs_before', BOUND_INPUT_COUNT), ('bound_inputs_after', BOUND_INPUT_COUNT),
                       ('format_parity_tables', RELEASE_TABLE_COUNT), ('mismatches', 0),
                       ('source_writes_performed', False)):
        if verification.get(key) != value:
            mismatches.append('source_verification:' + key)
    return {'bindings_checked': sorted(set(DERIVATION_CODE_BINDINGS) | set(DERIVATION_CONTEXT_BINDINGS)
                                       | {'test_sha256'} | set(expected.get('additional_test_sha256', {}))),
            'mismatches': mismatches, 'mismatch_count': len(mismatches), 'matches': not mismatches,
            'meaning': ('The estimation record may only be built on a derivation record that matches the '
                        'current derivation code, tests, bound context and input verification.')}


# --------------------------------------------------------------------------------------
# Source-bound record
# --------------------------------------------------------------------------------------

def serialise(result):
    text = json.dumps(D.strict(result), sort_keys=True, indent=2, allow_nan=False) + '\n'
    scan = dict(result) if isinstance(result, dict) else result
    if isinstance(scan, dict) and 'source_root' in scan:
        # The designated release label includes a release date, not a patient date.
        # Exempt only this exact provenance value at this exact top-level key.
        require(scan.pop('source_root') == str(RELEASE.relative_to(WORKSPACE)), 'SOURCE_ROOT_LABEL_MISMATCH')
    require(not DATE_SHAPED.search(json.dumps(D.strict(scan), sort_keys=True, allow_nan=False)),
            'DATE_SHAPED_TOKEN_IN_RECORD')
    E.json_safe(json.loads(text))
    return text


def assert_no_row_export(blocks, identifiers):
    """Prove, rather than declare, that no patient key or date reached the blocks.

    The keys are compared in memory and never emitted. Only the checked and total counts
    are reported, so the guard itself exposes nothing. Keys too short to be compared
    safely are counted but not searched, and the difference stays visible.
    """
    text = json.dumps(D.strict(blocks), sort_keys=True)
    checked = sorted(key for key in identifiers if isinstance(key, str) and len(key) >= 6)
    for key in checked:
        require(key not in text, 'IDENTIFIER_LEAK_IN_RECORD')
    require(not DATE_SHAPED.search(text), 'DATE_SHAPED_TOKEN_IN_RECORD')
    return {'patient_keys_total': len(identifiers), 'patient_keys_searched': len(checked),
            'patient_keys_too_short_to_search': len(identifiers) - len(checked),
            'row_exports_detected': False, 'date_shaped_tokens_detected': False}


def build_record(root=RELEASE, derivation_record=DERIVATION_RECORD):
    """Source-bound estimation record.

    The accepted derivation record is verified against current bindings first, then
    against one exact source recomputation. One verified source snapshot then supports
    every policy: the core tables are read once for this script and every policy is
    rebuilt from those in-memory frames, with no per-policy rehashing of the source.
    """
    root = D.bind_root(root)
    saved_text = derivation_record.read_text()
    check = binding_check(json.loads(saved_text), binding_expectations())
    require(check['matches'], 'DERIVATION_RECORD_BINDING_STALE')
    recomputed = D.build_report(root)
    require(D.serialise(recomputed) == saved_text, 'DERIVATION_RECORD_SOURCE_MISMATCH')
    verification = recomputed['source_verification']
    require(verification['bound_inputs_before'] == verification['bound_inputs_after'] == BOUND_INPUT_COUNT,
            'BOUND_INPUT_VERIFICATION_FAILURE')
    require(verification['format_parity_tables'] == RELEASE_TABLE_COUNT, 'FORMAT_PARITY_COUNT_FAILURE')

    patients, events, milestones = D.read_core_tables(root)
    derived = policy_inputs(patients, events, milestones)
    closing_inputs = D.bound_inputs()
    closing_tables, closing_parity = D.table_manifest(root)
    require(closing_inputs == BOUND_INPUT_COUNT, 'BOUND_INPUT_VERIFICATION_FAILURE')
    require(len(closing_parity) == RELEASE_TABLE_COUNT and len(closing_tables) == RELEASE_TABLE_COUNT,
            'FORMAT_PARITY_COUNT_FAILURE')

    blocks = estimate_blocks(derived, baseline=CANONICAL_BASELINE)
    privacy_scan = assert_no_row_export(blocks, set(patients[ID]))
    return {
        'record_kind': 'aggregate_observed_status_estimates',
        'scope': ('Descriptive proportions, one declared documented-burden contrast, row-conditional '
                  'transition descriptions and record availability. No model fit, standardisation, P value, '
                  'weight, imputation or bound.'),
        'authority': ('Selection, burden and policy rules are imported unchanged from the accepted '
                      'derivation. Intervals come from the accepted numerical helper module. The governing '
                      'design is the observed-assessment amendment, which authorises no clinical fact.'),
        'source_root': str(RELEASE.relative_to(WORKSPACE)),
        'source_verification': {
            'derivation_record_sha256': D.eda.sha(derivation_record),
            'derivation_record_recomputed_exactly_from_source': True,
            'bound_inputs_before': verification['bound_inputs_before'],
            'bound_inputs_after_policy_rebuild': closing_inputs,
            'format_parity_tables_before': verification['format_parity_tables'],
            'format_parity_tables_after_policy_rebuild': len(closing_parity),
            'core_table_reads': 2,
            'core_table_read_note': ('One read inside the exact derivation recomputation and one read for the '
                                     'in-memory policy rebuild. The source is not rehashed per policy.'),
            'source_writes_performed': False,
            'source_table_sha256': recomputed['source_table_sha256'],
        },
        'derivation_binding_verification': check,
        'privacy_scan': privacy_scan,
        'software': {'python': sys.version.split()[0], 'pandas': pd.__version__, 'numpy': np.__version__},
        'code_sha256': {name: D.eda.sha(HERE / 'scripts' / name) for name in
                        ('05_observed_estimators.py', '06_derive_observed_assessments.py',
                         '07_observed_status_estimates.py')},
        'test_sha256': {'test_06_derive_observed_assessments.py': D.eda.sha(D.TEST_SCRIPT),
                        'test_07_observed_status_estimates.py': D.eda.sha(TEST_SCRIPT)},
        'context_sha256': {name: D.eda.sha(HERE / name) for name in
                           ('ANALYSIS_AMENDMENT_OBSERVED_ASSESSMENTS.md', 'ANALYSIS_PLAN.md')},
        **blocks,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='Aggregate observed-status estimation.')
    ap.add_argument('--root', type=Path, default=RELEASE)
    ap.add_argument('--output', type=Path, default=OUTPUT)
    ap.add_argument('--derivation-record', type=Path, default=DERIVATION_RECORD)
    ap.add_argument('--verify', action='store_true',
                    help='Recompute and compare with the saved record. Never writes.')
    args = ap.parse_args(argv)
    output = args.output.absolute()
    require(not output.is_symlink()
            and output.resolve().is_relative_to(HERE / 'evidence')
            and not output.resolve().is_relative_to(RELEASE), 'OUTPUT_SCOPE_FAILURE')
    result = build_record(args.root, args.derivation_record)
    text = serialise(result)
    if args.verify:
        require(output.is_file() and output.read_text() == text, 'SAVED_ESTIMATES_MISMATCH')
    else:
        output.write_text(text)
    print(json.dumps({
        'status': 'saved_estimates_recomputed_exactly' if args.verify else 'aggregate_estimates_written',
        'reference_policy': result['reference_policy'],
        'policies': sorted(result['policies']),
        'selected_pairs': result['policies'][REFERENCE_POLICY]['year_estimates']['selected_pairs'],
        'later_pad_free_records': result['policies'][REFERENCE_POLICY]['year_estimates']['later_pad_free_records'],
        'estimate_table_rows': result['estimate_table']['row_count'],
        'model_fitted': result['model_disposition']['model_fitted'],
        'output_sha256': D.eda.sha(output)}))


def safe_main(argv=None):
    """Stable codes only. A message that is not a declared stable code is never surfaced."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            main(argv)
        return 0
    except (RuntimeError, ValueError) as error:
        message = str(error)
        print(message if STABLE_CODE.match(message) else GENERIC_FAILURE, file=sys.stderr)
        return 1
    except Exception:
        print(GENERIC_FAILURE, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
