#!/usr/bin/env python3
"""One-year daily pad category by three-month pad count (post hoc descriptive analysis).

Follows the switchable cohort definition (`completed_window` default, `all_operations`
optional) and the reference selection and burden rules from scripts 06 and 16.
Aggregate output only. No patient identifier, exact clinical date or narrative is
emitted, and the JSON record is scanned against the patient identity set and date
patterns before saving.

Run from manuscript1/:
  PY=/home/konrad/.venvs/konsta-research-py314/bin/python
  "$PY" -B scripts/18_one_year_pad_category.py --cohort completed_window --record-gates
  "$PY" -B scripts/18_one_year_pad_category.py --cohort completed_window --verify
"""

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
from scipy import stats

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / 'evidence/ONE_YEAR_PAD_CATEGORY.json'
DERIVATION_EVIDENCE = HERE / 'evidence/OBSERVED_ASSESSMENT_DERIVATION.json'
ESTIMATES_EVIDENCE = HERE / 'evidence/OBSERVED_STATUS_ESTIMATES.json'
STRENGTHENING_EVIDENCE = HERE / 'evidence/STRENGTHENING_ANALYSES.json'

DRAWS = 2000
BOOTSTRAP_SEED = 20261121
CONFIDENCE = 0.95
DATE_SHAPED = re.compile(r'\d{4}-\d{2}-\d{2}')

YEAR_CATEGORIES = ('pad_free', 'one', 'two_or_more', 'not_classifiable')
TABLE_A_ORDER = (
    ('pad_free_at_three_months', 'Pad-free at three months'),
    ('one', 'Exactly one pad per day'),
    ('two', 'Exactly two pads per day'),
    ('three_or_more', 'Three or more pads per day'),
    ('two_or_more_unseparated', 'Two or more pads, not separable into two vs three or more'),
    ('nonconflicting_quantity_uncertain', 'Unclear count (nonconflicting quantity uncertain)'),
    ('unresolved_quantity_evidence', 'Conflicting count (unresolved quantity evidence)'),
    ('two_or_more_all', 'Two or more pads, all'),
    ('all_pad_users', 'All men using pads at three months'),
)
TABLE_C_ORDER = (
    ('pad_free_at_three_months', 'Pad-free at three months'),
    ('one', 'Exactly one pad per day'),
    ('two_or_more_all', 'Two or more pads, all'),
)


def fail(code, detail=''):
    print(f'ONE_YEAR_PAD_CATEGORY_FAILED {code} {detail}'.strip(), file=sys.stderr)
    sys.exit(1)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cohort_mod = load('cohort', 'cohort.py')


def wilson_cell(E, n, N):
    """Exact two-sided Wilson score interval via `05_observed_estimators.wilson_interval`."""
    w = E.wilson_interval(int(n), int(N), CONFIDENCE)
    return {
        'n': int(n),
        'N': int(N),
        'proportion': w['estimate'],
        'lower': w['lower'],
        'upper': w['upper'],
        'estimable': w['estimable'],
        'not_estimable_reason': w['not_estimable_reason'],
    }


def armitage(cells, scores):
    """Cochran-Armitage trend test matching `16_strengthening_analyses.armitage`."""
    n = np.array([c['n'] for c in cells], float)
    x = np.array([c['events'] for c in cells], float)
    s = np.array(scores, float)
    total_n = n.sum()
    if total_n <= 0:
        return {'z': None, 'p_two_sided': None, 'estimable': False, 'reason': 'ZERO_DENOMINATOR'}
    p = x.sum() / total_n
    t = np.sum(s * (x - n * p))
    var = p * (1 - p) * (np.sum(n * s ** 2) - np.sum(n * s) ** 2 / total_n)
    if not np.isfinite(var) or var <= 0:
        return {'z': None, 'p_two_sided': None, 'estimable': False, 'reason': 'ZERO_VARIANCE'}
    zval = float(t / math.sqrt(var))
    return {'z': zval, 'p_two_sided': float(2 * stats.norm.sf(abs(zval))), 'estimable': True}


def build_day_groups(d, chosen, candidate):
    """Group status-consistent candidate rows on each patient's selected day."""
    ID = d.ID
    keys = set(zip(chosen[ID], chosen._date))
    member = pd.Series(
        [(p, when) in keys for p, when in zip(candidate[ID], candidate._date)],
        index=candidate.index,
    )
    day_rows = candidate.loc[member].copy()
    mapped = day_rows[ID].map(dict(zip(chosen[ID], chosen._status))).astype('Int64')
    usable = day_rows.loc[day_rows._status.eq(mapped).fillna(False).astype(bool)]
    return {p: g for p, g in usable.groupby(ID, sort=False)}


