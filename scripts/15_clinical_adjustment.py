"""Post hoc clinically adjusted comparison among the 201 men compared (amendment A-OBS-4).

Asks whether recorded clinical differences between the pad groups explain the one-year
difference. Every analysis here is post hoc and exploratory, added on 15 September 2026 after
the main result was known. Covariates were chosen on clinical grounds before any model was
fitted, from release fields recorded for at least 90% of the 201 men (pooled analyses) or for
most United States men (United States model):

1. Clinical model: pad group, age, three-month assessment day, centre, operative period
   (2025-2026 vs earlier), nerve sparing (not performed, or not stated, vs performed),
   pathological stage pT3-4 vs pT2, final ISUP grade group 3-5 vs 1-2 and body mass index.
   Complete cases for grade group and body mass index, with the crude difference in the
   same men.
2. The clinical model excluding men whose radiotherapy or androgen deprivation therapy
   started between the two assessments.
3. Inverse probability weighting with the clinical covariates (propensity for two or more
   pads), with weighted balance, weight range and effective sample sizes.
4. United States model: pad group, age, three-month day, nerve sparing, pathological stage,
   prostate volume, ASA class 3-4 and surgeon case sequence (per doubling). Complete cases.

Aggregate output only. No identifier, date or narrative is emitted, and the record is scanned
against the identity set before it is saved.

Run from manuscript1/:
  PY=/home/konrad/.venvs/konsta-research-py314/bin/python
  "$PY" -B scripts/15_clinical_adjustment.py            # build
  "$PY" -B scripts/15_clinical_adjustment.py --verify   # recompute, no write
"""

import argparse
import hashlib
import importlib.util
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / 'evidence/CLINICAL_ADJUSTMENT.json'
DRAWS = 2000
REFERENCE_SEED = 20260907
SEEDS = {'clinical': 20260926, 'clinical_no_interim_treatment': 20260927, 'ipw': 20260928,
         'united_states': 20260929}
BRIGHAM = "Brigham and Women's Hospital"
CENTRES = {'Bełchatów', 'Salve Medica', BRIGHAM}
NERVE_SPARING = {'performed', 'not_performed', 'not_assessed', 'unknown_after_review'}
CLINICAL = ['two_or_more', 'age_per10_cent65', 'early_day_per30_cent90', 'centre_belchatow', 'centre_salve',
            'period_recent', 'nerve_sparing_not_performed', 'nerve_sparing_not_stated', 'pt3_or_higher',
            'isup_3_or_higher', 'bmi_per5_cent28']
UNITED_STATES = ['two_or_more', 'age_per10_cent65', 'early_day_per30_cent90', 'nerve_sparing_not_performed',
                 'nerve_sparing_not_stated', 'pt3_or_higher', 'volume_per10_cent40', 'asa_3_or_4',
                 'surgeon_sequence_log2_cent32']


def fail(code, detail=''):
    print(f'CLINICAL_ADJUSTMENT_FAILED {code} {detail}'.strip(), file=sys.stderr)
    sys.exit(1)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cohort_mod = load('cohort', 'cohort.py')


def med_iqr(values):
    v = np.asarray(values, float)
    v = v[~np.isnan(v)]
    if not len(v):
        return {'n': 0}
    return {'n': int(len(v)), 'median': float(np.median(v)),
            'q1': float(np.percentile(v, 25)), 'q3': float(np.percentile(v, 75))}


