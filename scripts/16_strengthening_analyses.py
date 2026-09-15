"""Post hoc analyses that test the main comparison from further directions (amendment A-OBS-5).

Added on 15 September 2026, after the main result was known. Every analysis is exploratory
and aggregate-only:

1. Risk ratio for the reference comparison, with Katz and whole-patient bootstrap intervals,
   and E-values for the crude and clinically standardized risk ratios.
2. Pad-count gradient: one-year pad freedom among men pad-free at three months (stored
   transition record) and among pad users with exactly one, exactly two, and three or more
   pads, plus two-or-more users whose records do not separate two from three or more.
   Cochran-Armitage trend tests, with the unseparated men assigned either way, and a
   logistic odds ratio per pad level.
3. Country heterogeneity of the absolute difference (Wald test, whole-patient bootstrap of
   the difference between country differences, logistic interaction) and estimates leaving
   out one centre at a time.
4. Bounds for the 25 men whose three-month count could not be classified.
5. Prognostic value among the 183 men of the clinical model: likelihood-ratio test,
   apparent and optimism-corrected c statistics, optimism-corrected calibration slope, and
   classification of persistent pad use by the two-or-more group.
6. Missing one-year records among the one-pad and two-or-more users whose one-year window
   had closed: inverse probability of record-availability weighting, six-month and two-year
   status of men with and without a one-year record, and the equal and opposite shift at
   which the lower 95% confidence limit of the completed difference reaches zero.
7. Agreement of the pad record with EPIC-CP urinary incontinence scores.
8. Outcome definitions: a one-year window extended to day 545, social continence (no pads
   or at most one pad per day) and safety pads or diapers among men using pads at one year.
9. The clinical model refitted with Firth-penalized likelihood.

No identifier, date or narrative is emitted, and the record is scanned against the identity
set before it is saved.

Run from manuscript1/:
  PY=/home/konrad/.venvs/konsta-research-py314/bin/python
  "$PY" -B scripts/16_strengthening_analyses.py            # build
  "$PY" -B scripts/16_strengthening_analyses.py --verify   # recompute, no write
"""

import hashlib
import importlib.util
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / 'evidence/STRENGTHENING_ANALYSES.json'
DRAWS = 2000
REFERENCE_SEED = 20260907
CLINICAL_SEED = 20260926
PROGNOSTIC_SEED = 20260930
AVAILABILITY_SEED = 20260931
FIRTH_SEED = 20260932
TIPPING_SEED = 20260933
COMMON_EXTRACT = pd.Timestamp('2026-04-01')
YEAR_WINDOW_CLOSE = 425
WIDE_YEAR_WINDOW = (305, 545, 365)
BRIGHAM = "Brigham and Women's Hospital"
Z = stats.norm.ppf(0.975)
CLINICAL = ['two_or_more', 'age_per10_cent65', 'early_day_per30_cent90', 'centre_belchatow', 'centre_salve',
            'period_recent', 'nerve_sparing_not_performed', 'nerve_sparing_not_stated', 'pt3_or_higher',
            'isup_3_or_higher', 'bmi_per5_cent28']
AVAILABILITY = ['two_or_more', 'age_per10_cent65', 'early_day_per30_cent90', 'centre_belchatow', 'centre_salve',
                'period_recent', 'nerve_sparing_not_performed', 'nerve_sparing_not_stated', 'pt3_or_higher']


