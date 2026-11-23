"""Post hoc two-group analyses, amendment A-OBS-2 (Tier D prototype).

Covers the external-assessment recommendations that need new computation:
a post hoc adjusted analysis restricted to the 201 classifiable pairs, a
contrast-consistent burden rule (P6: same-side incompatible intervals join
their side; invalid evidence stays unresolved), an exact-count-only subset,
and extended Table 1 descriptive aggregates.

Status: exploratory prototype. Calibration gates reproduce the frozen P0
quantities exactly or the run FAILS. No patient identifier, exact clinical
date, narrative or private filename enters the emitted record; the writer
scans the final JSON against the input identity set before saving.
Tier A assurance (independent reproduction, two-family methods review,
results review) is NOT claimed here and remains required before any
publication-defining use.

Local execution only, from manuscript1/:
  PY=/home/konrad/.venvs/konsta-research-py314/bin/python
  "$PY" -B scripts/10_posthoc_twogroup_analyses.py --verify
--verify recomputes and compares against evidence/POSTHOC_TWOGROUP.json
without writing.
"""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / 'evidence/POSTHOC_TWOGROUP.json'
SEED = 20260914
DRAWS = 2000


def fail(code, detail=''):
    print(f'POSTHOC_TWOGROUP_FAILED {code} {detail}'.strip(), file=sys.stderr)
    sys.exit(1)


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_drv06():
    return load_module('drv06', '06_derive_observed_assessments.py')


cohort_mod = load_module('cohort', 'cohort.py')


def wilson(numer, denom):
    if denom == 0:
        return {'estimable': False}
    from math import sqrt
    z = 1.959963984540054
    p = numer / denom
    den = 1 + z * z / denom
    centre = (p + z * z / (2 * denom)) / den
    half = z * sqrt(p * (1 - p) / denom + z * z / (4 * denom * denom)) / den
    return {'estimable': True, 'estimate': p,
            'lower': max(0.0, centre - half), 'upper': min(1.0, centre + half)}