def logit(y, X):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        try:
            r = sm.Logit(y, X).fit(disp=False, maxiter=200)
        except Exception:
            return None
    if not r.mle_retvals.get('converged', False) or not np.all(np.isfinite(r.params.to_numpy(float))):
        return None
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description='Post hoc clinically adjusted comparison.')
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
    fields = ['operation_centre', 'surgery_date', 'first_postoperative_treatment_date', 'nerve_sparing_state',
              'pT_ordinal', 'isup_final', 'bmi', 'prostate_volume_cc', 'asa_class', 'surgeon_case_sequence',
              'continence_baseline_text_state', 'epic_cp_urinary_incontinence_preop', 'prior_turp', 'has_diabetes']
    wide = pd.read_csv(d.RELEASE / 'tables/patient_wide.csv', dtype=str, keep_default_na=False, usecols=[ID] + fields)
    wide = wide.set_index(wide[ID].astype(str))
    id_set = set(wide.index)

    frame = res['patients']
    f = frame.loc[frame['_year_status'].notna() & frame['_burden'].astype(str).isin(['one', 'two_or_more'])]
    f = f.reset_index(drop=True)
    pid = f[ID].astype(str)
    if not pid.isin(id_set).all():
        fail('UNMATCHED_PATIENTS')
    w = wide.loc[pid.to_numpy()].reset_index(drop=True)

    y = f['_year_status'].eq(1).astype(float).to_numpy()
    two = f['_burden'].astype(str).eq('two_or_more').to_numpy()

    def num(col):
        return pd.to_numeric(w[col].str.strip().replace('', np.nan), errors='coerce').to_numpy(float)

    surgery = pd.to_datetime(w['surgery_date'].str.strip(), errors='coerce')
    if surgery.isna().any():
        fail('SURGERY_DATE')
    treat = pd.to_datetime(w['first_postoperative_treatment_date'].str.strip(), errors='coerce')
    t_off = (treat - surgery).dt.days.to_numpy(float)
    early = pd.to_numeric(f['_early_day'], errors='coerce').to_numpy(float)
    year = pd.to_numeric(f['_year_day'], errors='coerce').to_numpy(float)
    with np.errstate(invalid='ignore'):
        interim = ~np.isnan(t_off) & (t_off > early) & (t_off <= year)
    observed_gates = {
        'n_compared': int(len(f)),
        'events': int(y.sum()),
        'two_n': int(two.sum()),
        'two_events': int(y[two].sum()),
        'interim_treatment_one': int(interim[~two].sum()),
        'interim_treatment_two_or_more': int(interim[two].sum()),
    }
    try:
        cohort_mod.check_or_record_gates(
            '15_clinical_adjustment', cohort_name, observed_gates, record=args.record_gates)
    except cohort_mod.GateError as exc:
        fail(exc.code, exc.detail)

    centre = w['operation_centre'].astype(str).to_numpy()
    if set(centre) - CENTRES:
        fail('CENTRE_VALUES')
    us = f['_country'].eq('United States').to_numpy()
    if not np.array_equal(us, centre == BRIGHAM):
        fail('CENTRE_COUNTRY_MISMATCH')
    ns = w['nerve_sparing_state'].astype(str).str.strip().to_numpy()
    if set(ns) - NERVE_SPARING:
        fail('NERVE_SPARING_VALUES')
    pt, isup, bmi, vol = num('pT_ordinal'), num('isup_final'), num('bmi'), num('prostate_volume_cc')
    asa, seq = num('asa_class'), num('surgeon_case_sequence')
    age = pd.to_numeric(f['_age'], errors='coerce').to_numpy(float)
    if np.isnan(age).any() or np.isnan(early).any() or np.isnan(pt).any():
        fail('COMPLETE_FIELDS')

    def flag(cond, source):
        return np.where(np.isnan(source), np.nan, cond.astype(float))

    X = pd.DataFrame({
        'two_or_more': two.astype(float),
        'age_per10_cent65': (age - 65.0) / 10.0,
        'early_day_per30_cent90': (early - 90.0) / 30.0,
        'centre_belchatow': (centre == 'Bełchatów').astype(float),
        'centre_salve': (centre == 'Salve Medica').astype(float),
        'period_recent': (surgery.dt.year.to_numpy() >= cohort_mod.recent_period_start_year(cohort_name)).astype(float),
        'nerve_sparing_not_performed': (ns == 'not_performed').astype(float),
        'nerve_sparing_not_stated': np.isin(ns, ['not_assessed', 'unknown_after_review']).astype(float),
        'pt3_or_higher': flag(np.nan_to_num(pt) >= 2, pt),
        'isup_3_or_higher': flag(np.nan_to_num(isup) >= 3, isup),
        'bmi_per5_cent28': (bmi - 28.0) / 5.0,
        'volume_per10_cent40': (vol - 40.0) / 10.0,
        'asa_3_or_4': flag(np.nan_to_num(asa) >= 3, asa),
        'surgeon_sequence_log2_cent32': np.log2(seq) - 5.0,
    })

    def crude(mask):
        rows = [(('two_or_more' if t else 'one'), int(s)) for t, s in zip(two[mask], y[mask])]
        boot = E.proportion_difference(rows, 'one', 'two_or_more', method=E.METHOD_BOOTSTRAP,
                                       confidence=0.95, resamples=DRAWS, seed=REFERENCE_SEED)
        newc = E.proportion_difference(rows, 'one', 'two_or_more', method=E.METHOD_NEWCOMBE, confidence=0.95)
        return {'n': int(mask.sum()), 'one_events': int(y[mask & ~two].sum()), 'one_n': int((mask & ~two).sum()),
                'two_events': int(y[mask & two].sum()), 'two_n': int((mask & two).sum()),
                'difference': boot['estimate'], 'bootstrap_lower': boot['lower'], 'bootstrap_upper': boot['upper'],
                'newcombe_lower': newc['lower'], 'newcombe_upper': newc['upper']}

    def gcomp(mask, cols, seed):
        Xm = X.loc[mask, cols].reset_index(drop=True)
        Xm.insert(0, 'intercept', 1.0)
        ym = y[mask]
        bi = list(Xm.columns).index('two_or_more')

        def standardize(A, coef):
            A = A.to_numpy(float)
            lin = A @ coef - A[:, bi] * coef[bi]
            return float(np.mean(1 / (1 + np.exp(-lin)))), float(np.mean(1 / (1 + np.exp(-(lin + coef[bi])))))

        fit = logit(ym, Xm)
        if fit is None:
            fail('MODEL_NONCONVERGENCE', ','.join(cols))
        s1, s2 = standardize(Xm, fit.params.to_numpy(float))
        rng = np.random.default_rng(seed)
        diffs, failed, large = [], 0, 0
        for _ in range(DRAWS):
            idx = rng.integers(0, len(Xm), len(Xm))
            Xb = Xm.iloc[idx].reset_index(drop=True)
            fb = logit(ym[idx], Xb)
            if fb is None:
                failed += 1
                continue
            coef = fb.params.to_numpy(float)
            large += int(np.abs(coef).max() > 10)
            b1, b2 = standardize(Xb, coef)
            diffs.append(b1 - b2)
        ci = fit.conf_int()
        k = len(Xm.columns) - 1
        return {'covariates': list(Xm.columns), 'n': int(len(Xm)), 'events': int(ym.sum()),
                'non_events': int(len(ym) - ym.sum()), 'parameters_excluding_intercept': k,
                'events_per_parameter': float(min(ym.sum(), len(ym) - ym.sum()) / k),
                'params': {c: {'coef': float(fit.params[c]), 'or': float(np.exp(fit.params[c])),
                               'wald_ci_or': [float(np.exp(v)) for v in ci.loc[c]]} for c in Xm.columns},
                'standardized_one_pad': s1, 'standardized_two_or_more': s2, 'standardized_difference': s1 - s2,
                'bootstrap': {'seed': seed, 'draws': DRAWS, 'failed_fits': failed,
                              'draws_with_coefficient_above_10': large,
                              'lower': float(np.percentile(diffs, 2.5)), 'upper': float(np.percentile(diffs, 97.5))}}

    def ipw(mask, cols, seed):
        Z = X.loc[mask, [c for c in cols if c != 'two_or_more']].reset_index(drop=True)
        Z.insert(0, 'intercept', 1.0)
        t = two[mask].astype(float)
        ym = y[mask]

        def estimate(Zm, tm, yv):
            r = logit(tm, Zm)
            if r is None:
                return None
            ps = np.asarray(r.predict(Zm), float)
            wt = np.where(tm == 1, 1 / ps, 1 / (1 - ps))
            p1 = float(np.sum(wt * (1 - tm) * yv) / np.sum(wt * (1 - tm)))
            p2 = float(np.sum(wt * tm * yv) / np.sum(wt * tm))
            return p1, p2, ps, wt

        est = estimate(Z, t, ym)
        if est is None:
            fail('PROPENSITY_NONCONVERGENCE')
        p1, p2, ps, wt = est
        balance = {}
        for c in Z.columns[1:]:
            x = Z[c].to_numpy(float)
            a, b = x[t == 0], x[t == 1]
            sd = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
            wa, wb = wt[t == 0], wt[t == 1]
            balance[c] = {'smd_unweighted': float((b.mean() - a.mean()) / sd) if sd > 0 else 0.0,
                          'smd_weighted': float((np.sum(wb * b) / wb.sum() - np.sum(wa * a) / wa.sum()) / sd) if sd > 0 else 0.0}

        def ess(v):
            return float(v.sum() ** 2 / np.sum(v ** 2))

        rng = np.random.default_rng(seed)
        diffs, failed = [], 0
        for _ in range(DRAWS):
            idx = rng.integers(0, len(Z), len(Z))
            eb = estimate(Z.iloc[idx].reset_index(drop=True), t[idx], ym[idx])
            if eb is None:
                failed += 1
                continue
            diffs.append(eb[0] - eb[1])
        return {'covariates': list(Z.columns), 'n': int(len(Z)), 'weighted_one_pad': p1, 'weighted_two_or_more': p2,
                'weighted_difference': p1 - p2,
                'propensity': {'one': med_iqr(ps[t == 0]) | {'min': float(ps[t == 0].min()), 'max': float(ps[t == 0].max())},
                               'two_or_more': med_iqr(ps[t == 1]) | {'min': float(ps[t == 1].min()), 'max': float(ps[t == 1].max())}},
                'max_weight': float(wt.max()),
                'effective_sample_size': {'one': ess(wt[t == 0]), 'two_or_more': ess(wt[t == 1])},
                'balance': balance,
                'max_abs_smd_unweighted': float(max(abs(v['smd_unweighted']) for v in balance.values())),
                'max_abs_smd_weighted': float(max(abs(v['smd_weighted']) for v in balance.values())),
                'bootstrap': {'seed': seed, 'draws': DRAWS, 'failed_fits': failed,
                              'lower': float(np.percentile(diffs, 2.5)), 'upper': float(np.percentile(diffs, 97.5))}}

    complete = X[CLINICAL].notna().all(axis=1).to_numpy()
    no_interim = complete & ~interim
    us_complete = us & X[UNITED_STATES].notna().all(axis=1).to_numpy()

    def by_group(values, kind):
        out = {}
        for key, m in (('one', ~two), ('two_or_more', two)):
            v = values[m]
            if kind == 'numeric':
                out[key] = med_iqr(v) | {'missing': int(np.isnan(np.asarray(v, float)).sum())}
            else:
                out[key] = {str(k): int(c) for k, c in pd.Series(v).astype(str).value_counts().sort_index().items()}
        return out

    pt_label = np.where(np.isnan(pt), 'missing', np.where(pt >= 2, 'pT3-4', 'pT2'))
    isup_label = np.where(np.isnan(isup), 'missing', np.where(isup >= 3, '3-5', '1-2'))
    record = {
        'analysis_id': 'M1-CLINICAL-ADJUSTMENT', 'amendment': 'A-OBS-4', 'status': 'exploratory_post_hoc_disclosed',
        'draws': DRAWS, 'reference_seed': REFERENCE_SEED, 'seeds': SEEDS,
        'n_compared': int(len(f)), 'events': int(y.sum()),
        'covariate_sets': {'clinical': CLINICAL, 'united_states': UNITED_STATES},
        'by_group_201' if is_all_ops else 'by_group': {
            'pathological_stage': by_group(pt_label, 'category'),
            'final_isup_grade_group': by_group(isup_label, 'category'),
            'nerve_sparing_state': by_group(ns, 'category'),
            'bmi': by_group(bmi, 'numeric'),
            'prostate_volume_cc': by_group(vol, 'numeric'),
            'prostate_volume_recorded_by_country': {
                'Poland': int((~us & ~np.isnan(vol)).sum()), 'United States': int((us & ~np.isnan(vol)).sum())},
            'interim_treatment': {'one': int(interim[~two].sum()), 'two_or_more': int(interim[two].sum())},
        },
        'fields_not_available_for_adjustment': {
            'continence_baseline_text_state': {str(k): int(v) for k, v in w['continence_baseline_text_state'].replace('', 'blank').value_counts().sort_index().items()},
            'epic_preoperative_incontinence_score_recorded': int((num('epic_cp_urinary_incontinence_preop') >= 0).sum()),
            'prior_turp_recorded': int(w['prior_turp'].str.strip().ne('').sum()),
            'has_diabetes_recorded': int(w['has_diabetes'].str.strip().ne('').sum()),
            'pelvic_floor_training_medication_or_continence_surgery_fields': 0,
        },
        'clinical': {'crude_same_men': crude(complete), 'model': gcomp(complete, CLINICAL, SEEDS['clinical'])},
        'clinical_no_interim_treatment': {'crude_same_men': crude(no_interim),
                                          'model': gcomp(no_interim, CLINICAL, SEEDS['clinical_no_interim_treatment'])},
        'ipw_clinical': ipw(complete, CLINICAL, SEEDS['ipw']),
        'united_states': {'crude_same_men': crude(us_complete),
                          'model': gcomp(us_complete, UNITED_STATES, SEEDS['united_states'])},
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if not is_all_ops:
        record['cohort'] = res['cohort']
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
    for p in id_set:
        if p and len(p) > 3 and p in text:
            fail('IDENTIFIER_LEAK')
    max_float_diff = 0.0
    if verify:
        if not out_path.is_file():
            fail('SAVED_RECORD_MISMATCH', 'missing_output')
        saved = out_path.read_text()
        if is_all_ops:
            ok, reason, max_float_diff = cohort_mod.compare_records_ignoring_provenance(
                json.loads(saved), json.loads(text), ignore_keys=('code_sha256',), float_tol=1e-12)
            if not ok:
                fail('SAVED_RECORD_MISMATCH', reason)
        elif json.loads(saved) != json.loads(text):
            fail('SAVED_RECORD_MISMATCH')
        print(json.dumps({'status': 'saved_clinical_adjustment_recomputed_exactly', 'cohort': cohort_name,
                          'max_float_diff': max_float_diff}))
        return 0
    out_path.write_text(text)
    print(json.dumps({'status': 'written', 'cohort': cohort_name, 'path': str(out_path)}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