def three_month_fine_level(d, grouped_early, pid, burden):
    """Split `two_or_more` into `two`, `three_or_more`, and `two_or_more_unseparated` as in script 16."""
    if burden != 'two_or_more':
        return burden
    g = grouped_early.get(pid)
    if g is None or len(g) == 0:
        fail('EARLY_ROWS_MISSING')
    cols = d.quantity_columns(g)
    known = g.index[(cols['informative'] & ~cols['invalid']).to_numpy()]
    lows = [cols['lower'][i] for i in known]
    highs = [cols['upper'][i] for i in known]
    if any(pd.isna(v) or float(v) < 2 for v in lows):
        fail('TWO_OR_MORE_LOWER_BOUND')
    if all(pd.notna(h) and float(lo) == 2.0 and float(h) == 2.0 for lo, h in zip(lows, highs)):
        return 'two'
    if all(float(lo) >= 3.0 for lo in lows):
        return 'three_or_more'
    return 'two_or_more_unseparated'


def classify_one_year_category(d, grouped_year, pid, year_status):
    """Classify a selected one-year assessment following script 16, plus audit against 06."""
    if int(year_status) == 1:
        return 'pad_free', None
    g = grouped_year.get(pid)
    if g is None or len(g) == 0:
        fail('YEAR_ROWS_MISSING')
    yq = d.quantity_columns(g)
    ok = yq['informative'] & ~yq['invalid']
    hi = yq['upper']
    counts = hi.loc[ok & hi.notna()]
    if not len(counts):
        cat_16 = 'not_classifiable'
    elif bool((counts <= 1).all()):
        cat_16 = 'one'
    else:
        cat_16 = 'two_or_more'

    level_06, flags_06, _ = d.classify_day(g)
    cat_06 = level_06 if level_06 in ('one', 'two_or_more') else 'not_classifiable'

    ok_idx = g.index[ok.to_numpy()]
    if bool(yq['invalid'].any()) or not len(ok_idx):
        cat_paren = 'not_classifiable'
    elif all(pd.notna(yq['upper'][i]) and float(yq['upper'][i]) <= 1.0 for i in ok_idx):
        cat_paren = 'one'
    elif all(pd.notna(yq['lower'][i]) and float(yq['lower'][i]) >= 2.0 for i in ok_idx):
        cat_paren = 'two_or_more'
    else:
        cat_paren = 'not_classifiable'

    audit = {
        'cat_16': cat_16,
        'cat_06': cat_06,
        'level_06': level_06,
        'cat_paren': cat_paren,
        'has_invalid': bool(flags_06['invalid_quantity_evidence']),
        'has_incompatible': bool(flags_06['incompatible_valid_intervals']),
        'has_crossing': bool(flags_06['crossing_range_evidence']),
        'has_partial': bool(flags_06['partial_bound_evidence']),
    }
    return cat_16, audit


def summarize_table_rows(E, df, row_specs):
    """Build row-by-column cell summaries with Wilson 95% intervals."""
    out = {}
    for row_key, label, mask in row_specs:
        sub = df.loc[mask]
        N = int(len(sub))
        cols = {
            col: wilson_cell(E, int((sub['_year_cat'] == col).sum()), N)
            for col in YEAR_CATEGORIES
        }
        if sum(cols[col]['n'] for col in YEAR_CATEGORIES) != N:
            fail('ROW_CELL_SUM_MISMATCH', row_key)
        out[row_key] = {'label': label, 'N': N, 'columns': cols}
    return out


def bootstrap_diff(E, rows, group_a, group_b):
    """Whole-patient percentile bootstrap difference with Newcombe score sensitivity."""
    boot = E.proportion_difference(
        rows, group_a, group_b,
        method=E.METHOD_BOOTSTRAP, confidence=CONFIDENCE,
        resamples=DRAWS, seed=BOOTSTRAP_SEED,
    )
    newc = E.proportion_difference(
        rows, group_a, group_b,
        method=E.METHOD_NEWCOMBE, confidence=CONFIDENCE,
    )
    if boot['estimate'] != newc['estimate']:
        fail('CONTRAST_ESTIMATE_MISMATCH', f'{group_a}_vs_{group_b}')
    return {
        'contrast': f'{group_a}_minus_{group_b}',
        'group_a_label': group_a,
        'group_b_label': group_b,
        'estimate': boot['estimate'],
        'bootstrap_lower': boot['lower'],
        'bootstrap_upper': boot['upper'],
        'estimable': boot['estimable'],
        'not_estimable_reason': boot['not_estimable_reason'],
        'newcombe_lower': newc['lower'],
        'newcombe_upper': newc['upper'],
        'group_a': boot['group_a'],
        'group_b': boot['group_b'],
        'bootstrap': boot.get('bootstrap'),
    }


def read_phase1_json(base_path, cohort_name):
    path = cohort_mod.output_path(base_path, cohort_name)
    if not path.is_file():
        fail('PHASE1_RECORD_MISSING', str(path))
    return json.loads(path.read_text())


