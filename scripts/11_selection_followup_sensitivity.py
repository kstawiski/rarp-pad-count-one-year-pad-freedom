"""Post hoc selection, follow-up-opportunity and missing-outcome analyses (amendment A-OBS-3).

Responds to the final external review of manuscript1. Every analysis here is post hoc and
exploratory. It adds:

1. A follow-up-opportunity restriction: early pad users whose whole one-year window
   (postoperative day 425) had closed before the earliest documented source extract date
   (1 April 2026; evidence/SOURCE_COVERAGE_STATUS.json). The extract dates are
   administrative leads, not custodian-confirmed inclusive coverage boundaries.
2. An operative-era restriction (operations 2017-2024).
3. Comparison of early pad users with and without a one-year record, and of robotic
   patients with and without an early assessment.
4. Missing-outcome bounds, tipping points and a pattern-mixture grid.
5. The post hoc country model without the one-year assessment day.
6. Exact-count, EPIC-excluded, device-evidence and platform-flag restrictions recomputed
   with the reference whole-patient bootstrap (seed 20260907) so every contrast in the
   sensitivity display shares one resampling scheme.
7. Source-level operative and record month ranges.

Aggregate output only. No identifier, exact clinical date or narrative is emitted, and the
record is scanned against the identity set before it is saved.

Run from manuscript1/:
  PY=/home/konrad/.venvs/konsta-research-py314/bin/python
  "$PY" -B scripts/11_selection_followup_sensitivity.py            # build
  "$PY" -B scripts/11_selection_followup_sensitivity.py --verify   # recompute, no write
"""

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / 'evidence/SELECTION_FOLLOWUP_SENSITIVITY.json'
DRAWS = 2000
REFERENCE_SEED = 20260907
MODEL_SEED = 20260916
COMMON_EXTRACT = pd.Timestamp('2026-04-01')
EXTRACT_LEADS = {'Bełchatów': '2026-04-03', 'Salve Medica': '2026-04-01',
                 "Brigham and Women's Hospital": '2026-04-15'}
YEAR_WINDOW_CLOSE = 425
GROUPS = ('one', 'two_or_more', 'nonconflicting_quantity_uncertain', 'unresolved_quantity_evidence')


def fail(code, detail=''):
    print(f'SELECTION_SENSITIVITY_FAILED {code} {detail}'.strip(), file=sys.stderr)
    sys.exit(1)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def med_iqr(values):
    v = pd.to_numeric(pd.Series(values), errors='coerce').dropna().to_numpy(float)
    if not len(v):
        return {'n': 0}
    return {'n': int(len(v)), 'median': float(np.median(v)),
            'q1': float(np.percentile(v, 25)), 'q3': float(np.percentile(v, 75))}


def counts(series):
    return {str(k): int(v) for k, v in pd.Series(series).astype(str).value_counts().sort_index().items()}


