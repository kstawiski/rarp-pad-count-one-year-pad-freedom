#!/usr/bin/env python3
"""Deterministic aggregate analysis-set accounting. Sources read only. No clinical estimate.

The release is opened through an explicit table and column allowlist and only aggregate counts
leave this module. No probability, interval, bound value, weight, model, hypothesis test or
patient-level record is produced. The accepted candidate selection semantics are imported from
scripts/02_eda_authoritative.py rather than restated, so this module describes the executed
460/226/86 screen and its residuals instead of replacing it.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import re
import sys
import warnings
import pandas as pd
import duckdb

HERE = Path(__file__).resolve().parents[1]
EDA_SCRIPT = HERE / 'scripts/02_eda_authoritative.py'
TEST_SCRIPT = HERE / 'tests/test_03_analysis_set_accounting.py'


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Accepted selection semantics are reused, never re-implemented.
eda = load_module(EDA_SCRIPT, 'm1_eda_authoritative')
WORKSPACE, RELEASE, ID = eda.WORKSPACE, eda.RELEASE, eda.ID

ALLOWLISTED_TABLES = ('patient_wide', 'continence_events_long', 'continence_milestones_long')
ALLOWLISTED_COLUMNS = {
    'patient_wide': ('master_patient_id', 'country', 'robotic_platform_used'),
    'continence_events_long': ('master_patient_id', 'event_index', 'country', 'surgery_date',
                               'event_date', 'event_phase', 'pad_free', 'pads_per_day',
                               'pads_per_day_min', 'pads_per_day_max', 'diaper_count_min',
                               'safety_pad_documented', 'usable_continence_observation',
                               'event_date_ambiguous', 'event_date_precision_source_derived'),
    'continence_milestones_long': ('master_patient_id', 'milestone_month', 'pad_free', 'observed'),
}
PRIMARY_WINDOWS = ('early', 'year')
SECONDARY_WINDOWS = ('six', 'two_year', 'early_narrow', 'year_narrow')
# Inclusive coverage day each outcome window would require before an opportunity disposition exists.
OUTCOME_COVERAGE_DAY = {'year': 425, 'year_narrow': 395, 'six': 210, 'two_year': 790}
BURDEN_LEVELS = ('one', 'two_or_more', 'quantity_uncertain')
UNITS = {
    'patients': 'Distinct pseudonymous patient identities. The inference unit.',
    'observation_rows': 'Released continence observation rows. Repeated observations, not patients.',
    'patient_day_groups': 'Patient-by-calendar-day groups of known-status rows. Not unique patients.',
    'ladder_stages': 'Ordered stages of the accepted candidate denominator ladder.',
    'source_files': 'Bound release input files verified by manifest hash and size.',
    'tables': 'Released tables.',
    'comparisons': 'Paired set comparisons between two documented observation rules.',
    'checks': 'Deterministic reconciliation checks against accepted saved aggregates.',
    'postoperative_days': 'Whole days after surgery, recomputed from the released event and surgery dates.',
}
DIMENSIONLESS_KEYS = ('ladder_position',)
FORBIDDEN_KEY_SUFFIX = ('_probability', '_percent', '_percentage', '_fraction', '_rate',
                        '_interval', '_odds', '_weight', '_estimate', '_ci')


def count(n, unit):
    if unit not in UNITS:
        raise RuntimeError('UNIT_NOT_DECLARED')
    return {'n': int(n), 'unit': unit}


def category(key, label, n, unit, klass):
    return {'key': key, 'label': label, 'count': count(n, unit), 'class': klass}


def ledger(key, label, denominator_key, denominator_n, unit, categories, note):
    total = sum(c['count']['n'] for c in categories)
    if total != int(denominator_n):
        raise RuntimeError('PARTITION_NOT_EXHAUSTIVE')
    return {'key': key, 'label': label,
            'denominator': {'key': denominator_key, 'count': count(denominator_n, unit)},
            'categories': categories, 'category_sum': count(total, unit),
            'mutually_exclusive': True, 'exhaustive_within_denominator': True, 'note': note}


def burden(frame):
    """Reproduces the executed D3 candidate burden mapping (00_preflight.py continence)."""
    point = eda.numeric(frame['pads_per_day'])
    lower = eda.numeric(frame['pads_per_day_min']).fillna(point)
    upper = eda.numeric(frame['pads_per_day_max']).fillna(point)
    out = pd.Series('quantity_uncertain', index=frame.index, dtype=object)
    out[lower.eq(1) & upper.eq(1)] = 'one'
    out[lower.ge(2)] = 'two_or_more'
    return out


def window_sets(eligible, window):
    """Accepted screening plus the identity sets the aggregate ladder does not expose."""
    lo, hi, _ = window
    in_window = eligible.loc[eligible._day.between(lo, hi)]
    known = in_window.loc[in_window._status.notna()]
    conflicted = known.groupby([ID, '_date'])._status.transform('nunique').gt(1)
    selected, diagnostics = eda.select_window(eligible, window)
    conflict_days = set(zip(known.loc[conflicted, ID], known.loc[conflicted, '_date']))
    if conflict_days & set(zip(selected[ID], selected._date)):
        # D5 forbids choosing between conflicting same-day states. Asserted, never assumed.
        raise RuntimeError('SELECTED_ROW_ON_CONFLICTING_DAY')
    return {'in_window_ids': set(in_window[ID]), 'known_ids': set(known[ID]),
            'conflict_ids': set(known.loc[conflicted, ID]), 'selected_ids': set(selected[ID]),
            'selected': selected, 'diagnostics': diagnostics}


def disposition(cohort, event_ids, valid_ids, sets):
    """Ordered cascade. Every identity lands in exactly one bucket, with no unnamed residual."""
    buckets, remaining = {}, set(cohort)
    stages = (('no_continence_event_row', event_ids),
              ('no_candidate_valid_observation', valid_ids),
              ('no_candidate_valid_observation_in_window', sets['in_window_ids']),
              ('in_window_without_explicit_pad_free_status', sets['known_ids']),
              ('conflicting_day_omitted_no_alternative', sets['selected_ids']))
    for key, available in stages:
        buckets[key] = remaining - available
        remaining = remaining & available
    buckets['selected'] = remaining
    if sum(len(v) for v in buckets.values()) != len(set(cohort)):
        raise RuntimeError('PARTITION_NOT_EXHAUSTIVE')
    return buckets


def milestone_sets(milestones, robotic_ids):
    m = milestones.loc[milestones[ID].isin(robotic_ids)]
    observed = m.loc[eda.truth(m.observed)]
    if observed.duplicated([ID, 'milestone_month']).any():
        raise RuntimeError('DUPLICATE_MILESTONE')
    three = observed.loc[observed.milestone_month.eq('3')]
    twelve = observed.loc[observed.milestone_month.eq('12')]
    three_users = set(three.loc[eda.false(three.pad_free), ID])
    twelve_ids = set(twelve[ID])
    paired_users = three_users & twelve_ids
    late_free = paired_users & set(twelve.loc[eda.truth(twelve.pad_free), ID])
    return {'released_milestone_3m_pad_user': three_users,
            'released_milestone_12m_observed': twelve_ids,
            'released_milestone_3_12_paired_pad_user': paired_users,
            'released_milestone_3_12_late_pad_free': late_free}


def compare_rules(name, exact_ids, released_ids, exact_label, released_label):
    both, exact_only, released_only = exact_ids & released_ids, exact_ids - released_ids, released_ids - exact_ids
    entry = {'comparison': name, 'exact_set': exact_label, 'released_set': released_label,
             'exact_total': count(len(exact_ids), 'patients'),
             'released_total': count(len(released_ids), 'patients'),
             'both': count(len(both), 'patients'),
             'exact_only': count(len(exact_only), 'patients'),
             'released_only': count(len(released_only), 'patients'),
             'union': count(len(exact_ids | released_ids), 'patients'),
             'equivalent_definitions': False,
             'interpretation': 'Two documented observation rules over the same release. '
                               'A difference is rule dependence, not a numerical correction, '
                               'and neither total may be substituted for the other.'}
    if entry['both']['n'] + entry['exact_only']['n'] != entry['exact_total']['n']:
        raise RuntimeError('RULE_COMPARISON_NOT_EXHAUSTIVE')
    if entry['both']['n'] + entry['released_only']['n'] != entry['released_total']['n']:
        raise RuntimeError('RULE_COMPARISON_NOT_EXHAUSTIVE')
    if entry['both']['n'] + entry['exact_only']['n'] + entry['released_only']['n'] != entry['union']['n']:
        raise RuntimeError('RULE_COMPARISON_NOT_EXHAUSTIVE')
    return entry


def check(receipts, name, saved, recomputed, unit, token):
    if int(saved) != int(recomputed):
        raise RuntimeError(token)
    receipts.append({'check': name, 'saved': count(saved, unit),
                     'recomputed': count(recomputed, unit), 'match': True})


def carries_number(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, dict) and 'n' in value


def guard_types(payload):
    """No non-integer number, and no numeric value under an estimate-shaped key."""
    def walk(node):
        if isinstance(node, bool) or node is None or isinstance(node, str):
            return
        if isinstance(node, int):
            return
        if isinstance(node, float):
            raise RuntimeError('ESTIMATE_LEAK')
        if isinstance(node, dict):
            for key, value in node.items():
                if not isinstance(key, str):
                    raise RuntimeError('OUTPUT_CONTRACT_FAILURE')
                if key.endswith(FORBIDDEN_KEY_SUFFIX) and carries_number(value):
                    raise RuntimeError('ESTIMATE_LEAK')
                walk(value)
            return
        if isinstance(node, list):
            for value in node:
                walk(value)
            return
        raise RuntimeError('OUTPUT_CONTRACT_FAILURE')
    walk(payload)


def guard_units(payload):
    """Every emitted integer sits in a dict that declares one of the declared units."""
    def walk(node, holder):
        if isinstance(node, bool) or node is None or isinstance(node, str):
            return
        if isinstance(node, int):
            if holder is None or holder.get('unit') not in UNITS:
                raise RuntimeError('UNIT_NOT_DECLARED')
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in DIMENSIONLESS_KEYS and isinstance(value, int) and not isinstance(value, bool):
                    continue
                walk(value, node)
            return
        if isinstance(node, list):
            for value in node:
                walk(value, None)
    walk(payload, None)


def guard_text(text, exemptions):
    if '%' in text:
        raise RuntimeError('ESTIMATE_LEAK')
    scan = text
    for token in exemptions:
        scan = scan.replace(token, '')
    if 'mpid' in scan.lower() or re.search(r'\d{4}-\d{2}-\d{2}', scan):
        raise RuntimeError('PRIVACY_GUARD_FAILURE')


def read_allowlisted(root, table):
    if table not in ALLOWLISTED_TABLES:
        raise RuntimeError('TABLE_NOT_ALLOWLISTED')
    return pd.read_csv(root / 'tables' / (table + '.csv'), dtype=str, keep_default_na=False,
                       usecols=list(ALLOWLISTED_COLUMNS[table]))


def accepted_references():
    paths = {'ladder': HERE / 'analysis/preparation/denominator_ladder.csv',
             'eda': HERE / 'evidence/EDA_AUTHORITATIVE_RELEASE.json',
             'feasibility': HERE / 'evidence/FEASIBILITY.json',
             'preparation': HERE / 'analysis/preparation/summary.json'}
    ladder = pd.read_csv(paths['ladder'], dtype=str, keep_default_na=False)
    saved = {name: json.loads(path.read_text()) for name, path in paths.items() if name != 'ladder'}
    hashes = {name: eda.sha(path) for name, path in sorted(paths.items())}
    return ladder, saved, hashes


def build_payload(patients, events, milestones, ladder, saved):
    if not patients[ID].ne('').all() or not patients[ID].is_unique:
        raise RuntimeError('PATIENT_KEY_CONTRACT_FAILURE')
    robotic_flag = eda.bool_quality(patients.robotic_platform_used)
    robotic_ids = set(patients.loc[eda.truth(patients.robotic_platform_used), ID])
    rows = events.loc[events[ID].isin(robotic_ids)]
    prepared, valid = eda.prepare(rows)
    eligible = prepared.loc[valid].copy()
    contradictions = eda.pad_masks(eligible)[0]['pad_free_quantity_or_device_contradiction']
    eligible.loc[contradictions, '_status'] = pd.NA
    eligible['_burden'] = burden(eligible)

    windows = {name: window_sets(eligible, window) for name, window in eda.WINDOWS.items()}
    early, year = windows['early']['selected'], windows['year']['selected']
    pairs = early.merge(year, on=ID, suffixes=('_early', '_year'), validate='one_to_one')
    early_users = early.loc[early._status.eq(0)]
    early_user_ids = set(early_users[ID])
    observed_users = pairs.loc[pairs._status_early.eq(0)]
    year_free_ids = set(observed_users.loc[observed_users._status_year.eq(1), ID])
    event_ids, valid_ids = set(rows[ID]), set(eligible[ID])

    values = {'unique_released_patients': len(patients), 'robotic_procedures': len(robotic_ids),
              'valid_dated_postoperative_continence_rows': len(eligible),
              'known_early_status_days_60_120': len(early), 'early_pad_users': len(early_users),
              'paired_early_and_year': len(pairs), 'early_pad_users_with_year_status': len(observed_users),
              'year_pad_free_in_observed_pairs': len(year_free_ids)}
    for name in SECONDARY_WINDOWS:
        values['window_' + name + '_status_known'] = len(windows[name]['selected'])
        values['window_' + name + '_pad_users'] = int(windows[name]['selected']._status.eq(0).sum())
    released = milestone_sets(milestones, robotic_ids)
    values['milestone_3m_observed'] = int((eda.truth(milestones.loc[milestones[ID].isin(robotic_ids)].observed)
                                           & milestones.loc[milestones[ID].isin(robotic_ids)].milestone_month.eq('3')).sum())
    values['milestone_12m_observed'] = len(released['released_milestone_12m_observed'])

    receipts = []
    stages = []
    for row in ladder.itertuples():
        check(receipts, 'ladder_stage_' + row.stage_key, int(row.candidate_n), values[row.stage_key],
              'observation_rows' if row.unit == 'rows' else 'patients', 'DENOMINATOR_LADDER_MISMATCH')
        stages.append({'ladder_position': int(row.stage_order), 'section': row.ladder_section, 'key': row.stage_key,
                       'label': row.stage_label,
                       'count': count(values[row.stage_key], 'observation_rows' if row.unit == 'rows' else 'patients'),
                       'class': 'released_milestone_screen' if row.ladder_section == 'released_milestone'
                       else ('source_native_diagnostic' if int(row.stage_order) <= 2 else 'candidate_screen'),
                       'accepted_saved': count(int(row.candidate_n), 'observation_rows' if row.unit == 'rows' else 'patients'),
                       'reproduced': True})

    cohort = saved['eda']['cohort']
    for key, unit in (('released_patients', 'patients'), ('robotic_patients', 'patients'),
                      ('candidate_valid_postoperative_rows', 'observation_rows')):
        recomputed = {'released_patients': len(patients), 'robotic_patients': len(robotic_ids),
                      'candidate_valid_postoperative_rows': len(eligible)}[key]
        check(receipts, 'eda_cohort_' + key, cohort[key], recomputed, unit, 'ACCEPTED_EDA_MISMATCH')
    for name, window in windows.items():
        accepted = saved['eda']['same_day']['windows'][name]
        for key, unit in (('selected_patients', 'patients'), ('selected_pad_users', 'patients'),
                          ('selected_pad_free', 'patients'), ('conflict_groups', 'patient_day_groups'),
                          ('conflict_patients', 'patients'), ('conflict_member_rows', 'observation_rows'),
                          ('patients_without_alternative_after_conflict_day_omission', 'patients')):
            check(receipts, 'eda_window_' + name + '_' + key, accepted[key], window['diagnostics'][key],
                  unit, 'ACCEPTED_EDA_MISMATCH')
        check(receipts, 'window_' + name + '_conflict_identities', accepted['conflict_patients'],
              len(window['conflict_ids']), 'patients', 'ACCEPTED_EDA_MISMATCH')

    inventory = saved['eda']['candidate_observation_inventory']
    check(receipts, 'eda_inventory_early_users', inventory['early_users'], len(early_users), 'patients', 'ACCEPTED_EDA_MISMATCH')
    check(receipts, 'eda_inventory_with_year_status', inventory['with_year_status'], len(observed_users), 'patients', 'ACCEPTED_EDA_MISMATCH')
    check(receipts, 'eda_inventory_without_year_status', inventory['without_year_status'],
          len(early_users) - len(observed_users), 'patients', 'ACCEPTED_EDA_MISMATCH')

    feasibility = saved['feasibility']['feasibility']
    exact = feasibility['exact_early_year']
    for key, recomputed in (('paired', len(pairs)), ('early_pad_users_with_year', len(observed_users)),
                            ('year_pad_free', len(year_free_ids)), ('early_pad_users_total', len(early_users)),
                            ('loss_of_pad_freedom', int((pairs._status_early.eq(1) & pairs._status_year.eq(0)).sum()))):
        check(receipts, 'feasibility_exact_early_year_' + key, exact[key], recomputed, 'patients',
              'ACCEPTED_FEASIBILITY_MISMATCH')

    burden_counts, burden_free = {}, {}
    for level in BURDEN_LEVELS:
        subset = observed_users.loc[observed_users._burden_early.eq(level)]
        burden_counts[level] = len(subset)
        burden_free[level] = int(subset._status_year.eq(1).sum())
        accepted = feasibility['exact_by_burden'][level]
        check(receipts, 'feasibility_burden_' + level + '_paired_pad_users', accepted['paired_pad_users'],
              burden_counts[level], 'patients', 'ACCEPTED_FEASIBILITY_MISMATCH')
        check(receipts, 'feasibility_burden_' + level + '_year_pad_free', accepted['year_pad_free'],
              burden_free[level], 'patients', 'ACCEPTED_FEASIBILITY_MISMATCH')

    countries = sorted(set(early_users.country))
    country_rows = {}
    for name in countries:
        users = early_users.loc[early_users.country.eq(name)]
        observed = observed_users.loc[observed_users.country_early.eq(name)]
        country_rows[name] = {'early_users': len(users), 'with_year_status': len(observed),
                              'without_year_status': len(users) - len(observed),
                              'year_pad_free': int(observed._status_year.eq(1).sum())}
        if name in inventory['by_country']:
            for key in ('early_users', 'with_year_status', 'without_year_status'):
                check(receipts, 'eda_country_' + name.replace(' ', '_') + '_' + key,
                      inventory['by_country'][name][key], country_rows[name][key], 'patients',
                      'ACCEPTED_EDA_MISMATCH')
        if name in feasibility['exact_by_country']:
            check(receipts, 'feasibility_country_' + name.replace(' ', '_') + '_paired_pad_users',
                  feasibility['exact_by_country'][name]['paired_pad_users'],
                  country_rows[name]['with_year_status'], 'patients', 'ACCEPTED_FEASIBILITY_MISMATCH')
            check(receipts, 'feasibility_country_' + name.replace(' ', '_') + '_year_pad_free',
                  feasibility['exact_by_country'][name]['year_pad_free'], country_rows[name]['year_pad_free'],
                  'patients', 'ACCEPTED_FEASIBILITY_MISMATCH')

    comparisons = [
        compare_rules('early_pad_user', early_user_ids, released['released_milestone_3m_pad_user'],
                      'exact_window_early_pad_user', 'released_milestone_3m_pad_user'),
        compare_rules('year_assessment_present', windows['year']['selected_ids'],
                      released['released_milestone_12m_observed'],
                      'exact_window_year_selected', 'released_milestone_12m_observed'),
        compare_rules('early_pad_user_with_year', set(observed_users[ID]),
                      released['released_milestone_3_12_paired_pad_user'],
                      'exact_window_paired_pad_user', 'released_milestone_3_12_paired_pad_user'),
        compare_rules('year_pad_free', year_free_ids, released['released_milestone_3_12_late_pad_free'],
                      'exact_window_year_pad_free', 'released_milestone_3_12_late_pad_free')]
    accepted_comparisons = {entry['comparison']: entry for entry in saved['preparation']['released_milestone_reconciliation']}
    for entry in comparisons:
        accepted = accepted_comparisons[entry['comparison']]
        for key, saved_key in (('exact_total', 'exact_n'), ('released_total', 'released_n'), ('both', 'both_n'),
                               ('exact_only', 'exact_only_n'), ('released_only', 'released_only_n'), ('union', 'union_n')):
            check(receipts, 'milestone_' + entry['comparison'] + '_' + key, accepted[saved_key],
                  entry[key]['n'], 'patients', 'MILESTONE_RECONCILIATION_MISMATCH')

    early_flow = disposition(robotic_ids, event_ids, valid_ids, windows['early'])
    year_flow = disposition(early_user_ids, event_ids, valid_ids, windows['year'])
    early_retained = windows['early']['conflict_ids'] & windows['early']['selected_ids']
    year_retained = windows['year']['conflict_ids'] & windows['year']['selected_ids']

    ledgers = {}
    ledgers['L1_released_patient_platform_partition'] = ledger(
        'L1_released_patient_platform_partition', 'All released prostatectomy patients by robotic platform flag',
        'unique_released_patients', len(patients), 'patients', [
            category('robotic_platform_used_true', 'Robotic platform flag explicitly true',
                     robotic_flag['true'], 'patients', 'source_native_diagnostic'),
            category('robotic_platform_used_false', 'Robotic platform flag explicitly false',
                     robotic_flag['false'], 'patients', 'source_native_diagnostic'),
            category('robotic_platform_used_missing', 'Robotic platform flag blank',
                     robotic_flag['missing'], 'patients', 'source_native_diagnostic'),
            category('robotic_platform_used_other_nonblank', 'Robotic platform flag present but not a Boolean token',
                     robotic_flag['other_nonblank'], 'patients', 'source_native_diagnostic')],
        'Released-field partition. Only the explicitly true group enters the candidate ladder.')

    ledgers['L2_robotic_early_window_disposition'] = ledger(
        'L2_robotic_early_window_disposition', 'Robotic patients by early-window candidate screening outcome',
        'robotic_procedures', len(robotic_ids), 'patients', [
            category('no_continence_event_row', 'No continence observation row of any kind',
                     len(early_flow['no_continence_event_row']), 'patients', 'source_native_diagnostic'),
            category('no_candidate_valid_observation', 'Has rows, none candidate-valid dated postoperative usable',
                     len(early_flow['no_candidate_valid_observation']), 'patients', 'candidate_screen'),
            category('no_candidate_valid_observation_in_window', 'Candidate-valid rows exist, none on days 60 to 120',
                     len(early_flow['no_candidate_valid_observation_in_window']), 'patients', 'candidate_screen'),
            category('in_window_without_explicit_pad_free_status', 'In-window rows exist without an explicit pad-free state',
                     len(early_flow['in_window_without_explicit_pad_free_status']), 'patients', 'candidate_screen'),
            category('conflicting_day_omitted_no_alternative', 'Every in-window known-status day was self-contradictory',
                     len(early_flow['conflicting_day_omitted_no_alternative']), 'patients', 'candidate_screen'),
            category('selected', 'Early status selected, days 60 to 120 nearest day 90',
                     len(early_flow['selected']), 'patients', 'candidate_screen')],
        'Ordered cascade over robotic patients. The first four categories are the named '
        'missing-or-invalid-eligibility residual that the aggregate ladder does not expose. '
        'Conflict-day omission removes the day only; the identity stays visible here and its true '
        'state remains unresolved under D5.')

    ledgers['L3_early_selected_status_partition'] = ledger(
        'L3_early_selected_status_partition', 'Selected early assessments by documented pad state',
        'known_early_status_days_60_120', len(early), 'patients', [
            category('early_pad_user', 'Documented pad use at the selected early assessment',
                     len(early_users), 'patients', 'candidate_screen'),
            category('early_pad_free', 'Documented pad freedom at the selected early assessment',
                     int(early._status.eq(1).sum()), 'patients', 'candidate_screen')],
        'Documentation states at one selected assessment, not adjudicated clinical status.')

    ledgers['L4_early_pad_user_year_disposition'] = ledger(
        'L4_early_pad_user_year_disposition', 'Early candidate pad users by year-window screening outcome',
        'early_pad_users', len(early_users), 'patients', [
            category('no_continence_event_row', 'No continence observation row of any kind',
                     len(year_flow['no_continence_event_row']), 'patients', 'source_native_diagnostic'),
            category('no_candidate_valid_observation', 'No candidate-valid dated postoperative usable row',
                     len(year_flow['no_candidate_valid_observation']), 'patients', 'candidate_screen'),
            category('no_candidate_valid_observation_in_window', 'Candidate-valid rows exist, none on days 305 to 425',
                     len(year_flow['no_candidate_valid_observation_in_window']), 'patients', 'candidate_screen'),
            category('in_window_without_explicit_pad_free_status', 'In-window rows exist without an explicit pad-free state',
                     len(year_flow['in_window_without_explicit_pad_free_status']), 'patients', 'candidate_screen'),
            category('conflicting_day_omitted_no_alternative', 'Every in-window known-status day was self-contradictory',
                     len(year_flow['conflicting_day_omitted_no_alternative']), 'patients', 'candidate_screen'),
            category('year_status_observed', 'Year status selected, days 305 to 425 nearest day 365',
                     len(year_flow['selected']), 'patients', 'candidate_screen')],
        'The first five categories are the named year-status-missing residual and sum to the '
        'early pad users without year status. Missing year status is an observation state under an '
        'ascertainment process of unknown extent, never an outcome and never incontinence.')

    ledgers['L5_observed_pair_year_status'] = ledger(
        'L5_observed_pair_year_status', 'Early candidate pad users with year status by documented year state',
        'early_pad_users_with_year_status', len(observed_users), 'patients', [
            category('year_pad_free', 'Documented pad freedom at the selected year assessment',
                     len(year_free_ids), 'patients', 'candidate_screen'),
            category('year_not_pad_free', 'Documented pad use at the selected year assessment',
                     len(observed_users) - len(year_free_ids), 'patients', 'candidate_screen')],
        'Candidate observed-pair inventory only. No opportunity-eligible denominator has been established, '
        'so this partition does not estimate the original opportunity-conditioned primary. Separately '
        'defined observed-assessment analyses require their own explicit analysis contract.')

    ledgers['L6_paired_set_early_status'] = ledger(
        'L6_paired_set_early_status', 'Patients with both a selected early and a selected year assessment',
        'paired_early_and_year', len(pairs), 'patients', [
            category('early_pad_user', 'Documented early pad use',
                     len(observed_users), 'patients', 'candidate_screen'),
            category('early_pad_free_then_year_pad_free', 'Documented early pad freedom retained at the year assessment',
                     int((pairs._status_early.eq(1) & pairs._status_year.eq(1)).sum()), 'patients', 'candidate_screen'),
            category('early_pad_free_then_year_pad_use', 'Documented early pad freedom followed by documented year pad use',
                     int((pairs._status_early.eq(1) & pairs._status_year.eq(0)).sum()), 'patients', 'candidate_screen')],
        'The third category shows the state is not absorbing. It is a documentation transition, not a '
        'measured recovery or relapse time.')

    ledgers['L7_observed_pair_burden_inventory'] = ledger(
        'L7_observed_pair_burden_inventory', 'Early burden category of the selected early row among observed pairs',
        'early_pad_users_with_year_status', len(observed_users), 'patients',
        [category(level, 'Early burden category ' + level, burden_counts[level], 'patients', 'candidate_screen')
         for level in BURDEN_LEVELS],
        'Candidate observed-pair inventory only. These strata were visible before specification and '
        'are result-informed, never prospectively prespecified. The uncertain group is never '
        'relabelled into a burden level.')

    ledgers['L8_country_inventory'] = ledger(
        'L8_country_inventory', 'Early candidate pad users by released country of the selected early row',
        'early_pad_users', len(early_users), 'patients',
        [category(name, 'Early candidate pad users in ' + name, country_rows[name]['early_users'],
                  'patients', 'candidate_screen') for name in countries],
        'Country is the released contextual stratum of the selected early observation.')

    nested = {
        'burden_year_status': {level: {
            'observed_pairs': count(burden_counts[level], 'patients'),
            'year_pad_free': count(burden_free[level], 'patients'),
            'year_not_pad_free': count(burden_counts[level] - burden_free[level], 'patients'),
            'class': 'candidate_screen'} for level in BURDEN_LEVELS},
        'country_year_status': {name: {
            'early_users': count(country_rows[name]['early_users'], 'patients'),
            'with_year_status': count(country_rows[name]['with_year_status'], 'patients'),
            'without_year_status': count(country_rows[name]['without_year_status'], 'patients'),
            'year_pad_free': count(country_rows[name]['year_pad_free'], 'patients'),
            'year_not_pad_free': count(country_rows[name]['with_year_status'] - country_rows[name]['year_pad_free'], 'patients'),
            'class': 'candidate_screen'} for name in countries},
        'note': 'Nested inventories inside L4, L5, L7 and L8. Their denominators differ from the '
                'ladder denominators and they must not be summed across ledgers.'}
    for level in BURDEN_LEVELS:
        entry = nested['burden_year_status'][level]
        if entry['year_pad_free']['n'] + entry['year_not_pad_free']['n'] != entry['observed_pairs']['n']:
            raise RuntimeError('PARTITION_NOT_EXHAUSTIVE')
    if sum(nested['burden_year_status'][level]['year_pad_free']['n'] for level in BURDEN_LEVELS) != len(year_free_ids):
        raise RuntimeError('PARTITION_NOT_EXHAUSTIVE')
    for name in countries:
        entry = nested['country_year_status'][name]
        if entry['with_year_status']['n'] + entry['without_year_status']['n'] != entry['early_users']['n']:
            raise RuntimeError('PARTITION_NOT_EXHAUSTIVE')
    if sum(nested['country_year_status'][name]['with_year_status']['n'] for name in countries) != len(observed_users):
        raise RuntimeError('PARTITION_NOT_EXHAUSTIVE')

    unresolved = {
        'rule': 'D5. Conflict-day omission is candidate screening only. Patient identity remains '
                'unresolved even when another day in the same window is selected.',
        'early_window': {
            'conflict_identities': count(len(windows['early']['conflict_ids']), 'patients'),
            'omitted_no_alternative_absent_from_selection': count(
                len(windows['early']['conflict_ids'] - windows['early']['selected_ids']), 'patients'),
            'retained_via_alternative_day_identity_unresolved': count(len(early_retained), 'patients'),
            'retained_and_early_pad_user': count(len(early_retained & early_user_ids), 'patients'),
            'retained_and_year_status_observed': count(len(early_retained & set(observed_users[ID])), 'patients'),
            'retained_and_year_pad_free': count(len(early_retained & year_free_ids), 'patients')},
        'year_window': {
            'conflict_identities': count(len(windows['year']['conflict_ids']), 'patients'),
            'omitted_no_alternative_absent_from_selection': count(
                len(windows['year']['conflict_ids'] - windows['year']['selected_ids']), 'patients'),
            'omitted_no_alternative_among_early_pad_users': count(
                len((windows['year']['conflict_ids'] - windows['year']['selected_ids']) & early_user_ids), 'patients'),
            'retained_via_alternative_day_identity_unresolved': count(len(year_retained), 'patients'),
            'retained_and_early_pad_user_with_year_status': count(len(year_retained & set(observed_users[ID])), 'patients'),
            'retained_and_year_pad_free': count(len(year_retained & year_free_ids), 'patients')},
        'overlap_note': 'These identities are already inside the ledger categories above. They are a '
                        'flag on membership, not an additional partition, and must not be added to any '
                        'ledger total.',
        'class': 'candidate_screen'}
    if unresolved['early_window']['omitted_no_alternative_absent_from_selection']['n'] != len(early_flow['conflicting_day_omitted_no_alternative']):
        raise RuntimeError('PARTITION_NOT_EXHAUSTIVE')

    screening = {}
    for name, window in windows.items():
        lo, hi, target = eda.WINDOWS[name]
        selected = window['selected']
        screening[name] = {
            'role': 'primary_candidate_screening' if name in PRIMARY_WINDOWS else 'secondary_candidate_screening',
            'window_days_inclusive': {'from': count(lo, 'postoperative_days'),
                                      'to': count(hi, 'postoperative_days'),
                                      'nearest_target': count(target, 'postoperative_days')},
            'selected_patients': count(len(selected), 'patients'),
            'selected_pad_users': count(int(selected._status.eq(0).sum()), 'patients'),
            'selected_pad_free': count(int(selected._status.eq(1).sum()), 'patients'),
            'known_status_identities_before_conflict_day_omission': count(len(window['known_ids']), 'patients'),
            'conflicting_patient_day_groups': count(window['diagnostics']['conflict_groups'], 'patient_day_groups'),
            'conflicting_identities': count(len(window['conflict_ids']), 'patients'),
            'conflicting_member_rows': count(window['diagnostics']['conflict_member_rows'], 'observation_rows'),
            'omitted_no_alternative': count(len(window['conflict_ids'] - window['selected_ids']), 'patients'),
            'retained_via_alternative_day': count(len(window['conflict_ids'] & window['selected_ids']), 'patients'),
            'selected_row_on_conflicting_day': count(0, 'patients'),
            'class': 'candidate_screen',
            'interpretation': 'Candidate screening only. Not an estimate and not an adjudicated endpoint.'}
        if name in OUTCOME_COVERAGE_DAY:
            screening[name]['opportunity'] = {
                'required_inclusive_coverage_through_postoperative_day':
                    count(OUTCOME_COVERAGE_DAY[name], 'postoperative_days'),
                'disposition': 'unknown_opportunity', 'confirmed_inclusive_close_available': False}
        else:
            screening[name]['opportunity'] = {
                'role': 'exposure_window_not_an_outcome_opportunity_window',
                'disposition': 'unknown_opportunity', 'confirmed_inclusive_close_available': False}
        if screening[name]['known_status_identities_before_conflict_day_omission']['n'] != \
                len(selected) + screening[name]['omitted_no_alternative']['n']:
            raise RuntimeError('PARTITION_NOT_EXHAUSTIVE')

    contract = {
        'scope': 'Uncomputable coverage-based quantities in this preparation contract refer to the original '
                 'administrative-opportunity-conditioned targets. They do not prohibit separately defined '
                 'observed-assessment extensions. Unknown clinical facts are not supplied by either target.',
        'classes': {
            'source_native_diagnostic': 'Counted directly from released fields of the allowlisted tables '
                                        'without any analysis-window selection rule.',
            'candidate_screen': 'Produced by the accepted exact-window candidate screening rule under D3, '
                                'D5 and D6. Candidate screening only. Membership is not adjudicated and no '
                                'selected date is a recovery time.',
            'released_milestone_screen': 'Produced by the released milestone labels. A different documented '
                                         'observation rule, not a correction of the exact-window rule.',
            'uncomputable_pending_coverage_confirmation': 'Requires an accountable inclusive administrative '
                                                          'observation-close date and source assignment per '
                                                          'setting. Not derivable from any released field.',
            'uncomputable_pending_factual_adjudication': 'Requires a source-linked, separately confirmed '
                                                         'per-case disposition. Not derivable by rule.'},
        'quantities': [
            {'key': 'unique_released_patients', 'class': 'source_native_diagnostic', 'unit': 'patients',
             'does_not_establish': 'Eligibility, follow-up coverage or outcome ascertainment.'},
            {'key': 'robotic_procedures', 'class': 'source_native_diagnostic', 'unit': 'patients',
             'does_not_establish': 'A platform contrast or platform comparability.'},
            {'key': 'valid_dated_postoperative_continence_rows', 'class': 'candidate_screen', 'unit': 'observation_rows',
             'does_not_establish': 'Patient counts. Rows are repeated observations.'},
            {'key': 'known_early_status_days_60_120', 'class': 'candidate_screen', 'unit': 'patients',
             'does_not_establish': 'That the selected day is a validated assessment point.'},
            {'key': 'early_pad_users', 'class': 'candidate_screen', 'unit': 'patients',
             'does_not_establish': 'An opportunity-eligible exposure denominator.'},
            {'key': 'paired_early_and_year', 'class': 'candidate_screen', 'unit': 'patients',
             'does_not_establish': 'Complete follow-up or an absorbing recovered state.'},
            {'key': 'early_pad_users_with_year_status', 'class': 'candidate_screen', 'unit': 'patients',
             'does_not_establish': 'Representativeness of all early users. Observation may be related to status.'},
            {'key': 'year_pad_free_in_observed_pairs', 'class': 'candidate_screen', 'unit': 'patients',
             'does_not_establish': 'A population recovery frequency, continence, or absence of leakage.'},
            {'key': 'early_pad_users_without_year_status', 'class': 'candidate_screen', 'unit': 'patients',
             'does_not_establish': 'An outcome. Missing year status is never read as pad use.'},
            {'key': 'observed_pair_burden_inventory', 'class': 'candidate_screen', 'unit': 'patients',
             'does_not_establish': 'A prespecified stratification. These counts were visible before specification.'},
            {'key': 'country_inventory', 'class': 'candidate_screen', 'unit': 'patients',
             'does_not_establish': 'A source-system assignment or a setting-level coverage boundary.'},
            {'key': 'released_milestone_screen_totals', 'class': 'released_milestone_screen', 'unit': 'patients',
             'does_not_establish': 'A correction of, or a substitute for, the exact-window counts.'},
            {'key': 'conflicting_patient_day_groups', 'class': 'source_native_diagnostic', 'unit': 'patient_day_groups',
             'does_not_establish': 'Source-event identity, unique patients, or the true state on that day.'}],
        'uncomputable': [
            {'key': 'administrative_opportunity_eligible_denominator', 'class': 'uncomputable_pending_coverage_confirmation',
             'required_fact': 'Inclusive administrative observation-close date and exhaustive patient and source '
                              'assignment for each source system.', 'owner': 'accountable source custodian per setting'},
            {'key': 'observed_status_response_share', 'class': 'uncomputable_pending_coverage_confirmation',
             'required_fact': 'The same coverage boundary, because system non-coverage and patient non-assessment '
                              'are otherwise mixed inside the missing year status.', 'owner': 'accountable source custodian per setting'},
            {'key': 'identification_bound_values', 'class': 'uncomputable_pending_coverage_confirmation',
             'required_fact': 'An opportunity-eligible denominator, plus recorded manager and clinical-investigator '
                              'approval before any bound is emitted.', 'owner': 'manager with accountable clinical investigator'},
            {'key': 'inverse_observation_weighted_quantity', 'class': 'uncomputable_pending_coverage_confirmation',
             'required_fact': 'An opportunity-eligible target population and its positivity check.',
             'owner': 'manager with accountable clinical investigator'},
            {'key': 'primary_conditional_quantity_given_exposure_opportunity_and_observation',
             'class': 'uncomputable_pending_coverage_confirmation',
             'required_fact': 'Confirmed coverage through the end of postoperative day 425 for the settings in scope.',
             'owner': 'accountable source custodian, then manager with accountable clinical investigator'},
            {'key': 'early_burden_contrast', 'class': 'uncomputable_pending_coverage_confirmation',
             'required_fact': 'The same coverage confirmation, and a disposition for burden values on contradicted '
                              'patient-days.', 'owner': 'manager with accountable clinical investigator'},
            {'key': 'true_state_on_conflicting_patient_days', 'class': 'uncomputable_pending_factual_adjudication',
             'required_fact': 'Source-linked evidence and a separately confirmed per-case disposition.',
             'owner': 'continence clinical adjudicator'},
            {'key': 'identity_resolution_for_conflict_day_retained_identities', 'class': 'uncomputable_pending_factual_adjudication',
             'required_fact': 'The same per-case disposition. Selecting another day does not resolve the identity.',
             'owner': 'continence clinical adjudicator'},
            {'key': 'burden_value_on_quantity_contradicted_selected_days', 'class': 'uncomputable_pending_factual_adjudication',
             'required_fact': 'A per-case quantity disposition. Quantity contradictions are inventoried by the '
                              'separate conflict-impact module and are outside this module.',
             'owner': 'continence clinical adjudicator'},
            {'key': 'intervention_history_states', 'class': 'uncomputable_pending_factual_adjudication',
             'required_fact': 'Source review of cancer therapy and each continence-directed class in the four '
                              'D7 ascertainment states.', 'owner': 'clinical adjudicator with source custodian'}],
        'validity': 'Every quantity in this module is a count of released records under a named rule. The '
                    'accounting is unchanged by the estimand decision, so it is valid under the currently '
                    'held primary estimand and under any future transparently named observed-assessment '
                    'addition. It supplies no preference between them.'}

    opportunity = {
        'all_windows': 'unknown_opportunity',
        'opportunity_eligible_denominator_computed': False,
        'primary_estimate': 'held',
        'derivation_performed_here': False,
        'basis': 'No inclusive administrative observation-close date is established or read by this module. '
                 'Release timestamps, file dates, extraction months, the maximum observed date, last '
                 'documented contact and any data cut are not coverage evidence under D8.',
        'reference_record_not_read_by_this_module': 'manuscript1/evidence/SOURCE_COVERAGE_STATUS.json',
        'windows': {name: screening[name]['opportunity'] for name in sorted(screening)}}

    return {
        'record_kind': 'aggregate-only-analysis-set-accounting',
        'scope': 'deterministic-aggregate-accounting-not-clinical-analysis',
        'authority': 'The user-designated released database is authoritative. This module describes the '
                     'executed candidate screen and its residuals. It does not replace, re-adjudicate or '
                     'recertify it, and it changes no membership.',
        'units': UNITS,
        'cohort_ladder': {'stages_checked': count(len(stages), 'ladder_stages'), 'stages': stages,
                          'derived': {
                              'early_pad_users_without_year_status':
                                  count(len(early_users) - len(observed_users), 'patients'),
                              'year_not_pad_free_in_observed_pairs':
                                  count(len(observed_users) - len(year_free_ids), 'patients'),
                              'early_pad_free_selected': count(int(early._status.eq(1).sum()), 'patients')}},
        'ledgers': ledgers,
        'nested_inventories': nested,
        'unresolved_identity_flags': unresolved,
        'rule_comparison': {
            'comparisons_checked': count(len(comparisons), 'comparisons'), 'comparisons': comparisons,
            'statement': 'The exact-window and released-milestone definitions are different documented '
                         'observation rules over the same release. They are not interchangeable, neither '
                         'is a correction of the other, and no total from one rule may be reported '
                         'without the other rule beside it.'},
        'screening_windows': screening,
        'observation_opportunity': opportunity,
        'evidence_contract': contract,
        'reconciliation': {'checks_performed': count(len(receipts), 'checks'), 'all_matched': True,
                           'checks': receipts},
        'definitions': {
            'selection': 'Imported unchanged from scripts/02_eda_authoritative.py. Nearest target day, then '
                         'earlier date, then released event_index for consistent states only.',
            'candidate_valid_observation': 'Positive postoperative day, event_phase postoperative, usable '
                                           'continence observation true, date not ambiguous, released day '
                                           'precision or a blank precision with a valid ISO date.',
            'known_status': 'An explicit pad_free Boolean that is not voided by a pad-free quantity or device '
                            'contradiction. A blank is unknown, never incontinence.',
            'same_day_conflict': 'At least one explicit true and one explicit false pad-free state in one '
                                 'patient-day group. This grouping does not establish source-event identity.',
            'burden': 'Reproduces the executed D3 mapping. Lower is pads_per_day_min with pads_per_day '
                      'fallback, upper is pads_per_day_max with the same fallback, one when lower and upper '
                      'are both 1, two_or_more when lower is at least 2, otherwise quantity_uncertain.',
            'mutually_exclusive_ledger': 'Within one ledger every identity falls in exactly one category and '
                                         'the categories sum to the stated denominator. Ledgers are nested '
                                         'rather than one flat partition, so counts must never be summed '
                                         'across ledgers.'},
        'limitations': [
            'This module resolves no patient status, no burden value and no coverage fact.',
            'Every documented state is the value of a released field on a row chosen by a stated rule. It is '
            'a documentation state, never verified biological status, continence or recovery.',
            'The candidate ladder counts were visible before specification and are result-informed.',
            'Same-day quantity contradictions are inventoried by the separate conflict-impact module and are '
            'deliberately outside this module.',
            'No opportunity disposition, no estimate, no review approval and no lifecycle promotion is supplied.'],
        'privacy': {'aggregate_only': True, 'patient_rows_emitted': False, 'identifiers_emitted': False,
                    'exact_dates_emitted': False, 'narratives_emitted': False,
                    'dictionary_examples_model_read': False,
                    'table_and_column_allowlist_enforced': True},
        'clinical_estimates_computed': False, 'probabilities_or_intervals_emitted': False,
        'candidate_membership_changed': False, 'science_lock': False,
    }


def build_report(root):
    if root.absolute() != RELEASE or root.is_symlink() or root.resolve() != RELEASE:
        raise RuntimeError('SOURCE_ROOT_NOT_BOUND_RELEASE')
    manifest_path = HERE / 'evidence/SOURCE_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    verified_before = eda.verify_sources(manifest)
    release_manifest = json.loads((root / 'MANIFEST.json').read_text())
    if set(release_manifest['tables']) != set(eda.TABLES):
        raise RuntimeError('TABLE_CONTRACT_MISMATCH')
    if not set(ALLOWLISTED_TABLES) <= set(release_manifest['tables']):
        raise RuntimeError('TABLE_NOT_ALLOWLISTED')
    # No source value, private filename or parse exception text leaves this function.
    frames = {table: read_allowlisted(root, table) for table in ALLOWLISTED_TABLES}
    ladder, saved, reference_hashes = accepted_references()
    payload = build_payload(frames['patient_wide'], frames['continence_events_long'],
                            frames['continence_milestones_long'], ladder, saved)
    verified_after = eda.verify_sources(manifest)
    payload['source_root'] = str(RELEASE.relative_to(WORKSPACE))
    payload['allowlist'] = {'tables': list(ALLOWLISTED_TABLES),
                            'columns': {table: list(columns) for table, columns in sorted(ALLOWLISTED_COLUMNS.items())},
                            'released_tables_present': count(len(release_manifest['tables']), 'tables')}
    payload['source_verification'] = {
        'manifest_sha256': eda.sha(manifest_path),
        'verified_inputs_before': count(verified_before, 'source_files'),
        'verified_inputs_after': count(verified_after, 'source_files'),
        'hash_or_size_mismatches': count(0, 'source_files'),
        'table_sha256': {table: eda.sha(root / 'tables' / (table + '.csv')) for table in ALLOWLISTED_TABLES},
        'accepted_reference_sha256': reference_hashes}
    payload['software'] = {'python': sys.version.split()[0], 'pandas': pd.__version__, 'duckdb': duckdb.__version__}
    payload['code'] = {'entry_sha256': eda.sha(Path(__file__).resolve()),
                       'reused_eda_module_sha256': eda.sha(EDA_SCRIPT),
                       'test_sha256': eda.sha(TEST_SCRIPT) if TEST_SCRIPT.is_file() else 'test_file_absent'}
    return payload


def render(payload):
    guard_types(payload)
    guard_units(payload)
    text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n'
    guard_text(text, [payload.get('source_root', ''), RELEASE.name])
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=RELEASE)
    ap.add_argument('--output', type=Path, default=HERE / 'evidence/ANALYSIS_SET_ACCOUNTING.json')
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args(argv)
    output = args.output.absolute()
    if output.is_symlink() or not output.resolve().is_relative_to(HERE) or output.resolve().is_relative_to(RELEASE):
        raise RuntimeError('OUTPUT_SCOPE_FAILURE')
    payload = build_report(args.root)
    text = render(payload)
    if args.verify:
        if output.read_text() != text:
            raise RuntimeError('SAVED_ACCOUNTING_MISMATCH')
    else:
        output.write_text(text)
    print(json.dumps({
        'status': 'saved_accounting_recomputed_exactly' if args.verify else 'aggregate_accounting_written',
        'verified_inputs': payload['source_verification']['verified_inputs_before']['n'],
        'ladder_stages': payload['cohort_ladder']['stages_checked']['n'],
        'reconciliation_checks': payload['reconciliation']['checks_performed']['n'],
        'ledgers': len(payload['ledgers']),
        'rule_comparisons': payload['rule_comparison']['comparisons_checked']['n'],
        'primary_estimate': payload['observation_opportunity']['primary_estimate']}))


def safe_main(argv=None):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            main(argv)
        return 0
    except Exception:
        # Parser and source exceptions may embed private data. Never echo them.
        print('ANALYSIS_SET_ACCOUNTING_FAILED_SOURCE_DETAIL_WITHHELD', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