def verify_phase1_gates(table_a, table_c, paired_users, paired_pad_free, rec06, rec07, rec16):
    """Assert exact agreement with phase 1 derivation, estimates, and script 16 outputs."""
    obs_pairs_06 = rec06['p0_reference']['four_level_burden']['observed_year_pairs']
    early_users_06 = rec06['p0_reference']['four_level_burden']['early_users']
    trans_06 = rec06['p0_reference']['all_paired_transitions_including_early_pad_free']

    est_07_year = rec07['policies']['P0']['year_estimates']
    est_07_trans = rec07['policies']['P0']['all_paired_transitions_year']['cell_counts']

    grad_16 = rec16['gradient']
    social_16 = rec16['outcome_definitions']['social_continence_no_pads_or_at_most_one']

    checks = [
        # Early pad-free row ties to 06, 07, and 16.
        ('pad_free_3m_N_06', table_a['pad_free_at_three_months']['N'],
         int(trans_06['early_pad_free|later_pad_free'] + trans_06['early_pad_free|later_pad_use'])),
        ('pad_free_3m_pf_06', table_a['pad_free_at_three_months']['columns']['pad_free']['n'],
         int(trans_06['early_pad_free|later_pad_free'])),
        ('pad_free_3m_N_07', table_a['pad_free_at_three_months']['N'],
         int(est_07_trans['early_pad_free|later_pad_free'] + est_07_trans['early_pad_free|later_pad_use'])),
        ('pad_free_3m_pf_07', table_a['pad_free_at_three_months']['columns']['pad_free']['n'],
         int(est_07_trans['early_pad_free|later_pad_free'])),
        ('pad_free_3m_N_16', table_a['pad_free_at_three_months']['N'],
         int(grad_16['pad_free_at_three_months']['n'])),
        ('pad_free_3m_pf_16', table_a['pad_free_at_three_months']['columns']['pad_free']['n'],
         int(grad_16['pad_free_at_three_months']['events'])),
        # Fine gradient rows tie to 16.
        ('one_N_16', table_a['one']['N'], int(grad_16['one']['n'])),
        ('one_pf_16', table_a['one']['columns']['pad_free']['n'], int(grad_16['one']['events'])),
        ('two_N_16', table_a['two']['N'], int(grad_16['two']['n'])),
        ('two_pf_16', table_a['two']['columns']['pad_free']['n'], int(grad_16['two']['events'])),
        ('three_N_16', table_a['three_or_more']['N'], int(grad_16['three_or_more']['n'])),
        ('three_pf_16', table_a['three_or_more']['columns']['pad_free']['n'], int(grad_16['three_or_more']['events'])),
        ('unsep_N_16', table_a['two_or_more_unseparated']['N'], int(grad_16['two_or_more_unseparated']['n'])),
        ('unsep_pf_16', table_a['two_or_more_unseparated']['columns']['pad_free']['n'],
         int(grad_16['two_or_more_unseparated']['events'])),
        # All pad users pooled ties to 06 and 07.
        ('all_pad_users_N_06', table_a['all_pad_users']['N'], int(obs_pairs_06['declared_total'])),
        ('all_pad_users_N_07', table_a['all_pad_users']['N'], int(est_07_year['selected_pairs'])),
        ('all_pad_users_pf_07', table_a['all_pad_users']['columns']['pad_free']['n'],
         int(est_07_year['later_pad_free_records'])),
    ]

    for lvl_a, lvl_p1 in (
        ('one', 'one'),
        ('two_or_more_all', 'two_or_more'),
        ('nonconflicting_quantity_uncertain', 'nonconflicting_quantity_uncertain'),
        ('unresolved_quantity_evidence', 'unresolved_quantity_evidence'),
    ):
        checks.append((f'{lvl_a}_N_06', table_a[lvl_a]['N'], int(obs_pairs_06[lvl_p1])))
        checks.append((f'{lvl_a}_N_07', table_a[lvl_a]['N'],
                       int(est_07_year['by_four_level_burden'][lvl_p1]['denominator'])))
        checks.append((f'{lvl_a}_pf_07', table_a[lvl_a]['columns']['pad_free']['n'],
                       int(est_07_year['by_four_level_burden'][lvl_p1]['numerator'])))

    # Social-continence gates against script 16 for one and two_or_more rows.
    one_cols = table_a['one']['columns']
    two_cols = table_a['two_or_more_all']['columns']
    one_social_num = one_cols['pad_free']['n'] + one_cols['one']['n']
    one_social_den = table_a['one']['N'] - one_cols['not_classifiable']['n']
    two_social_num = two_cols['pad_free']['n'] + two_cols['one']['n']
    two_social_den = table_a['two_or_more_all']['N'] - two_cols['not_classifiable']['n']
    social_excluded = one_cols['not_classifiable']['n'] + two_cols['not_classifiable']['n']

    checks.extend([
        ('social_one_events_16', one_social_num, int(social_16['one_events'])),
        ('social_one_n_16', one_social_den, int(social_16['one_n'])),
        ('social_two_events_16', two_social_num, int(social_16['two_events'])),
        ('social_two_n_16', two_social_den, int(social_16['two_n'])),
        ('social_total_n_16', one_social_den + two_social_den, int(social_16['n'])),
        ('social_excluded_16', social_excluded, int(social_16['excluded_pad_users_without_a_valid_count'])),
    ])

    # Country-by-burden ties against 07.
    for country in ('Poland', 'United States'):
        for row_key, lvl_07 in (('one', 'one'), ('two_or_more_all', 'two_or_more')):
            cell_07 = est_07_year['by_burden_and_country'][f'{lvl_07}|{country}']
            checks.append((f'{country}_{row_key}_N_07', table_c[country][row_key]['N'], int(cell_07['denominator'])))
            checks.append((f'{country}_{row_key}_pf_07', table_c[country][row_key]['columns']['pad_free']['n'],
                           int(cell_07['numerator'])))

    for label, obs, exp in checks:
        if obs != exp:
            fail('PHASE1_RECONCILIATION_MISMATCH', f'{label}: observed={obs} expected={exp}')

    # Verify early-user totals match 06.
    if len(paired_users) != int(obs_pairs_06['declared_total']):
        fail('PAIRED_USERS_COUNT_MISMATCH')
    if len(paired_pad_free) != table_a['pad_free_at_three_months']['N']:
        fail('PAIRED_PAD_FREE_COUNT_MISMATCH')
    return {
        'early_users_total_06': int(early_users_06['declared_total']),
        'social_continence_one_events': int(one_social_num),
        'social_continence_one_n': int(one_social_den),
        'social_continence_two_events': int(two_social_num),
        'social_continence_two_n': int(two_social_den),
        'social_continence_excluded': int(social_excluded),
        'checks_passed': len(checks),
        'all_gates_matched': True,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='One-year pad category by three-month pad count.')
    ap.add_argument('--verify', action='store_true')
    cohort_mod.add_cohort_args(ap)
    args = ap.parse_args(argv)
    verify = args.verify
    cohort_name = args.cohort
    is_all_ops = cohort_name == cohort_mod.COHORT_ALL_OPERATIONS
    out_path = cohort_mod.output_path(EVIDENCE, cohort_name)
    if not verify:
        cohort_mod.assert_writable_output(out_path)

    d = load('drv06', '06_derive_observed_assessments.py')
    E = load('est05', '05_observed_estimators.py')
    res = d.source_derive(cohort=cohort_name)
    if res['source_verification']['bound_inputs_before'] != 122:
        fail('BOUND_INPUT_COUNT')

    ID = d.ID
    selection, candidate, sets = res['selection'], res['candidate'], res['sets']

    patients_wide = pd.read_csv(
        d.RELEASE / 'tables/patient_wide.csv', dtype=str, keep_default_na=False, usecols=[ID, 'country'],
    )
    id_set = set(patients_wide[ID].astype(str))
    country_map = dict(zip(patients_wide[ID].astype(str), patients_wide['country'].astype(str)))

    rec06 = read_phase1_json(DERIVATION_EVIDENCE, cohort_name)
    rec07 = read_phase1_json(ESTIMATES_EVIDENCE, cohort_name)
    rec16 = read_phase1_json(STRENGTHENING_EVIDENCE, cohort_name)

    grouped_early = build_day_groups(d, selection['selected']['early'], candidate)
    grouped_year = build_day_groups(d, selection['selected']['year'], candidate)

    # 1. Early pad users (`res['patients']`).
    f = res['patients'].copy().reset_index(drop=True)
    if not f[ID].astype(str).isin(id_set).all():
        fail('UNMATCHED_PATIENTS')
    f['_fine_level'] = [
        three_month_fine_level(d, grouped_early, pid, str(b))
        for pid, b in zip(f[ID], f['_burden'])
    ]
    f['_has_year'] = f['_year_status'].notna()
    f['_has_six'] = f['_six_status'].notna()

    # 2. Early pad-free patients with a selected one-year status.
    year_chosen = selection['selected']['year'].set_index(ID)
    pf_year_ids = sorted(sets['early_pad_free'] & sets['year_status_known'])
    pf_country_raw = pd.Series([country_map.get(str(pid), '') for pid in pf_year_ids], dtype=str)
    pf_df = pd.DataFrame({
        ID: pf_year_ids,
        '_burden': 'pad_free_at_three_months',
        '_fine_level': 'pad_free_at_three_months',
        '_country': np.where(pf_country_raw.isin(d.COUNTRIES), pf_country_raw, d.UNKNOWN_COUNTRY),
        '_year_status': [int(year_chosen.loc[pid, '_status']) for pid in pf_year_ids],
    })

    # Classify one-year category on all paired patients (early pad users + early pad-free).
    paired_users = f.loc[f['_has_year']].copy().reset_index(drop=True)
    user_cats, user_strict, audits = [], [], []
    for pid, ys in zip(paired_users[ID], paired_users['_year_status']):
        cat, audit = classify_one_year_category(d, grouped_year, pid, ys)
        user_cats.append(cat)
        user_strict.append('pad_free' if audit is None else audit['cat_paren'])
        if audit is not None:
            audits.append(audit)
    paired_users['_year_cat'] = user_cats
    paired_users['_year_cat_strict'] = user_strict

    # Sensitivity of the one-year category to a strict rule: more than one pad only when every valid
    # record shows at least two pads, one pad only when every valid record shows at most one pad.
    strict_by_level = {}
    for key, mask in (('one', paired_users['_fine_level'] == 'one'),
                      ('two', paired_users['_fine_level'] == 'two'),
                      ('three_or_more', paired_users['_fine_level'] == 'three_or_more'),
                      ('two_or_more_all', paired_users['_burden'] == 'two_or_more')):
        sub = paired_users.loc[mask, '_year_cat_strict']
        counts_strict = {k: int((sub == k).sum()) for k in ('pad_free', 'one', 'two_or_more', 'not_classifiable')}
        if sum(counts_strict.values()) != int(mask.sum()):
            fail('STRICT_RULE_ROW_SUM_MISMATCH', key)
        strict_by_level[key] = {**counts_strict, 'with_year_record': int(mask.sum()),
                                'classified': int(mask.sum()) - counts_strict['not_classifiable']}

    pf_cats = []
    for pid, ys in zip(pf_df[ID], pf_df['_year_status']):
        cat, audit = classify_one_year_category(d, grouped_year, pid, ys)
        pf_cats.append(cat)
        if audit is not None:
            audits.append(audit)
    pf_df['_year_cat'] = pf_cats

    paired_all = pd.concat(
        [
            pf_df[[ID, '_burden', '_fine_level', '_country', '_year_status', '_year_cat']],
            paired_users[[ID, '_burden', '_fine_level', '_country', '_year_status', '_year_cat']],
        ],
        ignore_index=True,
    )

    # Audit comparison between script 16 rule and 06.classify_day / parenthetical description.
    disagree_06 = [a for a in audits if a['cat_16'] != a['cat_06']]
    disagree_paren = [a for a in audits if a['cat_16'] != a['cat_paren']]
    classification_rule_audit = {
        'rule_used': 'script_16_social_continence_quantity_rule',
        'paired_year_pad_users_audited': len(audits),
        'script16_counts': {
            k: sum(1 for a in audits if a['cat_16'] == k) for k in ('one', 'two_or_more', 'not_classifiable')
        },
        'classify_day_06_counts': {
            k: sum(1 for a in audits if a['cat_06'] == k) for k in ('one', 'two_or_more', 'not_classifiable')
        },
        'parenthetical_strict_counts': {
            k: sum(1 for a in audits if a['cat_paren'] == k) for k in ('one', 'two_or_more', 'not_classifiable')
        },
        'disagreements_script16_vs_06': len(disagree_06),
        'disagreements_script16_vs_parenthetical': len(disagree_paren),
        'disagreement_causes_vs_06': {
            'invalid_quantity_evidence': sum(1 for a in disagree_06 if a['has_invalid']),
            'incompatible_valid_intervals': sum(1 for a in disagree_06 if a['has_incompatible']),
            'crossing_range_evidence': sum(1 for a in disagree_06 if a['has_crossing']),
            'partial_bound_evidence': sum(1 for a in disagree_06 if a['has_partial']),
            'at_most_one_not_exact_one': sum(
                1 for a in disagree_06
                if a['cat_16'] == 'one' and not a['has_invalid'] and not a['has_incompatible']
            ),
        },
    }

    # Part A: Three-month level by one-year category.
    def table_a_masks(df):
        is_user = df['_burden'].astype(str) != 'pad_free_at_three_months'
        return [
            ('pad_free_at_three_months', 'Pad-free at three months', ~is_user),
            ('one', 'Exactly one pad per day', df['_fine_level'] == 'one'),
            ('two', 'Exactly two pads per day', df['_fine_level'] == 'two'),
            ('three_or_more', 'Three or more pads per day', df['_fine_level'] == 'three_or_more'),
            ('two_or_more_unseparated', 'Two or more pads, not separable into two vs three or more',
             df['_fine_level'] == 'two_or_more_unseparated'),
            ('nonconflicting_quantity_uncertain', 'Unclear count (nonconflicting quantity uncertain)',
             df['_fine_level'] == 'nonconflicting_quantity_uncertain'),
            ('unresolved_quantity_evidence', 'Conflicting count (unresolved quantity evidence)',
             df['_fine_level'] == 'unresolved_quantity_evidence'),
            ('two_or_more_all', 'Two or more pads, all', df['_burden'] == 'two_or_more'),
            ('all_pad_users', 'All men using pads at three months', is_user),
        ]

    table_a = summarize_table_rows(E, paired_all, table_a_masks(paired_all))

    # Part C: By country (Poland and United States, pooled rows only).
    table_c = {}
    for country in ('Poland', 'United States'):
        sub_c = paired_all.loc[paired_all['_country'] == country]
        c_specs = [
            ('pad_free_at_three_months', 'Pad-free at three months', sub_c['_burden'] == 'pad_free_at_three_months'),
            ('one', 'Exactly one pad per day', sub_c['_burden'] == 'one'),
            ('two_or_more_all', 'Two or more pads, all', sub_c['_burden'] == 'two_or_more'),
        ]
        table_c[country] = summarize_table_rows(E, sub_c, c_specs)
    unknown_country_sub = paired_all.loc[paired_all['_country'] == d.UNKNOWN_COUNTRY]
    table_c_unknown_counts = {
        row_key: int((unknown_country_sub['_burden'] == b_val).sum())
        for row_key, b_val in (
            ('pad_free_at_three_months', 'pad_free_at_three_months'),
            ('one', 'one'),
            ('two_or_more_all', 'two_or_more'),
        )
    }
    for row_key, _ in TABLE_C_ORDER:
        country_sum = (
            table_c['Poland'][row_key]['N']
            + table_c['United States'][row_key]['N']
            + table_c_unknown_counts[row_key]
        )
        if country_sum != table_a[row_key]['N']:
            fail('COUNTRY_SUM_MISMATCH', row_key)

    # Gate checks against phase 1 records.
    reconcile_summary = verify_phase1_gates(table_a, table_c, paired_users, pf_df, rec06, rec07, rec16)

    # Part B: Still using two or more pads at one year.
    classifiable_users = paired_users.loc[paired_users['_year_cat'] != 'not_classifiable'].copy().reset_index(drop=True)
    classifiable_users['_still_two_or_more'] = (classifiable_users['_year_cat'] == 'two_or_more').astype(int)

    part_b_rows = {}
    for key, mask_all, mask_cls in (
        ('one', paired_users['_fine_level'] == 'one', classifiable_users['_fine_level'] == 'one'),
        ('two', paired_users['_fine_level'] == 'two', classifiable_users['_fine_level'] == 'two'),
        ('three_or_more', paired_users['_fine_level'] == 'three_or_more',
         classifiable_users['_fine_level'] == 'three_or_more'),
        ('two_or_more_all', paired_users['_burden'] == 'two_or_more',
         classifiable_users['_burden'] == 'two_or_more'),
    ):
        total_yr = int(mask_all.sum())
        N_cls = int(mask_cls.sum())
        n_two_yr = int((mask_cls & (classifiable_users['_still_two_or_more'] == 1)).sum())
        not_cls = total_yr - N_cls
        if not_cls != int((mask_all & (paired_users['_year_cat'] == 'not_classifiable')).sum()):
            fail('PART_B_CLASSIFIABLE_MISMATCH', key)
        part_b_rows[key] = wilson_cell(E, n_two_yr, N_cls) | {
            'not_classifiable': not_cls,
            'total_with_year_record': total_yr,
        }

    # Unseparated two-or-more count among classifiable one-year outcomes (for trend sensitivity).
    mask_unsep_cls = classifiable_users['_fine_level'] == 'two_or_more_unseparated'
    unsep_N_cls = int(mask_unsep_cls.sum())
    unsep_n_two = int((mask_unsep_cls & (classifiable_users['_still_two_or_more'] == 1)).sum())

    # Whole-patient percentile bootstrap over all classifiable early pad users (matching 07/11).
    rows_fine = list(zip(classifiable_users['_fine_level'].astype(str), classifiable_users['_still_two_or_more'].tolist()))
    rows_pooled = list(zip(classifiable_users['_burden'].astype(str), classifiable_users['_still_two_or_more'].tolist()))
    diff_three_minus_one = bootstrap_diff(E, rows_fine, 'three_or_more', 'one')
    diff_two_all_minus_one = bootstrap_diff(E, rows_pooled, 'two_or_more', 'one')

    def trend_cell(r):
        return {'n': r['N'], 'events': r['n']}

    c_one = trend_cell(part_b_rows['one'])
    c_two = trend_cell(part_b_rows['two'])
    c_three = trend_cell(part_b_rows['three_or_more'])
    trend_exact = armitage([c_one, c_two, c_three], [1, 2, 3])
    trend_unsep_two = armitage(
        [c_one, {'n': c_two['n'] + unsep_N_cls, 'events': c_two['events'] + unsep_n_two}, c_three],
        [1, 2, 3],
    )
    trend_unsep_three = armitage(
        [c_one, c_two, {'n': c_three['n'] + unsep_N_cls, 'events': c_three['events'] + unsep_n_two}],
        [1, 2, 3],
    )

    table_b = {
        'denominator_definition': 'Men with a selected one-year record and a classifiable one-year pad category (pad_free, one, or two_or_more).',
        'rows': part_b_rows,
        'contrasts': {
            'three_or_more_minus_one': diff_three_minus_one,
            'two_or_more_all_minus_one': diff_two_all_minus_one,
        },
        'trend_cochran_armitage_one_two_three_or_more': trend_exact,
        'trend_sensitivity_unseparated_as_two': trend_unsep_two,
        'trend_sensitivity_unseparated_as_three_or_more': trend_unsep_three,
    }

    # Part D: Recovery after six months.
    six_and_year = f.loc[f['_has_six'] & f['_has_year']].copy()
    six_use = six_and_year.loc[six_and_year['_six_status'].eq(0)]
    six_free = six_and_year.loc[six_and_year['_six_status'].eq(1)]

    def recovery_subgroups(sub):
        specs = [
            ('overall', pd.Series(True, index=sub.index)),
            ('one', sub['_burden'].astype(str) == 'one'),
            ('two_or_more', sub['_burden'].astype(str) == 'two_or_more'),
            ('other_uncertain_or_unresolved',
             sub['_burden'].astype(str).isin(['nonconflicting_quantity_uncertain', 'unresolved_quantity_evidence'])),
        ]
        return {
            key: wilson_cell(E, int((sub.loc[m, '_year_status'].eq(1)).sum()), int(m.sum()))
            for key, m in specs
        }

    table_d = {
        'six_month_window_days': list(d.WINDOWS['six'][:2]),
        'year_window_days': list(d.WINDOWS['year'][:2]),
        'six_month_accounting': {
            'early_users': int(len(f)),
            'early_users_with_six_month_record': int(f['_has_six'].sum()),
            'early_users_six_month_pad_use': int((f['_has_six'] & f['_six_status'].eq(0)).sum()),
            'early_users_six_month_pad_free': int((f['_has_six'] & f['_six_status'].eq(1)).sum()),
            'early_users_with_six_and_year_record': int(len(six_and_year)),
            'six_month_pad_use_with_year_record': int(len(six_use)),
            'six_month_pad_free_with_year_record': int(len(six_free)),
        },
        'six_month_pad_use_with_year_record': recovery_subgroups(six_use),
        'six_month_pad_free_with_year_record': recovery_subgroups(six_free),
    }

    # Part E: Counts tying to phase 1 per level + cohort gate check/record.
    early_level_counts = {
        lvl: {
            'early_users': int((f['_fine_level'] == lvl).sum()),
            'with_year_record': int((paired_users['_fine_level'] == lvl).sum()),
            'year_pad_free': table_a[lvl]['columns']['pad_free']['n'],
        }
        for lvl in ('one', 'two', 'three_or_more', 'two_or_more_unseparated',
                    'nonconflicting_quantity_uncertain', 'unresolved_quantity_evidence')
    }
    early_level_counts['two_or_more_all'] = {
        'early_users': int((f['_burden'] == 'two_or_more').sum()),
        'with_year_record': int((paired_users['_burden'] == 'two_or_more').sum()),
        'year_pad_free': table_a['two_or_more_all']['columns']['pad_free']['n'],
    }
    early_level_counts['all_pad_users'] = {
        'early_users': int(len(f)),
        'with_year_record': int(len(paired_users)),
        'year_pad_free': table_a['all_pad_users']['columns']['pad_free']['n'],
    }

    observed_gates = {
        'early_users': int(len(f)),
        'early_pad_free_with_year': table_a['pad_free_at_three_months']['N'],
        'early_users_with_year': int(len(paired_users)),
        'one_n': table_a['one']['N'],
        'one_year_pad_free': table_a['one']['columns']['pad_free']['n'],
        'one_year_one': table_a['one']['columns']['one']['n'],
        'one_year_two_or_more': table_a['one']['columns']['two_or_more']['n'],
        'one_year_not_classifiable': table_a['one']['columns']['not_classifiable']['n'],
        'two_n': table_a['two']['N'],
        'two_year_pad_free': table_a['two']['columns']['pad_free']['n'],
        'two_year_one': table_a['two']['columns']['one']['n'],
        'two_year_two_or_more': table_a['two']['columns']['two_or_more']['n'],
        'two_year_not_classifiable': table_a['two']['columns']['not_classifiable']['n'],
        'three_or_more_n': table_a['three_or_more']['N'],
        'three_or_more_year_pad_free': table_a['three_or_more']['columns']['pad_free']['n'],
        'three_or_more_year_one': table_a['three_or_more']['columns']['one']['n'],
        'three_or_more_year_two_or_more': table_a['three_or_more']['columns']['two_or_more']['n'],
        'three_or_more_year_not_classifiable': table_a['three_or_more']['columns']['not_classifiable']['n'],
        'two_or_more_unseparated_n': table_a['two_or_more_unseparated']['N'],
        'two_or_more_all_n': table_a['two_or_more_all']['N'],
        'two_or_more_all_year_pad_free': table_a['two_or_more_all']['columns']['pad_free']['n'],
        'two_or_more_all_year_one': table_a['two_or_more_all']['columns']['one']['n'],
        'two_or_more_all_year_two_or_more': table_a['two_or_more_all']['columns']['two_or_more']['n'],
        'two_or_more_all_year_not_classifiable': table_a['two_or_more_all']['columns']['not_classifiable']['n'],
        'still_two_or_more_one_n': part_b_rows['one']['n'],
        'still_two_or_more_one_denom': part_b_rows['one']['N'],
        'still_two_or_more_two_n': part_b_rows['two']['n'],
        'still_two_or_more_two_denom': part_b_rows['two']['N'],
        'still_two_or_more_three_n': part_b_rows['three_or_more']['n'],
        'still_two_or_more_three_denom': part_b_rows['three_or_more']['N'],
        'still_two_or_more_all_two_n': part_b_rows['two_or_more_all']['n'],
        'still_two_or_more_all_two_denom': part_b_rows['two_or_more_all']['N'],
        'still_two_or_more_three_minus_one': diff_three_minus_one['estimate'],
        'still_two_or_more_two_or_more_minus_one': diff_two_all_minus_one['estimate'],
        'recovery_after_6m_pad_use_n': table_d['six_month_pad_use_with_year_record']['overall']['n'],
        'recovery_after_6m_pad_use_denom': table_d['six_month_pad_use_with_year_record']['overall']['N'],
        'recovery_after_6m_pad_free_n': table_d['six_month_pad_free_with_year_record']['overall']['n'],
        'recovery_after_6m_pad_free_denom': table_d['six_month_pad_free_with_year_record']['overall']['N'],
    }
    try:
        cohort_mod.check_or_record_gates(
            '18_one_year_pad_category', cohort_name, observed_gates, record=args.record_gates,
        )
    except cohort_mod.GateError as exc:
        fail(exc.code, exc.detail)

    record = {
        'analysis_id': 'M1-ONE-YEAR-PAD-CATEGORY',
        'status': 'exploratory_post_hoc_disclosed',
        'cohort': res['cohort'],
        'draws': DRAWS,
        'seed': BOOTSTRAP_SEED,
        'confidence': CONFIDENCE,
        'software': {
            'python': sys.version.split()[0],
            'pandas': pd.__version__,
            'numpy': np.__version__,
            'scipy': scipy.__version__,
        },
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'one_year_classification_rule': {
            'description': (
                'Reuses script 16 social-continence rule on status-consistent candidate rows of the '
                'selected one-year day: _year_status == 1 -> pad_free; otherwise from upper bounds '
                'of informative valid rows (`_ok & upper.notna()`): empty -> not_classifiable; '
                'all <= 1 -> one (at most one pad); otherwise -> two_or_more.'
            ),
            'row_order_table_a': [k for k, _ in TABLE_A_ORDER],
            'column_order_table_a': list(YEAR_CATEGORIES),
            'row_order_table_c': [k for k, _ in TABLE_C_ORDER],
        },
        'classification_rule_audit': {**classification_rule_audit,
                                      'strict_rule_by_three_month_level': strict_by_level},
        'table_a_three_month_by_one_year': table_a,
        'table_b_still_using_two_or_more_at_one_year': table_b,
        'table_c_by_country': table_c,
        'table_c_unknown_or_other_country_counts': table_c_unknown_counts,
        'table_d_recovery_after_six_months': table_d,
        'phase1_reconciliation': {
            'early_users_per_level': early_level_counts,
            'gate_checks': reconcile_summary,
        },
    }

    text = json.dumps(d.strict(record), indent=2, sort_keys=True, allow_nan=False, ensure_ascii=False)
    for pid in id_set:
        if pid and len(pid) > 3 and pid in text:
            fail('IDENTIFIER_LEAK')

    scan = dict(record)
    cscan = dict(scan['cohort'])
    if cscan.get('common_extract_date') == cohort_mod.COMMON_EXTRACT_DATE:
        cscan.pop('common_extract_date')
    scan['cohort'] = cscan
    if DATE_SHAPED.search(json.dumps(d.strict(scan), sort_keys=True, allow_nan=False)):
        fail('DATE_SHAPED_TOKEN')

    max_float_diff = 0.0
    if verify:
        if not out_path.is_file():
            fail('SAVED_RECORD_MISMATCH', 'missing_output')
        saved = out_path.read_text()
        if is_all_ops:
            ok, reason, max_float_diff = cohort_mod.compare_records_ignoring_provenance(
                json.loads(saved), json.loads(text), ignore_keys=('code_sha256', 'software'), float_tol=1e-12,
            )
            if not ok:
                fail('SAVED_RECORD_MISMATCH', reason)
        elif json.loads(saved) != json.loads(text):
            fail('SAVED_RECORD_MISMATCH')
        print(json.dumps({
            'status': 'saved_one_year_pad_category_recomputed_exactly',
            'cohort': cohort_name,
            'max_float_diff': max_float_diff,
        }))
        return 0

    out_path.write_text(text + '\n')
    print(json.dumps({'status': 'written', 'cohort': cohort_name, 'path': str(out_path)}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