def boot_diff(a_out, a_n, b_out, b_n, seed, draws=DRAWS):
    rng = np.random.default_rng(seed)
    a = np.array([1] * a_out + [0] * (a_n - a_out), dtype=float)
    b = np.array([1] * b_out + [0] * (b_n - b_out), dtype=float)
    diffs, failed = [], 0
    for _ in range(draws):
        sa = rng.integers(0, a_n, a_n)
        sb = rng.integers(0, b_n, b_n)
        try:
            diffs.append(float(a[sa].mean() - b[sb].mean()))
        except Exception:
            failed += 1
    diffs = np.array(diffs)
    return {'failed_draws': failed,
            'lower': float(np.percentile(diffs, 2.5)),
            'upper': float(np.percentile(diffs, 97.5))}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Post hoc two-group analyses.')
    ap.add_argument('--verify', action='store_true')
    cohort_mod.add_cohort_args(ap)
    args = ap.parse_args(argv)
    verify = args.verify
    cohort_name = args.cohort
    out_path = cohort_mod.output_path(EVIDENCE, cohort_name)
    if not verify:
        cohort_mod.assert_writable_output(out_path)

    d = load_drv06()
    res = d.source_derive(cohort=cohort_name)
    if res['source_verification']['bound_inputs_before'] != 122:
        fail('BOUND_INPUT_COUNT', str(res['source_verification']['bound_inputs_before']))
    selection, sets = res['selection'], res['sets']
    frame = res['patients']
    candidate = res['candidate']
    patients = d.read_core_tables(d.bind_root(d.RELEASE))[0]
    id_set = set(patients[d.ID].astype(str))
    pairs = frame.loc[frame[d.ID].isin(sets['early_users_with_year'])].copy()
    out = pairs['_year_status'].eq(1).to_numpy()
    burden = pairs['_burden'].astype(str)
    one = burden.eq('one')
    two = burden.eq('two_or_more')

    def contrast(mask_a, mask_b):
        na, nb = int(mask_a.sum()), int(mask_b.sum())
        oa, ob = int((out[mask_a.to_numpy()] == 1).sum()), int((out[mask_b.to_numpy()] == 1).sum())
        est = oa / na - ob / nb
        return {'a_n': na, 'a_events': oa, 'b_n': nb, 'b_events': ob,
                'difference': est, 'bootstrap': boot_diff(oa, na, ob, nb, SEED)}

    ref = contrast(one, two)

    # Country-standardized check (reviewer arithmetic cross-check).
    classifiable = (one | two)
    n_classifiable = int(classifiable.sum())
    std_w = {c: int((classifiable & (pairs['_country'] == c)).sum()) / n_classifiable
             for c in ('Poland', 'United States')}
    std_one = sum((out[(burden.eq('one')) & (pairs['_country'] == c)].mean()) * w
                  for c, w in std_w.items())
    std_two = sum((out[(burden.eq('two_or_more')) & (pairs['_country'] == c)].mean()) * w
                  for c, w in std_w.items())
    std_diff = float(std_one - std_two)
    country_std_diff = round(std_diff, 4)

    # P6 contrast-consistent reclassification from day-row evidence.
    chosen = selection['selected']['early']
    keys = set(zip(chosen[d.ID], chosen._date))
    member = pd.Series([(pid, when) in keys for pid, when in
                        zip(candidate[d.ID], candidate._date)], index=candidate.index)
    day_rows = candidate.loc[member].copy()
    status_map = dict(zip(chosen[d.ID], chosen._status))
    mapped = day_rows[d.ID].map(status_map).astype('Int64')
    usable = day_rows.loc[day_rows._status.eq(mapped).fillna(False).astype(bool)]
    grouped = {pid: group for pid, group in usable.groupby(d.ID, sort=False)}
    p6_map, p6_evidence, exact_map = {}, [], {}
    for pid in pairs[d.ID]:
        group = grouped.get(pid)
        level, flags, _ = d.classify_day(group)
        cols = d.quantity_columns(group)
        new_level = level
        if level == 'unresolved_quantity_evidence' and not flags['invalid_quantity_evidence'] \
                and flags['incompatible_valid_intervals']:
            lowers, uppers = [], []
            for i in group.index:
                if bool(cols['informative'][i]) and not bool(cols['invalid'][i]):
                    lo = cols['lower'][i]
    p6_map, p6_evidence, exact_map = {}, [], {}
    for pid in pairs[d.ID]:
        group = grouped.get(pid)
        level, flags, _ = d.classify_day(group)
        cols = d.quantity_columns(group)
        new_level = level
        if level == 'unresolved_quantity_evidence' and not flags['invalid_quantity_evidence'] \
                and flags['incompatible_valid_intervals']:
            lowers, uppers = [], []
            for i in group.index:
                if bool(cols['informative'][i]) and not bool(cols['invalid'][i]):
                    lowers.append(None if pd.isna(cols['lower'][i]) else float(cols['lower'][i]))
                    uppers.append(None if pd.isna(cols['upper'][i]) else float(cols['upper'][i]))
            lo_known = [v for v in lowers if v is not None]
            hi_known = [v for v in uppers if v is not None]
            pair_sig = ' vs '.join(
                f"[{'' if a is None else a},{'' if b is None else b}]"
                for a, b in zip(lowers, uppers))
            if lo_known and min(lo_known) >= 2.0:
                new_level = 'two_or_more (P6 same-side)'
            elif hi_known and max(hi_known) <= 1.0:
                new_level = 'one (P6 same-side)'
            else:
                new_level = level + ' (P6 held: cross-threshold)'
            p6_evidence.append({'intervals': pair_sig, 'reclassified_as': new_level,
                                'year_status': 'pad_free' if bool(out[(pairs[d.ID] == pid).to_numpy()][0]) else 'pad_use'})
        p6_map[pid] = new_level
        strict_exact = True
        for i in group.index:
            if not (bool(cols['informative'][i]) and not bool(cols['invalid'][i])):
                continue
            import math
            plo = cols['lower'][i]
            phi = cols['upper'][i]
            if pd.isna(plo) or pd.isna(phi) or float(plo) != float(phi):
                strict_exact = False
                break
            raw_lo = group.loc[i, 'pads_per_day_min']
            raw_hi = group.loc[i, 'pads_per_day_max']
            raw_pt = group.loc[i, 'pads_per_day']
            blank = lambda v: (v is None) or (isinstance(v, float) and math.isnan(v)) or str(v).strip() == ''
            if not ((not blank(raw_lo) and not blank(raw_hi) and str(raw_lo).strip() == str(raw_hi).strip()
                     and (blank(raw_pt) or str(raw_pt).strip() == str(raw_lo).strip()))
                    or (blank(raw_lo) and blank(raw_hi) and not blank(raw_pt))):
                strict_exact = False
                break
        exact_map[pid] = bool(strict_exact)
    burden_p6 = pairs[d.ID].map(p6_map)
    is_two_p6 = burden_p6.str.startswith('two_or_more')
    p6 = contrast(one, is_two_p6)
    exact_mask = pairs[d.ID].map(exact_map).fillna(False).astype(bool)
    ex = contrast(one & exact_mask, two & exact_mask)

    # Post hoc adjusted model on the classifiable pairs.
    sub = pairs.loc[(one | two).to_numpy()].copy().reset_index(drop=True)
    y = sub['_year_status'].eq(1).astype(float).to_numpy()
    observed_gates = {
        'pair_count': int(len(pairs)),
        'overall_events': int(out.sum()),
        'one_n': int(ref['a_n']),
        'two_n': int(ref['b_n']),
        'one_events': int(ref['a_events']),
        'two_events': int(ref['b_events']),
        'difference': float(ref['difference']),
        'country_standardized_difference': float(std_diff),
        'classifiable_count': int(len(sub)),
        'classifiable_events': int(y.sum()),
    }
    try:
        cohort_mod.check_or_record_gates(
            '10_posthoc_twogroup_analyses', cohort_name, observed_gates, record=args.record_gates)
    except cohort_mod.GateError as exc:
        fail(exc.code, exc.detail)
    X = pd.DataFrame({
        'intercept': np.ones(len(sub)),
        'burden_two_or_more': (sub['_burden'].astype(str) == 'two_or_more').astype(float).to_numpy(),
        'age_per10_cent65': (pd.to_numeric(sub['_age'], errors='coerce').to_numpy(float) - 65.0) / 10.0,
        'country_us': (sub['_country'].astype(str) == 'United States').astype(float).to_numpy(),
        'early_day_per30_cent90': (pd.to_numeric(sub['_early_day'], errors='coerce').to_numpy(float) - 90.0) / 30.0,
        'year_day_per30_cent365': (pd.to_numeric(sub['_year_day'], errors='coerce').to_numpy(float) - 365.0) / 30.0,
    })
    if not np.isfinite(X.to_numpy(float)).all():
        fail('COVARIATE_COMPLETENESS', str(int(np.isfinite(X.to_numpy(float)).all(axis=1).sum())))
    import statsmodels.api as sm

    def fit_variant(name, cols, seed, burden_col='burden_two_or_more'):
        Xv = pd.DataFrame({'intercept': np.ones(len(sub))})
        for cname, series in cols.items():
            Xv[cname] = series
        if not np.isfinite(Xv.to_numpy(float)).all():
            fail('COVARIATE_COMPLETENESS_' + name,
                 str(int(np.isfinite(Xv.to_numpy(float)).all(axis=1).sum())))
        f = sm.Logit(y, Xv).fit(disp=False, maxiter=200)
        if not bool(f.mle_retvals.get('converged', False)):
            fail('MODEL_NONCONVERGENCE_' + name, str(f.mle_retvals))
        bi = list(Xv.columns).index(burden_col)
        others = [c for c in Xv.columns if c not in ('intercept', burden_col)]

        def _std(df, coef):
            lin = coef[0] + sum(coef[list(Xv.columns).index(c)] * df[c].to_numpy(float) for c in others)
            lo = lin.to_numpy(float) if hasattr(lin, 'to_numpy') else lin
            p1 = 1 / (1 + np.exp(-lo))
            p0 = 1 / (1 + np.exp(-(lo + coef[bi])))
            return float(p1.mean()), float(p0.mean()), float(p1.mean() - p0.mean())

        co = f.params.to_numpy(float)
        s1, s0, sd = _std(Xv, co)
        rng = np.random.default_rng(seed)
        sdiffs, failed = [], 0
        for _ in range(DRAWS):
            s = rng.integers(0, len(sub), len(sub))
            try:
                fb = sm.Logit(y[s], Xv.iloc[s]).fit(disp=False, maxiter=200)
                if not bool(fb.mle_retvals.get('converged', False)):
                    failed += 1
                    continue
                _, _, dd = _std(Xv.iloc[s].reset_index(drop=True), fb.params.to_numpy(float))
                sdiffs.append(dd)
            except Exception:
                failed += 1
        sdiffs = np.array(sdiffs)
        if failed / DRAWS > 0.05:
            fail('BOOTSTRAP_FAILURE_RATE_' + name, str(failed))
        return {'covariates': list(Xv.columns), 'converged': True,
                'params': {c: {'coef': float(f.params[c]), 'or': float(np.exp(f.params[c])),
                               'wald_ci': [float(v) for v in f.conf_int().loc[c].to_numpy()]} for c in Xv.columns},
                'standardized_one_pad': s1, 'standardized_two_or_more': s0,
                'standardized_difference': sd,
                'bootstrap': {'seed': seed, 'draws': DRAWS, 'failed_fits': failed,
                              'lower': float(np.percentile(sdiffs, 2.5)),
                              'upper': float(np.percentile(sdiffs, 97.5))}}

    _base_cols = {
        'burden_two_or_more': (sub['_burden'].astype(str) == 'two_or_more').astype(float).to_numpy(),
        'age_per10_cent65': (pd.to_numeric(sub['_age'], errors='coerce').to_numpy(float) - 65.0) / 10.0,
        'early_day_per30_cent90': (pd.to_numeric(sub['_early_day'], errors='coerce').to_numpy(float) - 90.0) / 30.0,
        'year_day_per30_cent365': (pd.to_numeric(sub['_year_day'], errors='coerce').to_numpy(float) - 365.0) / 30.0,
    }
    _country_us = (sub['_country'].astype(str) == 'United States').astype(float).to_numpy()
    model = fit_variant('country', {**_base_cols, 'country_us': _country_us}, SEED + 1)
    model['n'] = int(len(sub))
    model['events'] = int(y.sum())

    # Centre-adjusted sensitivity variants (reviewer request): centre rather
    # than country (country is determined by centre), plus a parsimonious
    # recent-period indicator, with and without the year assessment day
    # (unknown at three months, so timing-adjusted association, not forecast).
    _wide = pd.read_csv(d.RELEASE / 'tables/patient_wide.csv', dtype=str,
                        keep_default_na=False, usecols=[d.ID, 'operation_centre', 'surgery_date'])
    _wide = _wide.set_index(_wide[d.ID].astype(str)).reindex(sub[d.ID].astype(str))
    _cen = _wide['operation_centre'].astype(str)
    _yr = pd.to_datetime(_wide['surgery_date'].astype(str).str.strip(), errors='coerce').dt.year.to_numpy()
    if bool(pd.isna(_yr).any()):
        fail('CENTRE_PERIOD_COMPLETENESS', str(int(pd.isna(_yr).sum())))
    _centre_b = (_cen.to_numpy() == 'Bełchatów').astype(float)
    _centre_s = (_cen.to_numpy() == 'Salve Medica').astype(float)
    _period_recent = (_yr >= cohort_mod.recent_period_start_year(cohort_name)).astype(float)
    _centre_base = {'burden_two_or_more': _base_cols['burden_two_or_more'],
                    'age_per10_cent65': _base_cols['age_per10_cent65'],
                    'early_day_per30_cent90': _base_cols['early_day_per30_cent90'],
                    'centre_belchatow': _centre_b, 'centre_salve': _centre_s,
                    'period_recent': _period_recent}
    _v1 = fit_variant('centre_no_yearday', dict(_centre_base), SEED + 10)
    _v2 = fit_variant('centre_yearday',
                      {**_centre_base,
                       'year_day_per30_cent365': _base_cols['year_day_per30_cent365']}, SEED + 11)
    centre_models = {'no_yearday': _v1, 'with_yearday': _v2}

    # Extended Table 1 aggregates among the paired early users (distributions only).
    release_root = d.RELEASE
    pw = pd.read_csv(release_root / 'tables/patient_wide.csv', dtype=str, keep_default_na=False)
    pair_ids = set(pairs[d.ID].astype(str))
    pw = pw.loc[pw[d.ID].astype(str).isin(pair_ids)].copy()
    n_pairs = int(len(pairs))
    if len(pw) != n_pairs:
        fail('TABLE1_DENOMINATOR', str(len(pw)))

    def numcol(name):
        return pd.to_numeric(pw[name].replace('', np.nan), errors='coerce')

    def dist(name):
        if name not in pw.columns:
            return {'column_absent_in_release': True}
        s = pw[name].astype(str)
        s = s.mask(s.str.strip() == '', 'missing_not_recorded')
        return {str(k): int(v) for k, v in s.value_counts().items()}

    def med_iqr(name):
        if name not in pw.columns:
            return {'column_absent_in_release': True}
        v = numcol(name).dropna().to_numpy(float)
        if len(v) == 0:
            return {'n': 0, 'missing': n_pairs}
        return {'n': int(len(v)), 'missing': int(n_pairs - len(v)),
                'median': float(np.median(v)), 'q1': float(np.percentile(v, 25)),
                'q3': float(np.percentile(v, 75))}

    early = selection['selected']['early'].set_index(d.ID)
    yeard = selection['selected']['year'].set_index(d.ID)
    tx = pw['first_postoperative_treatment_date'].astype(str).str.strip() != ''
    tx_doc = pw['postoperative_treatment_any_documented'].astype(str)
    surg = pd.to_datetime(pw['surgery_date'].astype(str).str.strip(), errors='coerce')
    txd = pd.to_datetime(pw['first_postoperative_treatment_date'].astype(str).str.strip(), errors='coerce')
    tx_offset = (txd - surg).dt.days
    # Per-pair early/year days must be reattached without disturbing the frame order.
    pmap = pairs.set_index(d.ID)
    eday = pd.to_numeric(pmap['_early_day'], errors='coerce')
    yday = pd.to_numeric(pmap['_year_day'], errors='coerce')
    pw_ordered = pw.set_index(pw[d.ID].astype(str)).reindex(pmap.index.astype(str))
    t_off = (pd.to_datetime(pw_ordered['first_postoperative_treatment_date'].astype(str).str.strip(), errors='coerce')
             - pd.to_datetime(pw_ordered['surgery_date'].astype(str).str.strip(), errors='coerce')).dt.days
    e_off = pd.to_numeric(pmap['_early_day'], errors='coerce').to_numpy(float)
    y_off = pd.to_numeric(pmap['_year_day'], errors='coerce').to_numpy(float)
    t_arr = t_off.to_numpy(float)
    t_known = pd.notna(t_off).to_numpy()
    between = pd.Series(t_known & (np.where(t_known, t_arr, np.nan) > e_off)
                        & (np.where(t_known, t_arr, np.nan) <= y_off), index=pmap.index)
    burden_arr = pmap['_burden'].astype(str).to_numpy()
    between_by_burden = {}
    for lvl in ['one', 'two_or_more', 'nonconflicting_quantity_uncertain', 'unresolved_quantity_evidence']:
        m = burden_arr == lvl
        between_by_burden[lvl] = {'n': int(m.sum()), 'treatment_starting_between_assessments': int((between.to_numpy() & m).sum())}
    surg_missing = int(surg.isna().sum())
    tx_date_unparseable = int(tx.sum() - int(pd.notna(txd).sum()))

    # By-group Table 1 extension among the 201 classifiable pairs.
    g1 = (burden_arr == 'one')
    g2 = (burden_arr == 'two_or_more')
    pwg = pw_ordered.reset_index(drop=True)
    op_year = pd.to_datetime(pwg['surgery_date'].astype(str).str.strip(), errors='coerce').dt.year

    def _med(x):
        v = pd.to_numeric(x, errors='coerce').dropna().to_numpy(float)
        return {'median': round(float(np.median(v)), 1), 'q1': round(float(np.percentile(v, 25)), 1),
                'q3': round(float(np.percentile(v, 75)), 1)} if len(v) else None

    def _diststr(col):
        s = pwg[col].astype(str)
        s = s.mask(s.str.strip() == '', 'missing_not_recorded')
        return {str(k): int(v) for k, v in s.value_counts().items()}

    def _grp(mask, col):
        s = pwg.loc[mask, col].astype(str)
        s = s.mask(s.str.strip() == '', 'missing_not_recorded')
        return {str(k): int(v) for k, v in s.value_counts().items()}

    def _grpmed(mask, col, ntot):
        v = pd.to_numeric(pwg.loc[mask, col].replace('', np.nan), errors='coerce').dropna().to_numpy(float)
        return {'median': round(float(np.median(v)), 1), 'q1': round(float(np.percentile(v, 25)), 1),
                'q3': round(float(np.percentile(v, 75)), 1), 'n': int(len(v)),
                'missing': int(ntot - len(v))} if len(v) else None

    n_g1, n_g2 = int(g1.sum()), int(g2.sum())
    by_group = {
        'n': {'one': n_g1, 'two_or_more': n_g2},
        'country': {'one': _grp(g1, 'country'), 'two_or_more': _grp(g2, 'country')},
        'centre': {'one': _grp(g1, 'operation_centre'), 'two_or_more': _grp(g2, 'operation_centre')},
        'bmi': {'one': _grpmed(g1, 'bmi', n_g1), 'two_or_more': _grpmed(g2, 'bmi', n_g2)},
        'psa_preop': {'one': _grpmed(g1, 'psa_preop', n_g1), 'two_or_more': _grpmed(g2, 'psa_preop', n_g2)},
        'isup_grade_preop': {'one': _grp(g1, 'isup_grade_preop'), 'two_or_more': _grp(g2, 'isup_grade_preop')},
        'nerve_sparing_state': {'one': _grp(g1, 'nerve_sparing_state'), 'two_or_more': _grp(g2, 'nerve_sparing_state')},
        'pad_count_instrument_src': {'one': _grp(g1, 'pad_count_instrument_src'), 'two_or_more': _grp(g2, 'pad_count_instrument_src')},
        'continence_assessment_method_src': {'one': _grp(g1, 'continence_assessment_method_src'), 'two_or_more': _grp(g2, 'continence_assessment_method_src')},
        'postoperative_treatment_any_documented': {'one': _grp(g1, 'postoperative_treatment_any_documented'), 'two_or_more': _grp(g2, 'postoperative_treatment_any_documented')},
        'any_complication_30d': {'one': _grp(g1, 'any_complication_30d'), 'two_or_more': _grp(g2, 'any_complication_30d')},
        'any_complication_90d': {'one': _grp(g1, 'any_complication_90d'), 'two_or_more': _grp(g2, 'any_complication_90d')},
    }
    pwg = pwg.assign(_ey=pd.to_numeric(pmap['_early_day'], errors='coerce').to_numpy(float),
                     _yd=pd.to_numeric(pmap['_year_day'], errors='coerce').to_numpy(float),
                     _ag=pd.to_numeric(pmap['_age'], errors='coerce').to_numpy(float))
    by_group['early_day'] = {'one': _med(pwg.loc[g1, '_ey']), 'two_or_more': _med(pwg.loc[g2, '_ey'])}
    by_group['year_day'] = {'one': _med(pwg.loc[g1, '_yd']), 'two_or_more': _med(pwg.loc[g2, '_yd'])}
    by_group['age'] = {'one': _med(pwg.loc[g1, '_ag']), 'two_or_more': _med(pwg.loc[g2, '_ag'])}
    op_period = pd.Series(np.where(op_year.isna(), 'missing', np.where(op_year <= 2024, '2017-2024', '2025-2026')), index=pwg.index)
    by_group['operative_period'] = {'one': {str(k): int(v) for k, v in op_period[g1].value_counts().items()},
                                    'two_or_more': {str(k): int(v) for k, v in op_period[g2].value_counts().items()}}

    # EPIC-instrument-excluded contrast (patient-level instrument flag).
    instr = pwg['pad_count_instrument_src'].astype(str).str.strip()
    no_epic = (instr != 'EPIC').to_numpy()
    epic_n = int((~pd.Series(no_epic)).sum())
    ee = contrast(pd.Series(pd.Series(g1).to_numpy() & no_epic), pd.Series(pd.Series(g2).to_numpy() & no_epic))
    epic_excluded = {'excluded_epic_pairs': epic_n, **{k: ee[k] for k in ('a_n', 'b_n', 'a_events', 'b_events', 'difference')},
                     'bootstrap_ci': [ee['bootstrap']['lower'], ee['bootstrap']['upper']],
                     'failed_draws': ee['bootstrap']['failed_draws']}

    # The 23 range-reliant two-or-more pairs: distribution by centre, period, outcome.
    rel23 = ((burden_arr == 'two_or_more') & (~exact_mask.to_numpy())).tolist()
    rel23 = np.array(rel23, dtype=bool)
    spans = []
    for pid in pmap.index[rel23]:
        group = grouped.get(pid)
        cols = d.quantity_columns(group)
        los = [float(cols['lower'][i]) for i in group.index
               if bool(cols['informative'][i]) and not bool(cols['invalid'][i]) and pd.notna(cols['lower'][i])]
        his = [float(cols['upper'][i]) for i in group.index
               if bool(cols['informative'][i]) and not bool(cols['invalid'][i]) and pd.notna(cols['upper'][i])]
        spans.append((max(his) - min(los)) if los and his else float('nan'))
    spans = np.array(spans)
    has_spans = bool(len(spans) and not np.all(np.isnan(spans)))
    range23 = {
        'n': int(rel23.sum()),
        'pad_free': int((out[rel23] == 1).sum()),
        'by_centre': {str(k): int(v) for k, v in pwg.loc[rel23, 'operation_centre'].astype(str).value_counts().items()},
        'by_period': {str(k): int(v) for k, v in op_period[rel23].value_counts().items()},
        'span_width_median': round(float(np.nanmedian(spans)), 1) if has_spans else None,
        'span_width_min': round(float(np.nanmin(spans)), 1) if has_spans else None,
        'span_width_max': round(float(np.nanmax(spans)), 1) if has_spans else None,
    }
    table1 = {
        'denominator': n_pairs,
        'centre': dist('operation_centre'),
        'bmi': med_iqr('bmi'),
        'psa_preop': med_iqr('psa_preop'),
        'isup_grade_preop': dist('isup_grade_preop'),
        'nerve_sparing_state': dist('nerve_sparing_state'),
        'pad_count_instrument_src': dist('pad_count_instrument_src'),
        'continence_assessment_method_src': dist('continence_assessment_method_src'),
        'continence_baseline_text_state': dist('continence_baseline_text_state'),
        'postoperative_treatment_any_documented': dist('postoperative_treatment_any_documented'),
        'postoperative_treatment_date_present': {'yes': int(tx.sum()), 'no': int(n_pairs - int(tx.sum()))},
        'any_complication_30d': dist('any_complication_30d'),
        'any_complication_90d': dist('any_complication_90d'),
        'has_comp_urinary_retention': dist('has_comp_urinary_retention'),
        'epic_incontinence_3m_present': int((pw['epic_cp_urinary_incontinence_3m'].astype(str).str.strip() != '').sum()),
        'epic_incontinence_12m_present': int((pw['epic_cp_urinary_incontinence_12m'].astype(str).str.strip() != '').sum()),
        'distinct_surgeon_codes': int(pw['surgeon_code'].astype(str).str.strip().replace('', np.nan).nunique()),
        'treatment_timing': {
            'surgery_date_missing': surg_missing,
            'treatment_date_documented_but_unparseable': tx_date_unparseable,
            'first_treatment_starting_between_assessments_by_burden': between_by_burden,
        },
    }

    is_all_ops = cohort_name == cohort_mod.COHORT_ALL_OPERATIONS
    record = {
        'analysis_id': 'M1-POSTHOC', 'amendment': 'A-OBS-2', 'tier': 'D-prototype',
        'status': 'exploratory_post_hoc_disclosed',
        'seed': SEED, 'draws': DRAWS,
        'calibration': {'p0_difference': ref['difference'], 'overall_events': int(out.sum()),
                        'country_standardized_difference': country_std_diff},
        'p6_contrast_consistent_rule': {**{k: p6[k] for k in ('a_n', 'b_n', 'a_events', 'b_events', 'difference')},
                                        'bootstrap_ci': [p6['bootstrap']['lower'], p6['bootstrap']['upper']],
                                        'failed_draws': p6['bootstrap']['failed_draws'],
                                        **({'reclassified_unresolved': p6_evidence} if is_all_ops else
                                           # Counts only: one entry per man is row-level detail.
                                           {'reclassified_unresolved_count': len(p6_evidence),
                                            'reclassified_unresolved_by_year_status': {
                                                k: sum(1 for e in p6_evidence if e.get('year_status') == k)
                                                for k in sorted({e.get('year_status') for e in p6_evidence})}})},
        'exact_count_only_subset': {**{k: ex[k] for k in ('a_n', 'b_n', 'a_events', 'b_events', 'difference')},
                                    'bootstrap_ci': [ex['bootstrap']['lower'], ex['bootstrap']['upper']],
                                    'bootstrap_lower': ex['bootstrap']['lower'],
                                    'bootstrap_upper': ex['bootstrap']['upper'],
                                    'failed_draws': ex['bootstrap']['failed_draws']},
        'posthoc_adjusted_two_group_model': model,
        'centre_adjusted_sensitivity': centre_models,
        'table1_extension_226' if is_all_ops else 'table1_extension': table1,
        'table1_by_group_201' if is_all_ops else 'table1_by_group': by_group,
        'epic_excluded_contrast': epic_excluded,
        'range_reliant_23' if is_all_ops else 'range_reliant': range23,
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if not is_all_ops:
        record['cohort'] = res['cohort']
    text = json.dumps(record, indent=2, sort_keys=True)
    for pid in id_set:
        if pid and pid in text:
            fail('IDENTIFIER_LEAK', 'identity present in record')
    max_float_diff = 0.0
    if verify:
        if not out_path.is_file():
            fail('SAVED_POSTHOC_MISMATCH', 'missing_output')
        saved = out_path.read_text()
        if is_all_ops:
            ok, reason, max_float_diff = cohort_mod.compare_records_ignoring_provenance(
                json.loads(saved), json.loads(text), ignore_keys=('code_sha256',), float_tol=1e-12)
            if not ok:
                fail('SAVED_POSTHOC_MISMATCH', reason)
        elif saved != text and json.loads(saved) != json.loads(text):
            fail('SAVED_POSTHOC_MISMATCH', '')
        print(json.dumps({'status': 'saved_posthoc_recomputed_exactly', 'cohort': cohort_name,
                          'max_float_diff': max_float_diff}))
        return 0
    out_path.write_text(text)
    print(json.dumps({'status': 'posthoc_prototype_written',
                      'cohort': cohort_name,
                      'path': str(out_path),
                      'p6_difference': round(p6['difference'], 4),
                      'exact_difference': round(ex['difference'], 4),
                      'adjusted_standardized_difference': round(model['standardized_difference'], 4),
                      'events': model['events']}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))