def main(argv):
    verify = '--verify' in argv
    d = load('drv06', '06_derive_observed_assessments.py')
    E = load('est05', '05_observed_estimators.py')
    res = d.source_derive()
    if res['source_verification']['bound_inputs_before'] != 122:
        fail('BOUND_INPUT_COUNT')
    ID = d.ID
    sets, frame, selection, candidate = res['sets'], res['patients'], res['selection'], res['candidate']
    robotic = set(res['robotic'])
    if len(frame) != 460 or len(robotic) != 1397:
        fail('LADDER', f'{len(frame)} {len(robotic)}')

    wide = pd.read_csv(d.RELEASE / 'tables/patient_wide.csv', dtype=str, keep_default_na=False,
                       usecols=[ID, 'operation_centre', 'surgery_date', 'age', 'country',
                                'followup_assessable', 'platform_conflict', 'pad_count_instrument_src'])
    wide = wide.set_index(wide[ID].astype(str))
    id_set = set(wide.index)

    f = frame.copy()
    f['_pid'] = f[ID].astype(str)
    f['_centre'] = f['_pid'].map(wide['operation_centre'])
    f['_surgery'] = pd.to_datetime(f['_pid'].map(wide['surgery_date']).str.strip(), errors='coerce')
    if f['_surgery'].isna().any():
        fail('SURGERY_DATE_MISSING_EARLY_USERS', str(int(f['_surgery'].isna().sum())))
    f['_year_close'] = f['_surgery'] + pd.Timedelta(days=YEAR_WINDOW_CLOSE)
    f['_closed_common'] = f['_year_close'] < COMMON_EXTRACT
    lead = f['_centre'].map({k: pd.Timestamp(v) for k, v in EXTRACT_LEADS.items()})
    if lead.isna().any():
        fail('CENTRE_UNMAPPED', str(int(lead.isna().sum())))
    f['_closed_centre'] = f['_year_close'] < lead
    f['_op_year'] = f['_surgery'].dt.year
    f['_era_2017_2024'] = f['_op_year'] <= 2024
    f['_has_year'] = f['_year_status'].notna()
    f['_burden'] = f['_burden'].astype(str)
    f['_platform_flag'] = f['_pid'].map(wide['platform_conflict']).astype(str).str.strip().isin(['1', 'True', 'true', '1.0'])
    f['_epic'] = f['_pid'].map(wide['pad_count_instrument_src']).astype(str).str.strip().eq('EPIC')

    def contrast(mask, label):
        sub = f.loc[mask & f['_has_year']]
        rows = [(str(b), int(s)) for b, s in zip(sub['_burden'], sub['_year_status'].astype(int))]
        boot = E.proportion_difference(rows, 'one', 'two_or_more', method=E.METHOD_BOOTSTRAP,
                                       confidence=0.95, resamples=DRAWS, seed=REFERENCE_SEED)
        newc = E.proportion_difference(rows, 'one', 'two_or_more', method=E.METHOD_NEWCOMBE, confidence=0.95)
        one = sub['_burden'].eq('one')
        two = sub['_burden'].eq('two_or_more')
        return {'label': label, 'pairs': int(len(sub)),
                'one_events': int(sub.loc[one, '_year_status'].eq(1).sum()), 'one_n': int(one.sum()),
                'two_events': int(sub.loc[two, '_year_status'].eq(1).sum()), 'two_n': int(two.sum()),
                'difference': boot['estimate'], 'bootstrap_lower': boot['lower'], 'bootstrap_upper': boot['upper'],
                'bootstrap_invalid': int(boot['bootstrap']['resamples_invalid']),
                'newcombe_lower': newc['lower'], 'newcombe_upper': newc['upper'],
                'one_wilson': [boot['group_a']['lower'], boot['group_a']['upper']],
                'two_wilson': [boot['group_b']['lower'], boot['group_b']['upper']]}

    everyone = pd.Series(True, index=f.index)
    ref = contrast(everyone, 'reference')
    if not (ref['pairs'] == 226 and ref['one_n'] == 110 and ref['two_n'] == 91 and ref['one_events'] == 58
            and ref['two_events'] == 24 and abs(ref['bootstrap_lower'] - 0.1327) < 5e-4
            and abs(ref['bootstrap_upper'] - 0.3951) < 5e-4 and abs(ref['newcombe_lower'] - 0.1281) < 5e-4):
        fail('REFERENCE_CALIBRATION', json.dumps(ref))

    # Exact-count classification, copied from script 10 so the restriction can be recomputed
    # with the reference resampling scheme.
    chosen = selection['selected']['early']
    keys = set(zip(chosen[ID], chosen._date))
    member = pd.Series([(pid, when) in keys for pid, when in zip(candidate[ID], candidate._date)],
                       index=candidate.index)
    day_rows = candidate.loc[member].copy()
    status_map = dict(zip(chosen[ID], chosen._status))
    mapped = day_rows[ID].map(status_map).astype('Int64')
    usable = day_rows.loc[day_rows._status.eq(mapped).fillna(False).astype(bool)]
    grouped = {pid: group for pid, group in usable.groupby(ID, sort=False)}

    def blank(v):
        return v is None or (isinstance(v, float) and math.isnan(v)) or str(v).strip() == ''

    exact = {}
    for pid in f.loc[f['_has_year'], ID]:
        group = grouped.get(pid)
        cols = d.quantity_columns(group)
        ok = True
        for i in group.index:
            if not (bool(cols['informative'][i]) and not bool(cols['invalid'][i])):
                continue
            lo, hi = cols['lower'][i], cols['upper'][i]
            if pd.isna(lo) or pd.isna(hi) or float(lo) != float(hi):
                ok = False
                break
            r_lo, r_hi, r_pt = group.loc[i, 'pads_per_day_min'], group.loc[i, 'pads_per_day_max'], group.loc[i, 'pads_per_day']
            if not ((not blank(r_lo) and not blank(r_hi) and str(r_lo).strip() == str(r_hi).strip()
                     and (blank(r_pt) or str(r_pt).strip() == str(r_lo).strip()))
                    or (blank(r_lo) and blank(r_hi) and not blank(r_pt))):
                ok = False
                break
        exact[pid] = ok
    f['_exact'] = f[ID].map(exact).fillna(False).astype(bool)
    range_reliant = f['_has_year'] & f['_burden'].eq('two_or_more') & ~f['_exact']
    if int(range_reliant.sum()) != 23 or int((f['_has_year'] & f['_burden'].eq('one') & ~f['_exact']).sum()) != 0:
        fail('EXACT_COUNT_CALIBRATION', str(int(range_reliant.sum())))

    device = f['_flag_device_evidence_present_never_used_as_ordinary'].astype(bool)

    contrasts = {
        'reference': ref,
        'window_closed_before_common_extract': contrast(f['_closed_common'], 'window_closed_before_2026_04_01'),
        'window_closed_before_centre_extract': contrast(f['_closed_centre'], 'window_closed_before_centre_lead'),
        'operative_era_2017_2024': contrast(f['_era_2017_2024'], 'operated_2017_2024'),
        'exact_count_records': contrast(~range_reliant, 'exclude_range_reliant_two_or_more'),
        'epic_instrument_excluded': contrast(~f['_epic'], 'exclude_epic_instrument'),
        'device_evidence_excluded': contrast(~device, 'exclude_other_absorbent_product_on_early_day'),
        'platform_flag_excluded': contrast(~f['_platform_flag'], 'exclude_platform_provenance_flag'),
    }
    for key in ('poland', 'united_states'):
        country = 'Poland' if key == 'poland' else 'United States'
        contrasts['window_closed_' + key] = contrast(f['_closed_common'] & f['_country'].eq(country),
                                                     'window_closed_' + key)

    # Availability among early pad users.
    def availability(mask):
        sub = f.loc[mask]
        out = {'early_users': int(len(sub)), 'with_year': int(sub['_has_year'].sum())}
        for g in GROUPS:
            m = sub['_burden'].eq(g)
            out['group_' + g] = {'early_users': int(m.sum()), 'with_year': int((m & sub['_has_year']).sum())}
        for c in ('Poland', 'United States'):
            m = sub['_country'].eq(c)
            out['country_' + c] = {'early_users': int(m.sum()), 'with_year': int((m & sub['_has_year']).sum())}
        for c in sorted(EXTRACT_LEADS):
            m = sub['_centre'].eq(c)
            out['centre_' + c] = {'early_users': int(m.sum()), 'with_year': int((m & sub['_has_year']).sum())}
        period = pd.Series(np.select([sub['_op_year'] <= 2022, sub['_op_year'] == 2023, sub['_op_year'] == 2024],
                                     ['2017-2022', '2023', '2024'], '2025-2026'), index=sub.index)
        for p in ('2017-2022', '2023', '2024', '2025-2026'):
            m = period.eq(p)
            out['period_' + p] = {'early_users': int(m.sum()), 'with_year': int((m & sub['_has_year']).sum())}
        age = pd.to_numeric(sub['_age'], errors='coerce')
        for label, m in (('age_lt60', age < 60), ('age_60_69', (age >= 60) & (age < 70)), ('age_ge70', age >= 70),
                         ('age_missing', age.isna())):
            out[label] = {'early_users': int(m.sum()), 'with_year': int((m & sub['_has_year']).sum())}
        out['age_with_year'] = med_iqr(sub.loc[sub['_has_year'], '_age'])
        out['age_without_year'] = med_iqr(sub.loc[~sub['_has_year'], '_age'])
        out['early_day_with_year'] = med_iqr(sub.loc[sub['_has_year'], '_early_day'])
        out['early_day_without_year'] = med_iqr(sub.loc[~sub['_has_year'], '_early_day'])
        return out

    def describe(sub):
        period = np.select([sub['_op_year'] <= 2022, sub['_op_year'] == 2023, sub['_op_year'] == 2024],
                           ['2017-2022', '2023', '2024'], '2025-2026')
        return {'n': int(len(sub)), 'centre': counts(sub['_centre']), 'country': counts(sub['_country']),
                'operative_period': counts(period), 'pad_group': counts(sub['_burden']),
                'window_closed_before_extract': int(sub['_closed_common'].sum()),
                'age': med_iqr(sub['_age']), 'early_day': med_iqr(sub['_early_day'])}

    with_year = describe(f.loc[f['_has_year']])
    without_year = describe(f.loc[~f['_has_year']])

    # Availability model among the 412 one-pad and two-or-more early users (descriptive).
    import statsmodels.api as sm
    av = f.loc[f['_burden'].isin(['one', 'two_or_more'])].copy()
    Xa = pd.DataFrame({'intercept': 1.0,
                       'two_or_more': av['_burden'].eq('two_or_more').astype(float),
                       'age_per10_cent65': (pd.to_numeric(av['_age'], errors='coerce') - 65.0) / 10.0,
                       'early_day_per30_cent90': (pd.to_numeric(av['_early_day'], errors='coerce') - 90.0) / 30.0,
                       'centre_belchatow': av['_centre'].eq('Bełchatów').astype(float),
                       'centre_salve': av['_centre'].eq('Salve Medica').astype(float),
                       'window_open_at_extract': (~av['_closed_common']).astype(float)})
    if not np.isfinite(Xa.to_numpy(float)).all():
        fail('AVAILABILITY_COVARIATES')
    fa = sm.Logit(av['_has_year'].astype(float).to_numpy(), Xa).fit(disp=False, maxiter=200)
    if not fa.mle_retvals.get('converged', False):
        fail('AVAILABILITY_MODEL_NONCONVERGENCE')
    availability_model = {'n': int(len(av)), 'events_with_year': int(av['_has_year'].sum()),
                          'params': {c: {'or': float(np.exp(fa.params[c])),
                                         'wald_ci': [float(np.exp(v)) for v in fa.conf_int().loc[c]]}
                                     for c in Xa.columns}}

    # Robotic patients with and without an early assessment.
    rob = wide.loc[wide.index.isin({str(x) for x in robotic})].copy()
    early_known = {str(x) for x in sets['early_status_known']}
    rob['_early'] = rob.index.isin(early_known)
    rob['_surgery'] = pd.to_datetime(rob['surgery_date'].str.strip(), errors='coerce')
    rob['_op_year'] = rob['_surgery'].dt.year
    valid_ids = {str(x) for x in candidate[ID]}
    rob['_any_valid_continence'] = rob.index.isin(valid_ids)
    rob['_no_dated_contact'] = rob['followup_assessable'].astype(str).str.strip().isin(['False', 'false', '0'])

    def describe_robotic(sub):
        period = np.select([sub['_op_year'] <= 2022, sub['_op_year'] == 2023, sub['_op_year'] == 2024,
                            sub['_op_year'].isna()], ['2014-2022', '2023', '2024', 'missing'], '2025-2026')
        return {'n': int(len(sub)), 'centre': counts(sub['operation_centre']), 'country': counts(sub['country']),
                'operative_period': counts(period), 'age': med_iqr(sub['age']),
                'any_valid_dated_postoperative_continence_record': int(sub['_any_valid_continence'].sum()),
                'no_dated_postoperative_contact': int(sub['_no_dated_contact'].sum()),
                'no_dated_postoperative_contact_by_country': counts(sub.loc[sub['_no_dated_contact'], 'country'])}

    robotic_with_early = describe_robotic(rob.loc[rob['_early']])
    robotic_without_early = describe_robotic(rob.loc[~rob['_early']])
    if robotic_with_early['n'] != 644 or robotic_without_early['n'] != 753:
        fail('ROBOTIC_EARLY_SPLIT', f"{robotic_with_early['n']} {robotic_without_early['n']}")

    # Source-level month ranges.
    def month_range(series):
        s = pd.to_datetime(series, errors='coerce').dropna()
        return {'first_month': s.min().strftime('%Y-%m'), 'last_month': s.max().strftime('%Y-%m')} if len(s) else None

    cand = candidate.copy()
    cand['_pid'] = cand[ID].astype(str)
    cand['_centre'] = cand['_pid'].map(wide['operation_centre'])
    source_ranges = {}
    for centre in sorted(EXTRACT_LEADS):
        rr = rob.loc[rob['operation_centre'].eq(centre)]
        ee = f.loc[f['_centre'].eq(centre)]
        cc = cand.loc[cand['_centre'].eq(centre)]
        source_ranges[centre] = {'robotic_operations': month_range(rr['_surgery']),
                                 'early_pad_user_operations': month_range(ee['_surgery']),
                                 'dated_pad_status_records': month_range(cc['_date']),
                                 'extract_date_lead': EXTRACT_LEADS[centre]}

    # Missing-outcome bounds and pattern-mixture grid.
    def missing_outcome(mask, label):
        sub = f.loc[mask]
        g = {}
        for key, level in (('one', 'one'), ('two', 'two_or_more')):
            m = sub['_burden'].eq(level)
            n_all = int(m.sum())
            obs = int((m & sub['_has_year']).sum())
            ev = int((m & sub['_year_status'].eq(1)).sum())
            g[key] = {'early_users': n_all, 'observed': obs, 'events': ev, 'unobserved': n_all - obs}
        N1, e1, u1, n1 = g['one']['early_users'], g['one']['events'], g['one']['unobserved'], g['one']['observed']
        N2, e2, u2, n2 = g['two']['early_users'], g['two']['events'], g['two']['unobserved'], g['two']['observed']
        p1, p2 = e1 / n1, e2 / n2

        def D(q1, q2):
            return (e1 + u1 * q1) / N1 - (e2 + u2 * q2) / N2

        grid_q = [round(x, 2) for x in np.arange(0, 1.0001, 0.05)]
        grid = [[D(q1, q2) for q2 in grid_q] for q1 in grid_q]
        fine = np.arange(0, 1.00001, 0.01)
        positive_share = float(np.mean([[D(a, b) > 0 for b in fine] for a in fine]))
        # Tipping values.
        q1_tip_if_two_mar = (N1 * (e2 + u2 * p2) / N2 - e1) / u1 if u1 else None
        q2_tip_if_one_mar = ((e1 + u1 * p1) / N1 * N2 - e2) / u2 if u2 else None
        # Symmetric shift: unobserved one-pad users delta lower, unobserved two-or-more delta higher.
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            if D(min(1, max(0, p1 - mid)), min(1, max(0, p2 + mid))) > 0:
                lo = mid
            else:
                hi = mid
        delta_tip = (lo + hi) / 2 if D(max(0, p1 - 1), min(1, p2 + 1)) <= 0 else None
        equal_q = {str(q): D(q, q) for q in (0.0, 0.25, 0.5, 0.75, 1.0)}
        return {'label': label, 'groups': g, 'observed_one': p1, 'observed_two': p2,
                'observed_difference': p1 - p2,
                'mar_within_group_difference': D(p1, p2),
                'lower_bound': D(0.0, 1.0), 'upper_bound': D(1.0, 0.0),
                'equal_unobserved_proportion_difference': equal_q,
                'q1_tipping_if_unobserved_two_or_more_like_observed': q1_tip_if_two_mar,
                'q2_tipping_if_unobserved_one_pad_like_observed': q2_tip_if_one_mar,
                'symmetric_shift_tipping_delta': delta_tip,
                'grid_step': 0.05, 'grid_q': grid_q, 'grid_difference_rows_q1_cols_q2': grid,
                'share_of_unit_square_with_positive_difference_step_0_01': positive_share}

    missing = {'all_early_users': missing_outcome(everyone, 'all_one_and_two_or_more_early_users'),
               'window_closed_before_common_extract': missing_outcome(f['_closed_common'], 'window_closed')}
    rv = missing['all_early_users']
    if not (abs(rv['lower_bound'] + 0.376) < 5e-3 and abs(rv['upper_bound'] - 0.643) < 5e-3):
        fail('REVIEWER_BOUNDS_ARITHMETIC', f"{rv['lower_bound']} {rv['upper_bound']}")

    # Post hoc country model without the one-year assessment day (201 classifiable pairs).
    sub = f.loc[f['_has_year'] & f['_burden'].isin(['one', 'two_or_more'])].reset_index(drop=True)
    y = sub['_year_status'].eq(1).astype(float).to_numpy()
    if len(sub) != 201 or int(y.sum()) != 82:
        fail('CLASSIFIABLE_SET')

    def fit_variant(cols, seed):
        X = pd.DataFrame({'intercept': np.ones(len(sub))})
        for k, v in cols.items():
            X[k] = v
        fit = sm.Logit(y, X).fit(disp=False, maxiter=200)
        if not fit.mle_retvals.get('converged', False):
            fail('MODEL_NONCONVERGENCE')
        names = list(X.columns)
        bi = names.index('two_or_more')

        def standardize(Xm, coef):
            lin = Xm.to_numpy(float) @ coef - Xm['two_or_more'].to_numpy(float) * coef[bi]
            p_one = 1 / (1 + np.exp(-lin))
            p_two = 1 / (1 + np.exp(-(lin + coef[bi])))
            return float(p_one.mean()), float(p_two.mean())

        s1, s2 = standardize(X, fit.params.to_numpy(float))
        rng = np.random.default_rng(seed)
        diffs, failed = [], 0
        for _ in range(DRAWS):
            idx = rng.integers(0, len(sub), len(sub))
            try:
                fb = sm.Logit(y[idx], X.iloc[idx]).fit(disp=False, maxiter=200)
                if not fb.mle_retvals.get('converged', False):
                    failed += 1
                    continue
                b1, b2 = standardize(X.iloc[idx].reset_index(drop=True), fb.params.to_numpy(float))
                diffs.append(b1 - b2)
            except Exception:
                failed += 1
        return {'covariates': names, 'converged': True, 'n': int(len(sub)), 'events': int(y.sum()),
                'params': {c: {'coef': float(fit.params[c]), 'or': float(np.exp(fit.params[c])),
                               'wald_ci_or': [float(np.exp(v)) for v in fit.conf_int().loc[c]]} for c in names},
                'standardized_one_pad': s1, 'standardized_two_or_more': s2, 'standardized_difference': s1 - s2,
                'bootstrap': {'seed': seed, 'draws': DRAWS, 'failed_fits': failed,
                              'lower': float(np.percentile(diffs, 2.5)), 'upper': float(np.percentile(diffs, 97.5))}}

    base = {'two_or_more': sub['_burden'].eq('two_or_more').astype(float).to_numpy(),
            'age_per10_cent65': (pd.to_numeric(sub['_age'], errors='coerce').to_numpy(float) - 65.0) / 10.0,
            'early_day_per30_cent90': (pd.to_numeric(sub['_early_day'], errors='coerce').to_numpy(float) - 90.0) / 30.0,
            'country_us': sub['_country'].eq('United States').astype(float).to_numpy()}
    country_no_yearday = fit_variant(base, MODEL_SEED)

    record = {
        'analysis_id': 'M1-SELECTION', 'amendment': 'A-OBS-3', 'status': 'exploratory_post_hoc_disclosed',
        'draws': DRAWS, 'reference_seed': REFERENCE_SEED, 'model_seed': MODEL_SEED,
        'extract_date_leads': EXTRACT_LEADS, 'common_extract_date': COMMON_EXTRACT.strftime('%Y-%m-%d'),
        'year_window_close_day': YEAR_WINDOW_CLOSE,
        'window_closed_early_users': {'common': int(f['_closed_common'].sum()), 'centre': int(f['_closed_centre'].sum())},
        'contrasts': contrasts,
        'availability': {'all_early_users': availability(everyone),
                         'window_closed_before_common_extract': availability(f['_closed_common']),
                         'window_open_at_common_extract': availability(~f['_closed_common']),
                         'with_year_record': with_year, 'without_year_record': without_year,
                         'model_one_vs_two_or_more': availability_model},
        'robotic_early_assessment': {'with_early_assessment': robotic_with_early,
                                     'without_early_assessment': robotic_without_early},
        'source_month_ranges': source_ranges,
        'missing_outcome': missing,
        'posthoc_country_model_without_year_day': country_no_yearday,
        'counts_in_classifiable_pairs': {
            'device_evidence_one': int((f['_has_year'] & f['_burden'].eq('one') & device).sum()),
            'device_evidence_two_or_more': int((f['_has_year'] & f['_burden'].eq('two_or_more') & device).sum()),
            'platform_flag_pairs': int((f['_has_year'] & f['_platform_flag']).sum()),
            'epic_pairs': int((f['_has_year'] & f['_epic']).sum()),
            'range_reliant_two_or_more': int(range_reliant.sum())},
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
    for pid in id_set:
        if pid and len(pid) > 3 and pid in text:
            fail('IDENTIFIER_LEAK')
    if verify:
        if json.loads(EVIDENCE.read_text()) != json.loads(text):
            fail('SAVED_RECORD_MISMATCH')
        print(json.dumps({'status': 'saved_selection_record_recomputed_exactly'}))
        return 0
    EVIDENCE.write_text(text)
    print(json.dumps({'status': 'written', 'path': str(EVIDENCE)}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
