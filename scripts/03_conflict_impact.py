#!/usr/bin/env python3
"""Aggregate D1-D5 impact diagnostic, not clinical analysis or tier-A assurance.

Source values and membership sets stay in memory. Candidate selection is preserved.
No model, interval, test, coverage derivation, adjudication or final exclusion.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import sys
import warnings
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
OUTPUT = HERE / 'evidence/CONFLICT_IMPACT.json'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


E = module('impact_eda', '02_eda_authoritative.py')
P = module('impact_preparation', '01_prepare_adjudication.py')
ID = E.ID
WINDOWS = {k: E.WINDOWS[k] for k in ('early', 'year')}


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def row_masks(frame):
    """Independent D1-D4 implementation. Missing evidence is not contradiction."""
    p, lo, hi = [E.numeric(frame[k]) for k in E.NUM_PAD]
    lower, upper = lo.fillna(p), hi.fillna(p)
    dm, dx = E.numeric(frame.diaper_count_min), E.numeric(frame.diaper_count_max)
    safety, free, user = E.truth(frame.safety_pad_documented), E.truth(frame.pad_free), E.false(frame.pad_free)
    out = {
        'D1_true_positive_ordinary_lower': free & lower.gt(0),
        'D1_true_positive_diaper': free & dm.gt(0),
        'D1_true_safety_pad': free & safety,
        'D1_reverse_false_zero_upper_no_device': user & upper.eq(0) & ~dm.gt(0) & ~safety,
        'D4_negative_ordinary': p.lt(0) | lo.lt(0) | hi.lt(0),
        'D4_negative_diaper': dm.lt(0) | dx.lt(0),
        'D4_inverted_ordinary_after_fallback': lower.gt(upper),
        'D4_inverted_diaper': dm.gt(dx),
        'D4_point_outside_documented_range': p.notna() & ((lo.notna() & p.lt(lo)) | (hi.notna() & p.gt(hi))),
    }
    out['D1_endpoint_contradiction'] = pd.concat([out[k] for k in out if k.startswith('D1_')], axis=1).any(axis=1)
    out['D4_invalid_quantity'] = pd.concat([out[k] for k in out if k.startswith('D4_')], axis=1).any(axis=1)
    burden = pd.Series('quantity_uncertain', index=frame.index)
    burden.loc[lower.eq(1) & upper.eq(1)] = 'one'
    burden.loc[lower.ge(2)] = 'two_or_more'
    context = {
        'D3_lower_fallback_used': lo.isna() & p.notna(),
        'D3_upper_fallback_used': hi.isna() & p.notna(),
        'D3_no_numeric_ordinary_evidence': lower.isna() & upper.isna(),
        'D3_at_least_one_bound_missing': lower.isna() | upper.isna(),
        'D3_range_spans_one_and_two': lower.le(1) & upper.ge(2),
        'D2_positive_diaper': dm.gt(0), 'D2_safety_pad_true': safety,
    }
    return out, context, lower, upper, burden


def annotate(events, patients):
    d, valid = E.prepare(events)
    masks, context, lower, upper, burden = row_masks(d)
    d['_lower'], d['_upper'], d['_burden'] = lower, upper, burden
    d['_valid'] = valid
    d['_endpoint_bad'] = masks['D1_endpoint_contradiction']
    d['_quantity_bad'] = masks['D4_invalid_quantity']
    recorded = E.numeric(d.days_from_surgery)
    wide_surgery = d[ID].map(E.dates(patients.set_index(ID).surgery_date))
    alt_day = (d._date - wide_surgery).dt.days
    dm = {
        'event_date_missing': d.event_date.eq(''),
        'event_date_invalid_nonblank': d.event_date.ne('') & d._date.isna(),
        'surgery_date_missing': d.surgery_date.eq(''),
        'surgery_date_invalid_nonblank': d.surgery_date.ne('') & d._surgery.isna(),
        'offset_missing_or_nonnumeric': recorded.isna(),
        'offset_mismatch': recorded.notna() & d._day.notna() & recorded.ne(d._day),
        'surgery_disagrees_with_patient_table': d._surgery.notna() & wide_surgery.notna() & d._surgery.ne(wide_surgery),
        'postoperative_nonpositive_day': d.event_phase.eq('postoperative') & d._day.le(0),
        'ambiguous_date': E.truth(d.event_date_ambiguous),
        'unsupported_precision': ~d.event_date_precision_source_derived.isin(['', 'day']),
    }
    d['_date_problem'] = pd.concat(dm.values(), axis=1).any(axis=1)
    # Date uncertainty can make window membership unlocatable, not definitely outside.
    d['_unlocatable'] = d._day.isna() & recorded.isna() & alt_day.isna()
    for key, (lo, hi, _) in WINDOWS.items():
        d['_in_' + key] = d._day.between(lo, hi)
        plausible = d._day.between(lo, hi) | recorded.between(lo, hi) | alt_day.between(lo, hi) | d._unlocatable
        d['_date_' + key] = d._date_problem & plausible
    return d, masks, context, dm


def group_keys(frame):
    return set(zip(frame[ID], frame._date))


def group_diagnostics(frame):
    """One dictionary per parseable patient-day, never exported.

    Numeric tuple variation is evidence discordance, not necessarily incompatible
    intervals or a changed D3 category. Missing tuples add no quantity assertion.
    """
    groups = {}
    for key, g in frame.loc[frame._date.notna()].groupby([ID, '_date'], sort=False):
        known = g._status.dropna()
        informative = g._lower.notna() | g._upper.notna()
        q = g.loc[informative]
        signatures = set()
        for p, lo, hi in zip(E.numeric(q.pads_per_day), q._lower, q._upper):
            p, lo, hi = [None if pd.isna(x) else float(x) for x in (p, lo, hi)]
            signatures.add((lo, hi, None if lo == hi == p else p))
        variation = len(signatures) > 1
        categories = set(q._burden)
        clean = q.loc[~q._quantity_bad]
        # Only valid, nonnegative intervals support an incompatibility assertion.
        incompat = (len(clean) > 1 and clean._lower.notna().any() and clean._upper.notna().any()
                    and clean._lower.max() > clean._upper.min())
        status_conflict = bool(known.eq(0).any() and known.eq(1).any())
        groups[key] = {
            'rows': len(g), 'known_rows': len(known),
            'status_conflict': status_conflict,
            'consistent_known_status_repetition': len(known) > 1 and not status_conflict,
            'numeric_tuple_variation': variation,
            'incompatible_valid_intervals': bool(incompat),
            'numeric_category_changing': variation and len(categories) > 1,
            'numeric_category_stable': variation and len(categories) == 1,
            'missing_with_numeric_evidence': bool(informative.any() and (~informative).any()),
            'historical_coarse_only': (len(set(g.loc[g._status.notna(), '_burden'])) > 1
                                       and not status_conflict and not variation),
        }
    return groups


GROUP_FLAGS = ('status_conflict', 'consistent_known_status_repetition', 'numeric_tuple_variation',
               'incompatible_valid_intervals', 'numeric_category_changing', 'numeric_category_stable',
               'missing_with_numeric_evidence', 'historical_coarse_only')


def flagged_keys(groups, flag):
    return {key for key, value in groups.items() if value[flag]}


def patients_of(keys):
    return {key[0] for key in keys}


def group_counts(groups, members=None, selected_keys=None):
    filtered = {k: v for k, v in groups.items() if (members is None or k[0] in members)
                and (selected_keys is None or k in selected_keys)}
    out = {'patient_day_groups': len(filtered), 'patients': len(patients_of(filtered)),
           'rows': sum(v['rows'] for v in filtered.values())}
    for flag in GROUP_FLAGS:
        keys = flagged_keys(filtered, flag)
        out[flag] = {'groups': len(keys), 'patients': len(patients_of(keys)),
                     'member_rows': sum(filtered[k]['rows'] for k in keys)}
    both = flagged_keys(filtered, 'numeric_tuple_variation') - flagged_keys(filtered, 'status_conflict')
    out['numeric_variation_without_state_contradiction'] = {'groups': len(both), 'patients': len(patients_of(both))}
    return out


def count_rows(frame, masks, members):
    eligible = frame[ID].isin(members)
    return {name: {'rows': int((mask & eligible).sum()),
                   'patients': int(frame.loc[mask & eligible, ID].nunique())}
            for name, mask in masks.items()}


def partition(universe, status, burden, date):
    """Mutually exclusive exhaustive 3-bit patient accounting; no overlapping sum."""
    bins = {str(i): 0 for i in range(8)}
    for pid in universe:
        bit = int(pid in status) + 2 * int(pid in burden) + 4 * int(pid in date)
        bins[str(bit)] += 1
    require(sum(bins.values()) == len(universe), 'PARTITION_FAILURE')
    return {'patients': len(universe), 'bitmask_counts': bins,
            'overlapping_reason_patients': {'status': len(universe & status), 'burden_category': len(universe & burden),
                                           'date_selection': len(universe & date)}, 'accounting_exact': True}


def impact_sets(d, selected, groups, key, selected_only=False):
    in_window = d['_in_' + key] & d._valid
    row_scope = in_window
    g = groups
    if selected_only:
        keys = group_keys(selected)
        row_scope = in_window & pd.Series([(pid, dt) in keys for pid, dt in zip(d[ID], d._date)], index=d.index)
        g = {k: v for k, v in groups.items() if k in keys}
    status = patients_of(flagged_keys(g, 'status_conflict')) | set(d.loc[row_scope & d._endpoint_bad, ID])
    burden = patients_of(flagged_keys(g, 'numeric_category_changing')) | set(d.loc[row_scope & d._quantity_bad, ID])
    numeric = patients_of(flagged_keys(g, 'numeric_tuple_variation'))
    # Date issues use all source rows, not just rows already admitted to the screen.
    date = set(d.loc[d['_date_' + key], ID])
    if selected_only:
        date &= set(selected[ID])
    return {'status': status, 'burden': burden, 'date': date, 'numeric_fact': numeric}


def build_diagnostic(patients, events):
    d, masks, context, date_masks = annotate(events, patients)
    robotic = set(patients.loc[E.truth(patients.robotic_platform_used), ID])
    v = d.loc[d._valid & d[ID].isin(robotic)].copy()
    # D1 blanking is only reproduction of the existing screen, not a factual correction.
    candidate = v.copy()
    candidate.loc[candidate._endpoint_bad, '_status'] = pd.NA
    selected = {k: E.select_window(candidate, win)[0] for k, win in E.WINDOWS.items()}
    early, year = selected['early'], selected['year']
    pairs = set(early[ID]) & set(year[ID])
    users = set(early.loc[early._status.eq(0), ID])
    pair_users = users & set(year[ID])
    free = pair_users & set(year.loc[year._status.eq(1), ID])
    cohorts = {'all_released': set(patients[ID]), 'robotic': robotic, 'early_status_known': set(early[ID]),
               'early_users': users, 'paired_early_year': pairs, 'early_users_with_year': pair_users,
               'year_padfree_observed_pairs': free, 'year_status_known': set(year[ID])}
    ladder = {k: {'n': len(ids), 'unit': 'patients'} for k, ids in cohorts.items()}
    ladder['valid_dated_postoperative_continence'] = {'n': len(v), 'unit': 'rows'}
    groups_all = group_diagnostics(d)
    groups_valid = group_diagnostics(candidate)
    windows, impacts, direct = {}, {}, {}
    for key in WINDOWS:
        frame = candidate.loc[candidate['_in_' + key]]
        groups = group_diagnostics(frame)
        robotic_rows = d.loc[d[ID].isin(robotic)]
        impacts[key] = impact_sets(robotic_rows, selected[key], groups, key)
        direct[key] = impact_sets(robotic_rows, selected[key], groups, key, True)
        conflicts = patients_of(flagged_keys(groups, 'status_conflict'))
        selected_ids = set(selected[key][ID])
        selected_keys = group_keys(selected[key])
        selected_day_mask = pd.Series([(pid, dt) in selected_keys for pid, dt in zip(d[ID], d._date)], index=d.index)
        row_scopes = {'all_source_dated_in_window': d['_in_' + key],
                      'valid_robotic_in_window': d['_in_' + key] & d._valid & d[ID].isin(robotic),
                      'selected_day_valid_robotic': selected_day_mask & d._valid & d[ID].isin(robotic)}
        windows[key] = {
            'row_reasons_and_context': {scope: {name: count_rows(d, {reason: mask & scope_mask for reason, mask in {**masks, **context}.items()}, ids)
                                              for name, ids in cohorts.items()} for scope, scope_mask in row_scopes.items()},
            'all_valid_robotic_rows': group_counts(groups),
            'by_cohort': {name: {'any_day_in_window': group_counts(groups, ids),
                                 'selected_day': group_counts(groups, ids, group_keys(selected[key])),
                                 'D5_with_alternative_selected_day_still_unresolved': len(ids & conflicts & selected_ids),
                                 'D5_no_alternative_selected_day_candidate_omission': len((ids & conflicts) - selected_ids)}
                          for name, ids in cohorts.items()},
            'D5_conflict_patients': len(conflicts),
            'D5_alternative_selected_still_unresolved': len(conflicts & selected_ids),
            'D5_no_alternative_candidate_omission': len(conflicts - selected_ids),
        }
    partitions = {}
    for scope, imp in [('any_valid_day_in_target_window', impacts), ('selected_day_fields_with_window_date_uncertainty', direct)]:
        status = imp['early']['status'] | imp['year']['status']
        date = imp['early']['date'] | imp['year']['date']
        # Primary burden is EARLY burden. Year quantity discordance is separately visible.
        burden = imp['early']['burden']
        partitions[scope] = {name: partition(ids, status, burden, date) for name, ids in cohorts.items()}
    burden_categories = {}
    for category in ('one', 'two_or_more', 'quantity_uncertain'):
        ids = set(early.loc[early._burden.eq(category), ID]) & users
        burden_categories[category] = {}
        for name, members in [('early_users', ids), ('early_users_with_year', ids & pair_users), ('year_padfree_observed_pairs', ids & free)]:
            burden_categories[category][name] = {
                **partition(members, impacts['early']['status'] | impacts['year']['status'], impacts['early']['burden'],
                            impacts['early']['date'] | impacts['year']['date']),
                'early_selected_day_numeric_fact_discordance': len(members & direct['early']['numeric_fact']),
                'early_selected_day_category_impact': len(members & direct['early']['burden']),
                'early_any_day_numeric_fact_discordance': len(members & impacts['early']['numeric_fact']),
                'year_any_day_category_impact_not_primary_burden': len(members & impacts['year']['burden'])}
    # Counts by located source day, independent of candidate filtering. Unlocatable stays separate.
    target_keys = group_keys(d.loc[d._in_early | d._in_year])
    location = {}
    for flag in ('status_conflict', 'numeric_tuple_variation', 'numeric_category_changing', 'numeric_category_stable', 'historical_coarse_only'):
        all_keys = flagged_keys(groups_all, flag)
        inside, outside = all_keys & target_keys, all_keys - target_keys
        all_p, inside_p, outside_p = patients_of(all_keys), patients_of(inside), patients_of(outside)
        location[flag] = {
            'all_dated_groups': len(all_keys), 'inside_target_groups': len(inside), 'outside_target_groups': len(outside),
            'patients_anywhere': len(all_p), 'patients_inside_only': len(inside_p - outside_p),
            'patients_outside_only': len(outside_p - inside_p), 'patients_inside_and_outside': len(inside_p & outside_p),
            'candidate_membership_intersections': {name: {'inside': len(ids & inside_p), 'outside_only': len(ids & (outside_p - inside_p))}
                                                  for name, ids in cohorts.items()}}
    row_location = {}
    for reason, mask in masks.items():
        row_location[reason] = {'inside_target': int((mask & (d._in_early | d._in_year)).sum()),
                                'located_outside_target': int((mask & d._day.notna() & ~(d._in_early | d._in_year)).sum()),
                                'unlocated': int((mask & d._day.isna()).sum()), 'total_rows': int(mask.sum())}
    selected_context = {}
    for key in WINDOWS:
        x = selected[key]
        xm, xc, _, _, _ = row_masks(x)
        selected_context[key] = {name: count_rows(x, {**xm, **xc}, ids) for name, ids in cohorts.items()}
    result = {
        'selected_record_reasons_and_context': selected_context,
        'candidate_ladder': ladder,
        'row_reasons_by_cohort': {name: count_rows(d, masks, ids) for name, ids in cohorts.items()},
        'quantity_context_not_contradictions_by_cohort': {name: count_rows(d, context, ids) for name, ids in cohorts.items()},
        'date_reasons_by_cohort': {name: count_rows(d, date_masks, ids) for name, ids in cohorts.items()},
        'date_selection_candidates_by_window': {key: {name: len(ids & impacts[key]['date']) for name, ids in cohorts.items()} for key in WINDOWS},
        'same_day': {'all_released_dated': group_counts(groups_all), 'valid_robotic': group_counts(groups_valid), 'windows': windows},
        'primary_field_impact_partitions': partitions,
        'candidate_early_burden_categories': burden_categories,
        'issue_location': location, 'row_issue_location': row_location,
        'duplicates': E.duplicate_quality(events),
        'per_window_impact_patients': {key: {name: {reason: len(ids & vals) for reason, vals in impacts[key].items()}
                                            for name, ids in cohorts.items()} for key in WINDOWS},
    }
    return result, selected, candidate, cohorts


def reconcile(patients, events, milestones, result, selected, candidate, saved_eda, summary):
    """Compare identities with independent earlier selection, without row exports."""
    s = P.screen(patients, events, milestones)
    require(P.candidate_counts(s) == summary['candidate_stages'], 'PREPARATION_CANDIDATE_MISMATCH')
    compared = 0
    for key, x in selected.items():
        y = s['selected'][key]
        a = set(zip(x[ID], x._date, x._status, x.event_index, x._burden))
        b = set(zip(y[ID], y._date, y._status.astype(int), y.event_index, y._burden))
        require(a == b, 'CANDIDATE_IDENTITY_MISMATCH')
        compared += len(a)
    # Reconcile aggregate historic queue while keeping missing-only coarse differences distinct.
    expected = pd.read_csv(HERE / 'analysis/preparation/issue_summary.csv', keep_default_na=False)
    comparisons = []
    for row in expected.itertuples():
        if row.scope == 'all_source_dated_rows':
            frame, _ = E.prepare(events)
            masks, _, lower, upper, burden = row_masks(frame)
            frame['_lower'], frame['_upper'], frame['_burden'] = lower, upper, burden
            frame['_quantity_bad'] = masks['D4_invalid_quantity']
        elif row.scope == 'any_valid_dated_row':
            frame = candidate
        else:
            lo, hi, _ = E.WINDOWS[row.window]
            frame = candidate.loc[candidate._day.between(lo, hi)]
        groups = group_diagnostics(frame)
        flag = 'status_conflict' if row.issue_type == 'same_day_conflicting_pad_status' else 'numeric_tuple_variation'
        keys = flagged_keys(groups, flag)
        if flag == 'numeric_tuple_variation' and row.scope != 'all_source_dated_rows':
            keys |= flagged_keys(groups, 'historical_coarse_only')
        rows = sum(groups[k]['known_rows' if flag == 'status_conflict' else 'rows'] for k in keys)
        require((rows, len(keys), len(patients_of(keys))) == (row.rows, row.groups, row.patients), 'HISTORICAL_QUEUE_MISMATCH')
        comparisons.append({'scope': row.scope, 'reason': row.issue_type, 'rows': rows, 'groups': len(keys), 'patients': len(patients_of(keys))})
    for key in WINDOWS:
        actual = result['same_day']['windows'][key]['all_valid_robotic_rows']['status_conflict']
        old = saved_eda['same_day']['windows'][key]
        require(actual['groups'] == old['conflict_groups'] and actual['patients'] == old['conflict_patients'], 'EDA_STATUS_MISMATCH')
    mr, _ = P.milestone_reconciliation(s, patients)
    require(mr == summary['released_milestone_reconciliation'], 'MILESTONE_IDENTITY_MISMATCH')
    return {'all_six_window_selection_identities_and_fields_match': True, 'selected_window_records_compared': compared,
            'candidate_stages_match_preparation': True, 'historical_issue_rows_groups_patients': comparisons,
            'milestone_identity_reconciliation': mr, 'historical_queue_not_reclassified_or_discharged': True}


def build_report(root):
    require(root.absolute() == E.RELEASE and root.resolve() == E.RELEASE and not root.is_symlink(), 'UNBOUND_RELEASE')
    manifest_path = HERE / 'evidence/SOURCE_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    require(manifest['release_relative_path'] == str(E.RELEASE.relative_to(E.WORKSPACE)), 'MANIFEST_ROOT_MISMATCH')
    before = E.verify_sources(manifest)
    require(before == 122, 'BOUND_INPUT_COUNT_MISMATCH')
    tables = json.loads((root / 'MANIFEST.json').read_text())['tables']
    require(set(tables) == set(E.TABLES), 'TABLE_SET_MISMATCH')
    formats = E.preflight_module().parity(root, list(E.TABLES))
    patients, events, milestones = [pd.read_csv(root / 'tables' / (name + '.csv'), dtype=str, keep_default_na=False)
                                    for name in ('patient_wide', 'continence_events_long', 'continence_milestones_long')]
    require(patients[ID].ne('').all() and patients[ID].is_unique, 'PATIENT_KEY_FAILURE')
    require(set(events[ID]) <= set(patients[ID]) and set(milestones[ID]) <= set(patients[ID]), 'ORPHAN_FAILURE')
    require(not milestones.duplicated([ID, 'milestone_month']).any(), 'MILESTONE_KEY_FAILURE')
    result, selected, candidate, cohorts = build_diagnostic(patients, events)
    expected = {'all_released': 1497, 'robotic': 1397, 'early_status_known': 644, 'early_users': 460,
                'paired_early_year': 309, 'early_users_with_year': 226, 'year_padfree_observed_pairs': 86,
                'valid_dated_postoperative_continence': 5376}
    require(all(result['candidate_ladder'][k]['n'] == n for k, n in expected.items()), 'CANONICAL_LADDER_FAILURE')
    eda = json.loads((HERE / 'evidence/EDA_AUTHORITATIVE_RELEASE.json').read_text())
    summary = json.loads((HERE / 'analysis/preparation/summary.json').read_text())
    result['reconciliation'] = reconcile(patients, events, milestones, result, selected, candidate, eda, summary)
    # All problem masks and resulting aggregate counts must ignore source-row order.
    shuffled, _, _, _ = build_diagnostic(patients.iloc[::-1], events.iloc[::-1])
    require({k: v for k, v in result.items() if k != 'reconciliation'} == shuffled, 'ROW_ORDER_INVARIANCE_FAILURE')
    after = E.verify_sources(manifest)
    result.update({
        'record_kind': 'aggregate_conflict_impact_data_preparation_only',
        'authority': 'User-designated release is authoritative. No original-document certification or blanket historic review-unit prerequisite.',
        'source_root': str(E.RELEASE.relative_to(E.WORKSPACE)),
        'source_verification': {'bound_inputs_before': before, 'bound_inputs_after': after, 'mismatches': 0,
                                'manifest_sha256': E.sha(manifest_path), 'format_parity_tables': len(formats), 'format_parity': formats},
        'code_sha256': {name: E.sha(HERE / 'scripts' / name) for name in ('00_preflight.py', '01_prepare_adjudication.py', '02_eda_authoritative.py', '03_conflict_impact.py')},
        'test_sha256': E.sha(HERE / 'tests/test_03_conflict_impact.py'),
        'context_sha256': {name: E.sha(HERE / name) for name in ('ANALYSIS_PLAN.md', 'project/adjudication-proposals.json', 'evidence/VARIABLE_MAP.csv', 'evidence/EDA_AUTHORITATIVE_RELEASE.json', 'analysis/preparation/summary.json', 'analysis/preparation/issue_summary.csv')},
        'source_table_sha256': {name: E.sha(root / 'tables' / (name + '.csv')) for name in ('patient_wide', 'continence_events_long', 'continence_milestones_long')},
        'software': {'python': sys.version.split()[0], 'pandas': pd.__version__, 'duckdb': E.duckdb.__version__},
        'source_row_order_reversal_aggregate_invariance': True,
        'definitions': {
            'units': 'Rows, patient-day groups and distinct patients are separate. Overlapping reasons must never be summed as patient totals.',
            'status': 'Explicit true AND false on one patient-day, or a D1 endpoint/device contradiction. No XOR of missing states.',
            'quantity': 'Distinct informative numeric (lower, upper, informative point) tuples after independent D3 fallbacks. Missing tuples do not assert a conflicting quantity.',
            'incompatible_intervals': 'Among nonnegative non-inverted records without point-outside-range defects, maximum lower exceeds minimum upper. Open ends provide no finite restriction.',
            'category_changing': 'At least two informative numeric tuples imply different preserved D3 labels. Numeric variation within one category is not category impact.',
            'historical_coarse_only': 'Preserved historical queue evidence, including missing-versus-known burden. Not a numeric contradiction by itself.',
            'impact_bitmask': '1=status in early or year; 2=early burden category-changing numeric disagreement or invalid quantity; 4=date-selection uncertainty in early or year. All eight cells are mutually exclusive.',
            'zero_bitmask': 'No detected impact on these primary fields under this scope, not adjudicated or free of unresolved numeric facts. Category-stable numeric facts remain separately visible.',
            'any_window': 'Valid robotic observations on any target-window day. This is a plausibility screen, not proof the selected value changes. Primary partitions project robotic-screen impacts onto each accounting universe, so nonrobotic patients have no primary impact flag; their source problems remain in all-source diagnostics.',
            'selected_day': 'All valid observations sharing the candidate selected patient-day, not just the tie-broken row. Date flag counts patients selected in that window with any plausible date-selection issue.',
            'date_plausibility': 'Any source row with a date/offset issue is potentially relevant when recomputed, recorded or patient-table-clock day lies in window, or all clocks are unavailable. It does not assert target membership.',
            'D5': 'Candidate omission removes a conflicting day, not the identity. Alternative selected days leave affected window membership unresolved. Problems outside target windows are not automatically primary-impact flags.',
            'D2': 'Diaper and safety-pad evidence are never used as ordinary-pad quantities.',
        },
        'limitations': ['Not tier-A assurance or a manuscript result. No patient fact is resolved and no final exclusion is applied.',
                        'No clinical estimate, interval, bound, statistical test, model, coverage inference or readiness promotion.',
                        'Aggregate impact classifications identify where judgment is needed, not how any contradiction should be resolved.',
                        'Missing/uncertain ordinary quantity and category-stable numeric discordance remain visible without being labelled category-changing contradictions.'],
        'privacy': {'aggregate_only': True, 'identifiers_exported': False, 'exact_dates_exported': False, 'row_exports': False,
                    'restricted_inventories_read': False, 'original_documents_read': False},
        'candidate_membership_changed': False, 'clinical_estimates_computed': False, 'science_lock': False,
    })
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=E.RELEASE)
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args(argv)
    require(not OUTPUT.is_symlink() and OUTPUT.resolve() == OUTPUT and (not OUTPUT.exists() or OUTPUT.stat().st_nlink == 1), 'OUTPUT_SCOPE_FAILURE')
    result = build_report(args.root)
    text = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n'
    if args.verify:
        require(OUTPUT.read_text() == text, 'SAVED_IMPACT_MISMATCH')
    else:
        OUTPUT.write_text(text)
    print(json.dumps({'status': 'saved_conflict_impact_recomputed_exactly' if args.verify else 'aggregate_conflict_impact_written',
                      'bound_inputs': result['source_verification']['bound_inputs_before'], 'format_parity_tables': 17,
                      'candidate_ladder': result['candidate_ladder'], 'output_sha256': E.sha(OUTPUT)}))


def safe_main(argv=None):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            main(argv)
        return 0
    except Exception:
        print('CONFLICT_IMPACT_FAILED_SOURCE_DETAIL_WITHHELD', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
