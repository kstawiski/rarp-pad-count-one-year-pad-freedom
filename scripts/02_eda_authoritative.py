#!/usr/bin/env python3
"""Deterministic aggregate EDA. Sources read only. No clinical inference or row exports."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import warnings
import pandas as pd
import duckdb

HERE = Path(__file__).resolve().parents[1]
WORKSPACE = HERE.parent
RELEASE = WORKSPACE / 'data/prostatectomy_analysis_database_v1.1_2026-09-04'
ID = 'master_patient_id'
TABLES = ('baseline_pet_nodal_status', 'clinical_domains_safe', 'complications_long',
          'complications_structured_safe', 'continence_events_long', 'continence_milestones_long',
          'erectile_function_structured_safe', 'erectile_long', 'governed_psa_endpoint_input',
          'imaging_observation', 'patient_wide', 'postoperative_treatment_long',
          'prom_instruments_safe', 'proms_long', 'psa_long', 'psa_timepoint_labels_safe',
          'recurrence_endpoints_long')
WINDOWS = {'early': (60, 120, 90), 'six': (150, 210, 180), 'year': (305, 425, 365),
           'two_year': (670, 790, 730), 'early_narrow': (75, 105, 90), 'year_narrow': (335, 395, 365)}
NUM_PAD = ('pads_per_day', 'pads_per_day_min', 'pads_per_day_max')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def truth(s):
    return s.astype(str).str.strip().str.lower().isin(['true', '1', '1.0'])


def false(s):
    return s.astype(str).str.strip().str.lower().isin(['false', '0', '0.0'])


def numeric(s):
    return pd.to_numeric(s, errors='coerce')


def dates(s):
    # Require exact released ISO day precision, not permissive date inference.
    iso = s.astype(str).str.fullmatch(r'\d{4}-\d{2}-\d{2}')
    return pd.to_datetime(s.where(iso, ''), format='%Y-%m-%d', errors='coerce')


def rounded(x):
    return None if pd.isna(x) else round(float(x), 4)


def stats(s):
    x = numeric(s)
    finite = x.notna() & x.map(math.isfinite)
    y = x[finite].astype(float)
    blank = s.astype(str).str.strip().eq('')
    result = {'total': len(s), 'n': len(y), 'missing': int(blank.sum()),
              'nonnumeric_nonblank': int((~blank & x.isna()).sum()),
              'nonfinite': int((x.notna() & ~finite).sum())}
    if y.empty:
        return result
    q1, median, q3 = y.quantile([.25, .5, .75])
    iqr = q3 - q1
    flags = (y < q1 - 1.5 * iqr) | (y > q3 + 1.5 * iqr)
    core = y[~flags]
    result.update(mean=rounded(y.mean()), sd=rounded(y.std(ddof=1)), median=rounded(median),
                  q1=rounded(q1), q3=rounded(q3), min=rounded(y.min()), max=rounded(y.max()),
                  median_absolute_deviation=rounded((y - median).abs().median()),
                  iqr_flagged=int(flags.sum()), mean_without_iqr_flags_diagnostic_only=rounded(core.mean()),
                  mean_influence_of_iqr_flags=rounded(y.mean() - core.mean()))
    return result


def bool_quality(s):
    t, f = truth(s), false(s)
    blank = s.astype(str).str.strip().eq('')
    return {'total': len(s), 'true': int(t.sum()), 'false': int(f.sum()),
            'missing': int(blank.sum()), 'other_nonblank': int((~t & ~f & ~blank).sum())}


def date_quality(s):
    blank = s.astype(str).str.strip().eq('')
    parsed = dates(s)
    return {'total': len(s), 'parseable': int(parsed.notna().sum()), 'missing': int(blank.sum()),
            'invalid_nonblank': int((~blank & parsed.isna()).sum())}


def category_quality(s, allowed):
    result = {k: int(s.eq(k).sum()) for k in allowed}
    result['missing'] = int(s.eq('').sum())
    result['other_nonblank'] = int((s.ne('') & ~s.isin(allowed)).sum())
    return result


def duplicate_quality(frame):
    result = {'rows': len(frame), 'columns': len(frame.columns),
              'exact_duplicate_extra_rows': int(frame.duplicated().sum()),
              'exact_duplicate_member_rows': int(frame.duplicated(keep=False).sum())}
    if ID in frame:
        present = frame[ID].ne('')
        result.update(distinct_nonblank_patients=int(frame.loc[present, ID].nunique()),
                      blank_patient_keys=int((~present).sum()),
                      repeated_patient_key_extra_rows=int(frame.loc[present].duplicated(ID).sum()))
    else:
        result['patient_key_check'] = 'not_applicable_no_declared_master_patient_key'
    return result


def logical_key_quality(frame, columns):
    good = frame.loc[frame[list(columns)].ne('').all(axis=1)]
    sizes = good.groupby(list(columns)).size()
    repeated = sizes[sizes.gt(1)]
    return {'complete_key_rows': len(good), 'incomplete_key_rows': len(frame) - len(good),
            'duplicate_groups': len(repeated), 'duplicate_member_rows': int(repeated.sum()),
            'duplicate_extra_rows': int((repeated - 1).sum())}


def pad_masks(frame):
    point = numeric(frame['pads_per_day'])
    rawlo, rawhi = numeric(frame['pads_per_day_min']), numeric(frame['pads_per_day_max'])
    lower, upper = rawlo.fillna(point), rawhi.fillna(point)
    contradiction = (truth(frame['pad_free']) & (lower.gt(0) | numeric(frame['diaper_count_min']).gt(0) | truth(frame['safety_pad_documented']))) | (false(frame['pad_free']) & upper.eq(0) & ~numeric(frame['diaper_count_min']).gt(0) & ~truth(frame['safety_pad_documented']))
    masks = {'negative_point': point.lt(0), 'negative_lower': lower.lt(0), 'negative_upper': upper.lt(0),
             'inverted_range_after_fallback': lower.gt(upper),
             'point_outside_documented_bounds': (point.notna() & ((rawlo.notna() & point.lt(rawlo)) | (rawhi.notna() & point.gt(rawhi)))),
             'bound_missing_after_fallback': lower.isna() | upper.isna(),
             'pad_free_quantity_or_device_contradiction': contradiction}
    return masks, lower, upper


def pad_quality(frame):
    masks, lower, upper = pad_masks(frame)
    return {'rows': len(frame), **{k: int(v.sum()) for k, v in masks.items()},
            'numeric_fields': {k: stats(frame[k]) for k in NUM_PAD}}


def prepare(frame):
    d = frame.copy()
    d['_date'] = dates(d.event_date)
    d['_surgery'] = dates(d.surgery_date)
    d['_day'] = (d._date - d._surgery).dt.days
    d['_status'] = pd.Series(pd.NA, index=d.index, dtype='Int64')
    d.loc[truth(d.pad_free), '_status'] = 1
    d.loc[false(d.pad_free), '_status'] = 0
    valid = d._day.gt(0) & d.event_phase.eq('postoperative') & truth(d.usable_continence_observation) & ~truth(d.event_date_ambiguous) & d.event_date_precision_source_derived.isin(['', 'day'])
    return d, valid


def same_day_summary(frame):
    known = frame.loc[frame._status.notna() & frame._date.notna()]
    groups = known.groupby([ID, '_date'])._status.agg(['size', 'nunique'])
    conflict = groups['nunique'].gt(1)
    repeated_consistent = groups['size'].gt(1) & ~conflict
    return {'known_status_rows': len(known), 'patient_day_groups': len(groups),
            'conflict_groups': int(conflict.sum()),
            'conflict_patients': int(groups[conflict].index.get_level_values(0).nunique()),
            'conflict_member_rows': int(groups.loc[conflict, 'size'].sum()),
            'consistent_repeated_groups': int(repeated_consistent.sum()),
            'consistent_repeated_extra_rows': int((groups.loc[repeated_consistent, 'size'] - 1).sum()),
            'singleton_groups': int(groups['size'].eq(1).sum())}


def select_window(frame, window):
    lo, hi, target = window
    x = frame.loc[frame._day.between(lo, hi) & frame._status.notna()].copy()
    diagnostics = same_day_summary(x)
    conflicts = x.groupby([ID, '_date'])._status.transform('nunique').gt(1)
    patients_before = set(x[ID])
    x = x.loc[~conflicts].copy()
    x['_distance'] = (x._day - target).abs()
    x = x.sort_values(['_distance', '_date', 'event_index'], kind='stable').drop_duplicates(ID)
    diagnostics.update(selected_patients=len(x), selected_pad_users=int(x._status.eq(0).sum()),
                       selected_pad_free=int(x._status.eq(1).sum()),
                       patients_without_alternative_after_conflict_day_omission=len(patients_before - set(x[ID])))
    return x, diagnostics


def sealed_digest(path):
    """Byte count and SHA-256 of the plaintext of a bound input kept sealed as PATH.age.

    Patient-level provenance files of the release are stored encrypted. The plaintext is
    streamed through the hash and never written or returned.
    """
    sealed = path.with_name(path.name + '.age')
    if sealed.is_symlink() or not sealed.is_file():
        return None
    try:
        proc = subprocess.Popen(['phi', 'cat', str(sealed)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    h = hashlib.sha256()
    size = 0
    for block in iter(lambda: proc.stdout.read(1 << 20), b''):
        h.update(block)
        size += len(block)
    if proc.wait() != 0:
        return None
    return size, h.hexdigest()


def verify_sources(manifest):
    mismatches = 0
    for entry in manifest['files']:
        rel = Path(entry['path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise RuntimeError('INVALID_MANIFEST_PATH')
        path = WORKSPACE / rel
        if path.is_symlink():
            mismatches += 1
        elif path.is_file():
            if path.stat().st_size != entry['bytes'] or sha(path) != entry['sha256']:
                mismatches += 1
        elif sealed_digest(path) != (entry['bytes'], entry['sha256']):
            mismatches += 1
    if mismatches:
        raise RuntimeError('BOUND_INPUT_MISMATCH')
    return len(manifest['files'])


def preflight_module():
    spec = importlib.util.spec_from_file_location('m1_preflight', HERE / 'scripts/00_preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_report(root):
    if root.absolute() != RELEASE or root.is_symlink() or root.resolve() != RELEASE:
        raise RuntimeError('SOURCE_ROOT_NOT_BOUND_RELEASE')
    manifest_path = HERE / 'evidence/SOURCE_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    checked = verify_sources(manifest)
    release_manifest = json.loads((root / 'MANIFEST.json').read_text())
    if set(release_manifest['tables']) != set(TABLES):
        raise RuntimeError('TABLE_CONTRACT_MISMATCH')
    # No source values, private filenames, or parse exception text leave this function.
    frames = {name: pd.read_csv(root / 'tables' / (name + '.csv'), dtype=str, keep_default_na=False) for name in TABLES}
    w, c, m = (frames[name] for name in ('patient_wide', 'continence_events_long', 'continence_milestones_long'))
    if not w[ID].ne('').all() or not w[ID].is_unique:
        raise RuntimeError('PATIENT_KEY_CONTRACT_FAILURE')
    all_ids = set(w[ID])
    robotic = w.loc[truth(w.robotic_platform_used)]
    cr = c.loc[c[ID].isin(set(robotic[ID]))]
    table_results = {}
    for name, frame in frames.items():
        table_results[name] = duplicate_quality(frame)
        table_results[name]['csv_sha256'] = sha(root / 'tables' / (name + '.csv'))
        if ID in frame:
            table_results[name]['orphan_rows'] = int((~frame[ID].isin(all_ids)).sum())
    logical = {'patient_wide': logical_key_quality(w, [ID]),
               'continence_events_long': logical_key_quality(c, [ID, 'event_index']),
               'continence_milestones_long': logical_key_quality(m, [ID, 'milestone_month'])}
    d, valid = prepare(cr)
    eligible = d.loc[valid].copy()
    contradictions = pad_masks(eligible)[0]['pad_free_quantity_or_device_contradiction']
    eligible.loc[contradictions, '_status'] = pd.NA
    chosen, win = {}, {}
    for name, window in WINDOWS.items():
        chosen[name], win[name] = select_window(eligible, window)
    pairs = chosen['early'].merge(chosen['year'], on=ID, suffixes=('_early', '_year'), validate='one_to_one')
    early_users = chosen['early'].loc[chosen['early']._status.eq(0)]
    observed_users = pairs.loc[pairs._status_early.eq(0)]
    values = {'unique_released_patients': len(w), 'robotic_procedures': len(robotic),
              'valid_dated_postoperative_continence_rows': len(eligible),
              'known_early_status_days_60_120': len(chosen['early']), 'early_pad_users': len(early_users),
              'paired_early_and_year': len(pairs), 'early_pad_users_with_year_status': len(observed_users),
              'year_pad_free_in_observed_pairs': int(observed_users._status_year.eq(1).sum())}
    for name in ('six', 'two_year', 'early_narrow', 'year_narrow'):
        values['window_' + name + '_status_known'] = len(chosen[name])
        values['window_' + name + '_pad_users'] = int(chosen[name]._status.eq(0).sum())
    mr = m.loc[m[ID].isin(set(robotic[ID]))]
    for month in (3, 12):
        values[f'milestone_{month}m_observed'] = int((mr.milestone_month.eq(str(month)) & truth(mr.observed)).sum())
    ladder_path = HERE / 'analysis/preparation/denominator_ladder.csv'
    ladder = pd.read_csv(ladder_path, dtype=str, keep_default_na=False)
    reconciliation = [{'stage': r.stage_key, 'unit': r.unit, 'saved': int(r.candidate_n),
                       'recomputed': int(values[r.stage_key]), 'match': int(r.candidate_n) == values[r.stage_key]}
                      for r in ladder.itertuples()]
    if not all(r['match'] for r in reconciliation):
        raise RuntimeError('DENOMINATOR_LADDER_MISMATCH')
    pre = preflight_module()
    formats = pre.parity(root, list(TABLES))
    feasibility = pre.continence(w, c, m)
    saved_path = HERE / 'evidence/FEASIBILITY.json'
    saved = json.loads(saved_path.read_text())
    if feasibility != saved['feasibility']:
        raise RuntimeError('SAVED_FEASIBILITY_MISMATCH')
    recorded = numeric(d.days_from_surgery)
    compared = d._day.notna() & recorded.notna()
    date_info = {'robotic_event_dates': date_quality(cr.event_date),
                 'robotic_event_surgery_dates': date_quality(cr.surgery_date),
                 'offset_comparable_rows': int(compared.sum()),
                 'offset_mismatches': int((compared & d._day.ne(recorded)).sum()),
                 'event_surgery_disagreements_with_patient_table': int((d._surgery.notna() & d[ID].map(dates(w.set_index(ID).surgery_date)).notna() & d._surgery.ne(d[ID].map(dates(w.set_index(ID).surgery_date)))).sum()),
                 'postoperative_label_with_nonpositive_day': int((d.event_phase.eq('postoperative') & d._day.le(0)).sum()),
                 'all_dated_robotic_assessment_offsets': stats(d.days_from_surgery),
                 'candidate_valid_postoperative_days': stats(eligible._day),
                 'phase': category_quality(cr.event_phase, ['preoperative', 'perioperative', 'postoperative']),
                 'precision': category_quality(cr.event_date_precision_source_derived, ['day', 'month', 'year']),
                 'ambiguous_date': bool_quality(cr.event_date_ambiguous)}
    fields = ['pad_free', 'pads_per_day', 'pads_per_day_min', 'pads_per_day_max', 'diaper_count_min', 'safety_pad_documented', 'event_date', 'surgery_date', 'days_from_surgery']
    missingness = {scope: {'rows': len(frame), 'blank_counts': {k: int(frame[k].eq('').sum()) for k in fields}}
                   for scope, frame in [('all_continence', c), ('robotic_continence', cr)]}
    by_country = {}
    for country in ('Poland', 'United States'):
        e = early_users.loc[early_users.country.eq(country)]
        observed = e[ID].isin(set(chosen['year'][ID]))
        by_country[country] = {'early_users': len(e), 'with_year_status': int(observed.sum()),
                               'without_year_status': int((~observed).sum())}
    verified_after = verify_sources(manifest)
    result = {
        'record_kind': 'aggregate-only-authoritative-release-eda', 'scope': 'database-development-not-final-clinical-analysis',
        'authority': 'The user-designated released database is authoritative. No original-document certification is required for this EDA.',
        'source_root': str(RELEASE.relative_to(WORKSPACE)), 'table_count': len(TABLES),
        'source_verification': {'manifest_sha256': sha(manifest_path), 'bound_inputs_before': checked,
                                'bound_inputs_after': verified_after, 'hash_or_size_mismatches': 0,
                                'format_parity_tables': len(formats), 'format_parity': formats},
        'software': {'python': sys.version.split()[0], 'pandas': pd.__version__, 'duckdb': duckdb.__version__},
        'code': {'entry_sha256': sha(Path(__file__)), 'preflight_sha256': sha(HERE / 'scripts/00_preflight.py')},
        'tables': table_results, 'logical_key_checks': logical,
        'definitions': {'exact_duplicate': 'All original CSV columns identical. Extra rows count occurrences beyond the first.',
                        'repeated_patient_key': 'Rows beyond the first per nonblank patient key. Expected in longitudinal data.',
                        'same_day_conflict': 'At least one explicit true and one explicit false pad-free state in one patient/date group. This grouping does not establish source-event identity.',
                        'selection': 'Existing candidate rule only. Omit conflicting day and permit another usable day. Nearest target, then earlier date, then event_index for consistent states.',
                        'missingness': 'Empty CSV field is missing. Other invalid tokens are counted separately where parsed. No imputation.',
                        'outliers': '1.5 IQR flags are diagnostic. Mean without flags measures influence, not an exclusion rule.'},
        'cohort': {'released_patients': len(w), 'robotic_patients': len(robotic), 'all_continence_rows': len(c),
                   'robotic_continence_rows': len(cr), 'candidate_valid_postoperative_rows': len(eligible)},
        'patient_quality': {'age_all': stats(w.age), 'age_robotic': stats(robotic.age),
                            'age_outside_adult_18_to_100_all': int((numeric(w.age).lt(18) | numeric(w.age).gt(100)).sum()),
                            'surgery_date': date_quality(w.surgery_date),
                            'country': category_quality(w.country, ['Poland', 'United States']),
                            'robotic_platform_used': bool_quality(w.robotic_platform_used)},
        'missingness': missingness,
        'boolean_quality': {k: bool_quality(c[k]) for k in ('pad_free', 'usable_continence_observation', 'safety_pad_documented')},
        'date_quality': date_info,
        'pad_quality': {'all_release_rows': pad_quality(c), 'robotic_rows': pad_quality(cr), 'candidate_valid_rows': pad_quality(eligible)},
        'same_day': {'all_dated_robotic_known_status': same_day_summary(d), 'candidate_valid_known_status': same_day_summary(eligible), 'windows': win},
        'denominator_reconciliation': {'ladder_sha256': sha(ladder_path), 'stages_checked': len(reconciliation), 'stages': reconciliation,
                                      'feasibility_sha256': sha(saved_path), 'saved_feasibility_recomputed_exactly': True},
        'candidate_observation_inventory': {'early_users': len(early_users), 'with_year_status': len(observed_users),
                                             'without_year_status': len(early_users) - len(observed_users), 'by_country': by_country,
                                             'meaning': 'Observed-pair inventory before opportunity derivation. No follow-up response probability or clinical recovery estimate.'},
        'intervention_flags': {'source_true_canonical_not_true': int((truth(w.postoperative_treatment_assessed_src) & ~truth(w.postoperative_treatment_assessed_v11)).sum()),
                              'canonical_true_source_not_true': int((truth(w.postoperative_treatment_assessed_v11) & ~truth(w.postoperative_treatment_assessed_src)).sum()),
                              'meaning': 'Different assessment flags. Neither establishes absence or delivery of treatment.'},
        'analysis_implications': ['The cohort and candidate denominator ladder reproduce. Repeated patient observations are not duplicate records.',
                                  'Material same-day conflicts warrant targeted handling for affected estimates only.',
                                  'Follow-up observation and pad-quantity missingness require explicit denominator accounting. The mechanism is not established by EDA.',
                                  'No source value was altered and no outlier was removed from the source.'],
        'limitations': ['This is a focused EDA, not validation of every clinical field in the release.',
                        'The current primary estimand remains P(Y=1 | E=1, A=1, O=1). No opportunity boundary is inferred.',
                        'Counts do not establish treatment delivery or absence. Unknown histories remain unknown.',
                        'No model, hypothesis test, clinical estimate, scientific review approval or lifecycle promotion is supplied.'],
        'privacy': {'aggregate_only': True, 'patient_rows_emitted': False, 'exact_dates_emitted': False, 'identifiers_emitted': False,
                    'narratives_emitted': False, 'dictionary_examples_model_read': False},
        'clinical_estimates_computed': False, 'science_lock': False
    }
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=RELEASE)
    ap.add_argument('--output', type=Path, default=HERE / 'evidence/EDA_AUTHORITATIVE_RELEASE.json')
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args(argv)
    output = args.output.absolute()
    if output.is_symlink() or not output.resolve().is_relative_to(HERE) or output.resolve().is_relative_to(RELEASE):
        raise RuntimeError('OUTPUT_SCOPE_FAILURE')
    result = build_report(args.root)
    text = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n'
    if args.verify:
        if output.read_text() != text:
            raise RuntimeError('SAVED_EDA_MISMATCH')
    else:
        output.write_text(text)
    print(json.dumps({'status': 'saved_eda_recomputed_exactly' if args.verify else 'aggregate_eda_written',
                      'bound_inputs': result['source_verification']['bound_inputs_before'],
                      'tables': result['table_count'], 'ladder_stages': result['denominator_reconciliation']['stages_checked'],
                      'early_conflict_groups': result['same_day']['windows']['early']['conflict_groups'],
                      'year_conflict_groups': result['same_day']['windows']['year']['conflict_groups']}))


def safe_main(argv=None):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            main(argv)
        return 0
    except Exception:
        # Parser and source exceptions may contain private data. Never echo them.
        print('EDA_FAILED_SOURCE_DETAIL_WITHHELD', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