def fail(code, detail=''):
    print(f'STRENGTHENING_FAILED {code} {detail}'.strip(), file=sys.stderr)
    sys.exit(1)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def firth_fit(y, X, maxiter=200, tol=1e-8):
    """Firth-penalized logistic regression by modified-score Newton steps with step halving."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    beta = np.zeros(X.shape[1])

    def penalized(b):
        eta = X @ b
        p = 1 / (1 + np.exp(-eta))
        w = p * (1 - p)
        info = X.T @ (X * w[:, None])
        sign, logdet = np.linalg.slogdet(info)
        if sign <= 0:
            return -np.inf, p, w, info
        return float(np.sum(y * eta - np.logaddexp(0, eta)) + 0.5 * logdet), p, w, info

    ll, p, w, info = penalized(beta)
    if not np.isfinite(ll):
        return None
    for _ in range(maxiter):
        try:
            inv = np.linalg.inv(info)
        except np.linalg.LinAlgError:
            return None
        h = w * np.einsum('ij,jk,ik->i', X, inv, X)
        step = inv @ (X.T @ (y - p + h * (0.5 - p)))
        largest = np.max(np.abs(step))
        if largest > 5:
            step = step * (5 / largest)
        t = 1.0
        while True:
            nb = beta + t * step
            nll, np_, nw, ninfo = penalized(nb)
            if (np.isfinite(nll) and nll >= ll - 1e-10) or t < 1e-4:
                break
            t /= 2
        if not np.isfinite(nll):
            return None
        done = np.max(np.abs(nb - beta)) < tol
        beta, ll, p, w, info = nb, nll, np_, nw, ninfo
        if done:
            return beta
    return None


def evalue(rr):
    rr = rr if rr >= 1 else 1 / rr
    return float(rr + math.sqrt(rr * (rr - 1)))


def auc(y, score):
    y = np.asarray(y, float)
    ranks = stats.rankdata(np.asarray(score, float))
    n1 = y.sum()
    n0 = len(y) - n1
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def med_iqr(v):
    v = np.asarray(v, float)
    v = v[~np.isnan(v)]
    if not len(v):
        return {'n': 0}
    return {'n': int(len(v)), 'median': float(np.median(v)), 'q1': float(np.percentile(v, 25)),
            'q3': float(np.percentile(v, 75))}


def main(argv):
    verify = '--verify' in argv
    d = load('drv06', '06_derive_observed_assessments.py')
    E = load('est05', '05_observed_estimators.py')
    res = d.source_derive()
    if res['source_verification']['bound_inputs_before'] != 122:
        fail('BOUND_INPUT_COUNT')
    ID = d.ID
    selection, candidate = res['selection'], res['candidate']
    fields = ['operation_centre', 'surgery_date', 'pad_count_instrument_src', 'nerve_sparing_state', 'pT_ordinal',
              'isup_final', 'bmi', 'epic_cp_urinary_incontinence_preop', 'epic_cp_urinary_incontinence_3m',
              'epic_cp_urinary_incontinence_12m']
    wide = pd.read_csv(d.RELEASE / 'tables/patient_wide.csv', dtype=str, keep_default_na=False, usecols=[ID] + fields)
    wide = wide.set_index(wide[ID].astype(str))
    id_set = set(wide.index)
    clinical_record = json.loads((HERE / 'evidence/CLINICAL_ADJUSTMENT.json').read_text())

    f = res['patients'].copy().reset_index(drop=True)
    if len(f) != 460:
        fail('EARLY_USERS', str(len(f)))
    pid = f[ID].astype(str)
    if not pid.isin(id_set).all():
        fail('UNMATCHED_PATIENTS')
    w = wide.loc[pid.to_numpy()].reset_index(drop=True)
    burden = f['_burden'].astype(str).to_numpy()
    has_year = f['_year_status'].notna().to_numpy()
    y_all = f['_year_status'].eq(1).fillna(False).to_numpy(bool)
    one, two = burden == 'one', burden == 'two_or_more'
    pair = has_year & (one | two)
    if int(pair.sum()) != 201 or int(y_all[pair & one].sum()) != 58 or int((pair & one).sum()) != 110 \
            or int(y_all[pair & two].sum()) != 24 or int((pair & two).sum()) != 91:
        fail('REFERENCE_COUNTS')

    def num(col):
        return pd.to_numeric(w[col].str.strip().replace('', np.nan), errors='coerce').to_numpy(float)

    def contrast(mask, outcome=None):
        yv = y_all if outcome is None else outcome
        rows = [('two_or_more' if t else 'one', int(s)) for t, s in zip(two[mask], yv[mask])]
        boot = E.proportion_difference(rows, 'one', 'two_or_more', method=E.METHOD_BOOTSTRAP, confidence=0.95,
                                       resamples=DRAWS, seed=REFERENCE_SEED)
        newc = E.proportion_difference(rows, 'one', 'two_or_more', method=E.METHOD_NEWCOMBE, confidence=0.95)
        return {'n': int(mask.sum()), 'one_events': int(yv[mask & one].sum()), 'one_n': int((mask & one).sum()),
                'two_events': int(yv[mask & two].sum()), 'two_n': int((mask & two).sum()),
                'difference': boot['estimate'], 'bootstrap_lower': boot['lower'], 'bootstrap_upper': boot['upper'],
                'newcombe_lower': newc['lower'], 'newcombe_upper': newc['upper']}

    surgery = pd.to_datetime(w['surgery_date'].str.strip(), errors='coerce')
    if surgery.isna().any():
        fail('SURGERY_DATE')
    closed = ((surgery + pd.Timedelta(days=YEAR_WINDOW_CLOSE)) < COMMON_EXTRACT).to_numpy()
    centre = w['operation_centre'].astype(str).to_numpy()
    us = f['_country'].eq('United States').to_numpy()
    ns = w['nerve_sparing_state'].astype(str).str.strip().to_numpy()
    pt, isup, bmi = num('pT_ordinal'), num('isup_final'), num('bmi')
    age = pd.to_numeric(f['_age'], errors='coerce').to_numpy(float)
    early = pd.to_numeric(f['_early_day'], errors='coerce').to_numpy(float)

    def flag(cond, source):
        return np.where(np.isnan(source), np.nan, cond.astype(float))

    X = pd.DataFrame({
        'two_or_more': two.astype(float),
        'age_per10_cent65': (age - 65.0) / 10.0,
        'early_day_per30_cent90': (early - 90.0) / 30.0,
        'centre_belchatow': (centre == 'Bełchatów').astype(float),
        'centre_salve': (centre == 'Salve Medica').astype(float),
        'period_recent': (surgery.dt.year.to_numpy() >= 2025).astype(float),
        'nerve_sparing_not_performed': (ns == 'not_performed').astype(float),
        'nerve_sparing_not_stated': (~np.isin(ns, ['performed', 'not_performed'])).astype(float),
        'pt3_or_higher': flag(np.nan_to_num(pt) >= 2, pt),
        'isup_3_or_higher': flag(np.nan_to_num(isup) >= 3, isup),
        'bmi_per5_cent28': (bmi - 28.0) / 5.0,
    })

    # 1. Risk ratio and E-value.
    x1, n1, x2, n2 = 58, 110, 24, 91
    rr = (x1 / n1) / (x2 / n2)
    se = math.sqrt(1 / x1 - 1 / n1 + 1 / x2 - 1 / n2)
    rng = np.random.default_rng(REFERENCE_SEED)
    yp, tp = y_all[pair].astype(float), two[pair]
    rrs = []
    for _ in range(DRAWS):
        idx = rng.integers(0, len(yp), len(yp))
        a, b = yp[idx][~tp[idx]], yp[idx][tp[idx]]
        if len(a) and len(b) and b.sum() > 0:
            rrs.append(a.mean() / b.mean())
    katz_lower = math.exp(math.log(rr) - Z * se)
    risk_ratio = {'estimate': rr, 'katz_lower': katz_lower, 'katz_upper': math.exp(math.log(rr) + Z * se),
                  'bootstrap_lower': float(np.percentile(rrs, 2.5)), 'bootstrap_upper': float(np.percentile(rrs, 97.5)),
                  'bootstrap_valid': len(rrs), 'seed': REFERENCE_SEED,
                  'e_value': evalue(rr), 'e_value_katz_lower_limit': evalue(katz_lower),
                  'persistent_pad_use_two_or_more': {'n': n2 - x2, 'of': n2}, 'persistent_pad_use_one': {'n': n1 - x1, 'of': n1},
                  'classification_of_persistent_pad_use_by_two_or_more': {
                      'sensitivity': (n2 - x2) / ((n2 - x2) + (n1 - x1)), 'specificity': x1 / (x1 + x2),
                      'positive_predictive_value': (n2 - x2) / n2, 'negative_predictive_value': x1 / n1}}

    # 2. Pad-count gradient from the rows used for the three-month classification.
    chosen = selection['selected']['early']
    keys = set(zip(chosen[ID], chosen._date))
    member = pd.Series([(p, when) in keys for p, when in zip(candidate[ID], candidate._date)], index=candidate.index)
    day_rows = candidate.loc[member].copy()
    mapped = day_rows[ID].map(dict(zip(chosen[ID], chosen._status))).astype('Int64')
    usable = day_rows.loc[day_rows._status.eq(mapped).fillna(False).astype(bool)]
    grouped = {p: g for p, g in usable.groupby(ID, sort=False)}

    def level(p, b):
        if b != 'two_or_more':
            return b
        g = grouped[p]
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

    levels = np.array([level(p, b) for p, b in zip(f[ID], burden)])
    transitions = json.loads((HERE / 'evidence/OBSERVED_STATUS_ESTIMATES.json').read_text())['policies']['P0'][
        'all_paired_transitions_year']['cell_counts']
    pad_free_early = {'n': int(transitions['early_pad_free|later_pad_free'] + transitions['early_pad_free|later_pad_use']),
                      'events': int(transitions['early_pad_free|later_pad_free'])}
    gradient = {'pad_free_at_three_months': pad_free_early}
    for lv in ('one', 'two', 'three_or_more', 'two_or_more_unseparated'):
        m = levels == lv
        gradient[lv] = {'early_users': int(m.sum()), 'n': int((m & has_year).sum()), 'events': int((m & has_year & y_all).sum())}
    if gradient['one']['n'] != 110 or sum(gradient[k]['n'] for k in ('two', 'three_or_more', 'two_or_more_unseparated')) != 91:
        fail('GRADIENT_CALIBRATION')

    def armitage(cells, scores):
        n = np.array([c['n'] for c in cells], float)
        x = np.array([c['events'] for c in cells], float)
        s = np.array(scores, float)
        p = x.sum() / n.sum()
        t = np.sum(s * (x - n * p))
        var = p * (1 - p) * (np.sum(n * s ** 2) - np.sum(n * s) ** 2 / n.sum())
        zval = t / math.sqrt(var)
        return {'z': float(zval), 'p_two_sided': float(2 * stats.norm.sf(abs(zval)))}

    exact_cells = [gradient['one'], gradient['two'], gradient['three_or_more']]
    gradient['trend_pad_users_exact'] = armitage(exact_cells, [1, 2, 3])
    gradient['trend_including_pad_free_at_three_months'] = armitage([pad_free_early] + exact_cells, [0, 1, 2, 3])
    for key, target in (('unseparated_as_two', 'two'), ('unseparated_as_three_or_more', 'three_or_more')):
        cells = {k: dict(gradient[k]) for k in ('one', 'two', 'three_or_more')}
        cells[target] = {'n': cells[target]['n'] + gradient['two_or_more_unseparated']['n'],
                         'events': cells[target]['events'] + gradient['two_or_more_unseparated']['events']}
        gradient['trend_' + key] = armitage([cells['one'], cells['two'], cells['three_or_more']], [1, 2, 3])
    m = has_year & np.isin(levels, ['one', 'two', 'three_or_more'])
    score = np.select([levels == 'one', levels == 'two', levels == 'three_or_more'], [1.0, 2.0, 3.0], 0.0)
    fg = logit(y_all[m].astype(float), pd.DataFrame({'intercept': 1.0, 'pad_level': score[m]}))
    if fg is None:
        fail('GRADIENT_MODEL')
    gradient['odds_ratio_per_pad_level'] = {'or': float(np.exp(fg.params['pad_level'])),
                                            'wald_ci': [float(np.exp(v)) for v in fg.conf_int().loc['pad_level']],
                                            'n': int(m.sum())}

    # 3. Country heterogeneity among the 201, and leaving out one centre at a time.
    def country_diff(yv, tv, uv):
        out = {}
        for key, c in (('poland', ~uv), ('united_states', uv)):
            a, b = yv[c & ~tv], yv[c & tv]
            if not len(a) or not len(b):
                return None
            out[key] = (a.mean(), len(a), b.mean(), len(b))
        return out

    up = us[pair]
    cd = country_diff(yp, tp, up)
    var = {k: v[0] * (1 - v[0]) / v[1] + v[2] * (1 - v[2]) / v[3] for k, v in cd.items()}
    dd_est = (cd['poland'][0] - cd['poland'][2]) - (cd['united_states'][0] - cd['united_states'][2])
    zval = dd_est / math.sqrt(var['poland'] + var['united_states'])
    rng = np.random.default_rng(REFERENCE_SEED)
    dds = []
    for _ in range(DRAWS):
        idx = rng.integers(0, len(yp), len(yp))
        c = country_diff(yp[idx], tp[idx], up[idx])
        if c is not None:
            dds.append((c['poland'][0] - c['poland'][2]) - (c['united_states'][0] - c['united_states'][2]))
    Xh0 = pd.DataFrame({'intercept': 1.0, 'two_or_more': tp.astype(float), 'us': up.astype(float)})
    Xh1 = Xh0.assign(interaction=(tp & up).astype(float))
    h0, h1 = logit(yp, Xh0), logit(yp, Xh1)
    lr = 2 * (h1.llf - h0.llf)
    heterogeneity = {'difference_poland_minus_united_states': float(dd_est), 'wald_z': float(zval),
                     'wald_p': float(2 * stats.norm.sf(abs(zval))),
                     'bootstrap_lower': float(np.percentile(dds, 2.5)), 'bootstrap_upper': float(np.percentile(dds, 97.5)),
                     'bootstrap_valid': len(dds), 'seed': REFERENCE_SEED,
                     'logistic_interaction_or': float(np.exp(h1.params['interaction'])),
                     'logistic_interaction_lr_chi2': float(lr), 'logistic_interaction_p': float(stats.chi2.sf(lr, 1)),
                     'leave_one_centre_out': {key: contrast(pair & (centre != name)) for key, name in
                                              (('without_belchatow', 'Bełchatów'), ('without_salve_medica', 'Salve Medica'),
                                               ('without_brigham', BRIGHAM))}}

    # 4. Bounds for unclassifiable counts.
    unclass = has_year & np.isin(burden, ['nonconflicting_quantity_uncertain', 'unresolved_quantity_evidence'])
    if int(unclass.sum()) != 25:
        fail('UNCLASSIFIED_COUNT', str(int(unclass.sum())))
    bounds = {'unclassified_n': int(unclass.sum()), 'unclassified_pad_free': int(y_all[unclass].sum())}
    for key, target in (('all_assigned_one', 'one'), ('all_assigned_two_or_more', 'two_or_more')):
        rows = [('one' if (b == 'one' or (u and target == 'one')) else 'two_or_more', int(s))
                for b, u, s, keep in zip(burden, unclass, y_all, pair | unclass) if keep]
        newc = E.proportion_difference(rows, 'one', 'two_or_more', method=E.METHOD_NEWCOMBE, confidence=0.95)
        boot = E.proportion_difference(rows, 'one', 'two_or_more', method=E.METHOD_BOOTSTRAP, confidence=0.95,
                                       resamples=DRAWS, seed=REFERENCE_SEED)
        bounds[key] = {'difference': newc['estimate'], 'newcombe_lower': newc['lower'], 'newcombe_upper': newc['upper'],
                       'bootstrap_lower': boot['lower'], 'bootstrap_upper': boot['upper'], 'n': len(rows),
                       'one_events': sum(s for g, s in rows if g == 'one'), 'one_n': sum(1 for g, _ in rows if g == 'one'),
                       'two_events': sum(s for g, s in rows if g == 'two_or_more'),
                       'two_n': sum(1 for g, _ in rows if g == 'two_or_more')}

    # 5. Prognostic value among the complete cases of the clinical model.
    cc = pair & X[CLINICAL].notna().all(axis=1).to_numpy()
    if int(cc.sum()) != 183:
        fail('CLINICAL_COMPLETE_CASES', str(int(cc.sum())))
    yc = y_all[cc].astype(float)
    X1 = X.loc[cc, CLINICAL].reset_index(drop=True)
    X1.insert(0, 'intercept', 1.0)
    X0 = X1.drop(columns=['two_or_more'])
    f1, f0 = logit(yc, X1), logit(yc, X0)

    def lin(fit, A):
        return A.to_numpy(float) @ fit.params.to_numpy(float)

    app1, app0 = auc(yc, lin(f1, X1)), auc(yc, lin(f0, X0))
    rng = np.random.default_rng(PROGNOSTIC_SEED)
    opt1, opt0, gains, slopes, failed = [], [], [], [], 0
    for _ in range(DRAWS):
        idx = rng.integers(0, len(yc), len(yc))
        b1, b0 = X1.iloc[idx].reset_index(drop=True), X0.iloc[idx].reset_index(drop=True)
        g1, g0 = logit(yc[idx], b1), logit(yc[idx], b0)
        if g1 is None or g0 is None or len(np.unique(yc[idx])) < 2:
            failed += 1
            continue
        boot1, boot0 = auc(yc[idx], lin(g1, b1)), auc(yc[idx], lin(g0, b0))
        test1 = lin(g1, X1)
        opt1.append(boot1 - auc(yc, test1))
        opt0.append(boot0 - auc(yc, lin(g0, X0)))
        gains.append(boot1 - boot0)
        cal = logit(yc, pd.DataFrame({'intercept': 1.0, 'lp': test1}))
        if cal is not None:
            slopes.append(float(cal.params['lp']))
    lr_pad = 2 * (f1.llf - f0.llf)
    prognostic = {'n': int(cc.sum()), 'events': int(yc.sum()),
                  'lr_chi2_adding_pad_group': float(lr_pad), 'lr_p': float(stats.chi2.sf(lr_pad, 1)),
                  'c_apparent_without_pad_group': app0, 'c_apparent_with_pad_group': app1,
                  'c_corrected_without_pad_group': app0 - float(np.mean(opt0)),
                  'c_corrected_with_pad_group': app1 - float(np.mean(opt1)),
                  'c_pad_group_alone': auc(yc, X1['two_or_more'].to_numpy() * -1.0),
                  'gain_bootstrap_lower': float(np.percentile(gains, 2.5)), 'gain_bootstrap_upper': float(np.percentile(gains, 97.5)),
                  'calibration_slope_optimism_corrected': float(np.mean(slopes)), 'calibration_slope_draws': len(slopes),
                  'seed': PROGNOSTIC_SEED, 'draws': DRAWS, 'failed_draws': failed}

    # 6. Missing one-year records among closed-window one-pad and two-or-more users.
    cw = closed & (one | two)
    if int((cw & one).sum()) != 189 or int((cw & two).sum()) != 137 or int((cw & one & has_year).sum()) != 104 \
            or int((cw & two & has_year).sum()) != 85:
        fail('CLOSED_WINDOW_CALIBRATION')
    Xa = X.loc[cw, AVAILABILITY].reset_index(drop=True)
    if Xa.isna().any().any():
        fail('AVAILABILITY_COVARIATES_INCOMPLETE')
    Xa.insert(0, 'intercept', 1.0)
    ra = has_year[cw].astype(float)
    ya = y_all[cw].astype(float)
    ta = two[cw].astype(float)

    def weighted(A, r, yv, tv):
        fit = logit(r, A)
        if fit is None:
            return None
        p = 1 / (1 + np.exp(-(A.to_numpy(float) @ fit.params.to_numpy(float))))
        obs = r == 1
        wt = 1 / p[obs]
        yo, to = yv[obs], tv[obs]
        p1 = float(np.sum(wt * yo * (1 - to)) / np.sum(wt * (1 - to)))
        p2 = float(np.sum(wt * yo * to) / np.sum(wt * to))
        return p1, p2, wt, to

    est = weighted(Xa, ra, ya, ta)
    if est is None:
        fail('AVAILABILITY_MODEL')
    rng = np.random.default_rng(AVAILABILITY_SEED)
    diffs, failed = [], 0
    for _ in range(DRAWS):
        idx = rng.integers(0, len(ra), len(ra))
        e = weighted(Xa.iloc[idx].reset_index(drop=True), ra[idx], ya[idx], ta[idx])
        if e is None:
            failed += 1
            continue
        diffs.append(e[0] - e[1])
    wt, to = est[2], est[3]

    def ess(v):
        return float(v.sum() ** 2 / np.sum(v ** 2))

    status = {}
    six_known = f['_six_status'].notna().to_numpy()
    six_free = f['_six_status'].eq(1).fillna(False).to_numpy(bool)
    two_known = f['_two_year_status'].notna().to_numpy()
    two_free = f['_two_year_status'].eq(1).fillna(False).to_numpy(bool)
    for gkey, gm in (('one', one), ('two_or_more', two)):
        for rkey, rm in (('with_year_record', has_year), ('without_year_record', ~has_year)):
            m = cw & gm & rm
            status[f'{gkey}|{rkey}'] = {'n': int(m.sum()),
                                        'six_month_record': int((six_known & m).sum()), 'six_month_pad_free': int((six_free & m).sum()),
                                        'two_year_record': int((two_known & m).sum()), 'two_year_pad_free': int((two_free & m).sum())}

    grid = np.round(np.arange(0, 0.5000001, 0.001), 3)

    def completed(tv, rv, yv):
        out = []
        for g in (0.0, 1.0):
            m = tv == g
            out.append((float(m.sum()), float((m & (rv == 1)).sum()), float((m & (rv == 1) & (yv == 1)).sum())))
        (N1, o1, e1), (N2, o2, e2) = out
        if min(N1, o1, N2, o2) == 0:
            return None
        q1 = np.clip(e1 / o1 - grid, 0, 1)
        q2 = np.clip(e2 / o2 + grid, 0, 1)
        return (e1 + (N1 - o1) * q1) / N1 - (e2 + (N2 - o2) * q2) / N2

    point = completed(ta, ra, ya)
    rng = np.random.default_rng(TIPPING_SEED)
    curves = []
    for _ in range(DRAWS):
        idx = rng.integers(0, len(ra), len(ra))
        c = completed(ta[idx], ra[idx], ya[idx])
        if c is not None:
            curves.append(c)
    lower = np.percentile(np.array(curves), 2.5, axis=0)
    availability = {'n': int(cw.sum()), 'covariates': list(Xa.columns),
                    'weighted_one_pad': est[0], 'weighted_two_or_more': est[1], 'weighted_difference': est[0] - est[1],
                    'bootstrap_lower': float(np.percentile(diffs, 2.5)), 'bootstrap_upper': float(np.percentile(diffs, 97.5)),
                    'failed_fits': failed, 'seed': AVAILABILITY_SEED, 'max_weight': float(wt.max()),
                    'effective_sample_size': {'one': ess(wt[to == 0]), 'two_or_more': ess(wt[to == 1])},
                    'status_by_record_availability': status,
                    'tipping_shift_point_estimate': float(grid[np.argmax(point <= 0)]) if (point <= 0).any() else None,
                    'tipping_shift_lower_confidence_limit': float(grid[np.argmax(lower <= 0)]) if (lower <= 0).any() else None,
                    'completed_difference_lower_limit_at_zero_shift': float(lower[0]),
                    'tipping_grid_step': 0.001, 'tipping_seed': TIPPING_SEED, 'tipping_valid_draws': len(curves)}

    # 7. EPIC-CP urinary incontinence scores (0-12, higher is worse). Men whose pad count came
    # from the EPIC instrument are excluded so that the comparison is not circular.
    not_epic = w['pad_count_instrument_src'].astype(str).str.strip().ne('EPIC').to_numpy()

    def compare(values, a, b):
        va, vb = values[a], values[b]
        va, vb = va[~np.isnan(va)], vb[~np.isnan(vb)]
        out = {'group_a': med_iqr(va), 'group_b': med_iqr(vb)}
        if len(va) >= 5 and len(vb) >= 5:
            out['mann_whitney_p'] = float(stats.mannwhitneyu(va, vb, alternative='two-sided').pvalue)
        return out

    epic = {'three_month_score_one_vs_two_or_more': compare(num('epic_cp_urinary_incontinence_3m'), pair & one & not_epic, pair & two & not_epic),
            'twelve_month_score_pad_free_vs_pad_use': compare(num('epic_cp_urinary_incontinence_12m'), pair & y_all & not_epic, pair & ~y_all & not_epic),
            'preoperative_score_one_vs_two_or_more': compare(num('epic_cp_urinary_incontinence_preop'), pair & one & not_epic, pair & two & not_epic)}

    # 8. Outcome definitions.
    wide_chosen, _ = d.select_window(candidate, WIDE_YEAR_WINDOW, 'nearest')
    wide_status = pd.to_numeric(f[ID].map(dict(zip(wide_chosen[ID], wide_chosen._status))), errors='coerce').to_numpy(float)
    wide_obs = ~np.isnan(wide_status) & (one | two)
    widened = contrast(wide_obs, outcome=(wide_status == 1)) | {'window_days': [WIDE_YEAR_WINDOW[0], WIDE_YEAR_WINDOW[1]],
                                                                'added_men': int(wide_obs.sum()) - 201}

    year_chosen = selection['selected']['year']
    ykeys = set(zip(year_chosen[ID], year_chosen._date))
    ymember = pd.Series([(p, when) in ykeys for p, when in zip(candidate[ID], candidate._date)], index=candidate.index)
    yrows = candidate.loc[ymember].copy()
    ymapped = yrows[ID].map(dict(zip(year_chosen[ID], year_chosen._status))).astype('Int64')
    yrows = yrows.loc[yrows._status.eq(ymapped).fillna(False).astype(bool)]
    yq = d.quantity_columns(yrows)
    yrows = yrows.assign(_hi=yq['upper'], _ok=(yq['informative'] & ~yq['invalid']),
                         _safety=d.eda.truth(yrows.safety_pad_documented),
                         _diaper=(d.eda.numeric(yrows.diaper_count_min).gt(0) | d.eda.numeric(yrows.diaper_count_max).gt(0)))
    ygroups = {p: g for p, g in yrows.groupby(ID, sort=False)}
    social = np.full(len(f), np.nan)
    safety_users = diaper_users = 0
    for i in np.where(pair)[0]:
        g = ygroups.get(f[ID].iloc[i])
        if g is None:
            fail('YEAR_ROWS_MISSING')
        if y_all[i]:
            social[i] = 1.0
            continue
        safety_users += int(g['_safety'].any())
        diaper_users += int(g['_diaper'].any())
        counts = g.loc[g['_ok'] & g['_hi'].notna(), '_hi']
        if len(counts):
            social[i] = float((counts <= 1).all())
    social_known = pair & ~np.isnan(social)
    outcomes = {'widened_one_year_window': widened,
                'social_continence_no_pads_or_at_most_one': contrast(social_known, outcome=(social == 1))
                | {'excluded_pad_users_without_a_valid_count': int((pair & np.isnan(social)).sum())},
                'pad_users_at_one_year': int((pair & ~y_all).sum()),
                'pad_users_at_one_year_with_safety_pad_recorded': safety_users,
                'pad_users_at_one_year_with_diaper_recorded': diaper_users}

    # 9. Clinical model: standardized risk ratio (maximum likelihood, reproducing the stored
    # bootstrap) and Firth-penalized refits.
    bi = list(X1.columns).index('two_or_more')

    def standardize(A, coef):
        A = np.asarray(A, float)
        lp = A @ coef - A[:, bi] * coef[bi]
        return float(np.mean(1 / (1 + np.exp(-lp)))), float(np.mean(1 / (1 + np.exp(-(lp + coef[bi])))))

    s1, s2 = standardize(X1, f1.params.to_numpy(float))
    rng = np.random.default_rng(CLINICAL_SEED)
    ml_diffs, ml_ratios = [], []
    for _ in range(DRAWS):
        idx = rng.integers(0, len(X1), len(X1))
        Xb = X1.iloc[idx].reset_index(drop=True)
        fb = logit(yc[idx], Xb)
        if fb is None:
            continue
        b1, b2 = standardize(Xb, fb.params.to_numpy(float))
        ml_diffs.append(b1 - b2)
        ml_ratios.append(b1 / b2)
    stored = clinical_record['clinical']['model']['bootstrap']
    if abs(np.percentile(ml_diffs, 2.5) - stored['lower']) > 1e-12 or abs(np.percentile(ml_diffs, 97.5) - stored['upper']) > 1e-12:
        fail('CLINICAL_BOOTSTRAP_NOT_REPRODUCED')
    ratio_lower = float(np.percentile(ml_ratios, 2.5))
    fb0 = firth_fit(yc, X1)
    if fb0 is None:
        fail('FIRTH_NONCONVERGENCE')
    fs1, fs2 = standardize(X1, fb0)
    rng = np.random.default_rng(FIRTH_SEED)
    firth_diffs, firth_failed = [], 0
    for _ in range(DRAWS):
        idx = rng.integers(0, len(X1), len(X1))
        Xb = X1.iloc[idx].reset_index(drop=True)
        beta = firth_fit(yc[idx], Xb)
        if beta is None:
            firth_failed += 1
            continue
        b1, b2 = standardize(Xb, beta)
        firth_diffs.append(b1 - b2)
    clinical = {'standardized_risk_ratio': s1 / s2, 'standardized_risk_ratio_bootstrap_lower': ratio_lower,
                'standardized_risk_ratio_bootstrap_upper': float(np.percentile(ml_ratios, 97.5)),
                'e_value': evalue(s1 / s2), 'e_value_lower_limit': evalue(ratio_lower), 'seed': CLINICAL_SEED,
                'firth': {'odds_ratio_two_or_more': float(np.exp(fb0[bi])), 'standardized_one_pad': fs1,
                          'standardized_two_or_more': fs2, 'standardized_difference': fs1 - fs2,
                          'bootstrap_lower': float(np.percentile(firth_diffs, 2.5)),
                          'bootstrap_upper': float(np.percentile(firth_diffs, 97.5)),
                          'failed_fits': firth_failed, 'seed': FIRTH_SEED}}

    record = {
        'analysis_id': 'M1-STRENGTHENING', 'amendment': 'A-OBS-5', 'status': 'exploratory_post_hoc_disclosed',
        'draws': DRAWS, 'risk_ratio': risk_ratio, 'gradient': gradient, 'country_heterogeneity': heterogeneity,
        'unclassified_bounds': bounds, 'prognostic_value': prognostic, 'record_availability': availability,
        'epic_agreement': epic, 'outcome_definitions': outcomes, 'clinical_model_checks': clinical,
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False)
    for p in id_set:
        if p and len(p) > 3 and p in text:
            fail('IDENTIFIER_LEAK')
    if verify:
        if json.loads(EVIDENCE.read_text()) != json.loads(text):
            fail('SAVED_RECORD_MISMATCH')
        print(json.dumps({'status': 'saved_strengthening_record_recomputed_exactly'}))
        return 0
    EVIDENCE.write_text(text)
    print(json.dumps({'status': 'written', 'path': str(EVIDENCE)}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
