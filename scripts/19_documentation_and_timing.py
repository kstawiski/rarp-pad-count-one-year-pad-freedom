#!/usr/bin/env python3
"""Documentation of pad status in the assessment windows, recording of safety pads, timing of the
three-month assessment and extreme allocation of unclassifiable counts (descriptive analysis).

Uses the switchable study cohort (`completed_window` default) and the derivation of script 06.
Aggregate output only. No patient identifier, date or narrative is emitted, and the record is
scanned against the patient identity set and date patterns before saving.

Run from manuscript1/:
  python -B scripts/19_documentation_and_timing.py --cohort completed_window --record-gates
  python -B scripts/19_documentation_and_timing.py --cohort completed_window --verify
"""

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = Path(__file__).resolve().parents[1]
EVIDENCE = HERE / 'evidence/DOCUMENTATION_AND_TIMING.json'
CONFIDENCE = 0.95
DATE_SHAPED = re.compile(r'\d{4}-\d{2}-\d{2}')
CENTRES = ('Bełchatów', 'Salve Medica', "Brigham and Women's Hospital")
DOC_CATEGORIES = ('usable_pad_status', 'pad_status_recorded_not_usable', 'continence_record_without_pad_status',
                  'record_at_other_time_only', 'no_dated_continence_record')


def fail(code, detail=''):
    print(f'DOCUMENTATION_AND_TIMING_FAILED {code} {detail}'.strip(), file=sys.stderr)
    sys.exit(1)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cohort_mod = load('cohort', 'cohort.py')


# Any record after the six-month window and before the two-year window, nearest day 365.
WIDER_YEAR_WINDOW = (211, 669, 365)
HEAVIER_SEED = 20261122
HEAVIER_DRAWS = 2000
HEAVIER_LEVELS = ('one', 'two', 'three_or_more')
HEAVIER_FACTORS = (('half_the_observed_share', 0.5), ('the_observed_share', 1.0), ('twice_the_observed_share', 2.0))


def cell(E, n, N):
    w = E.wilson_interval(int(n), int(N), CONFIDENCE)
    return {'n': int(n), 'N': int(N), 'proportion': w['estimate'], 'lower': w['lower'], 'upper': w['upper']}


def newcombe(E, x1, n1, x2, n2):
    """Difference of two proportions with the Newcombe hybrid score interval (method 10)."""
    a, b = E.wilson_interval(int(x1), int(n1), CONFIDENCE), E.wilson_interval(int(x2), int(n2), CONFIDENCE)
    p1, p2 = a['estimate'], b['estimate']
    diff = p1 - p2
    lower = diff - math.sqrt((p1 - a['lower']) ** 2 + (b['upper'] - p2) ** 2)
    upper = diff + math.sqrt((a['upper'] - p1) ** 2 + (p2 - b['lower']) ** 2)
    return {'group_a': {'n': int(x1), 'N': int(n1)}, 'group_b': {'n': int(x2), 'N': int(n2)},
            'difference': diff, 'newcombe_lower': lower, 'newcombe_upper': upper}


def documentation(d, annotated, candidate_ids, population, usable_ids, window_key, strata):
    """Classify every man of `population` by what the records hold in one assessment window."""
    eda = d.eda
    rows = annotated.loc[annotated[d.ID].isin(population) & annotated.event_phase.eq('postoperative')
                         & annotated['_in_' + window_key].fillna(False)]
    explicit = eda.truth(rows.pad_free) | eda.false(rows.pad_free)
    with_rows = set(rows[d.ID])
    with_explicit = set(rows.loc[explicit, d.ID])
    category = {}
    for pid in population:
        if pid in usable_ids:
            category[pid] = 'usable_pad_status'
        elif pid in with_explicit:
            category[pid] = 'pad_status_recorded_not_usable'
        elif pid in with_rows:
            category[pid] = 'continence_record_without_pad_status'
        elif pid in candidate_ids:
            category[pid] = 'record_at_other_time_only'
        else:
            category[pid] = 'no_dated_continence_record'
    series = pd.Series(category)

    def table(ids):
        sub = series.loc[series.index.isin(ids)]
        out = {'men': int(len(sub))}
        out.update({c: int((sub == c).sum()) for c in DOC_CATEGORIES})
        if sum(out[c] for c in DOC_CATEGORIES) != out['men']:
            fail('DOCUMENTATION_ROW_SUM', window_key)
        # Men whose records never include a valid dated postoperative continence observation, by category.
        no_valid = sub.loc[~sub.index.isin(candidate_ids)]
        out['without_valid_dated_record_at_any_time'] = {c: int((no_valid == c).sum()) for c in DOC_CATEGORIES}
        if out['without_valid_dated_record_at_any_time']['usable_pad_status'] != 0 or \
                out['without_valid_dated_record_at_any_time']['record_at_other_time_only'] != 0:
            fail('CANDIDATE_SET_INCONSISTENT', window_key)
        return out

    result = {'all': table(population)}
    for name, groups in strata.items():
        result[name] = {label: table(ids & population) for label, ids in groups.items()}

    # What the in-window rows of men without any explicit pad status contain (men, not rows).
    without = set(series.index[series == 'continence_record_without_pad_status'])
    wrows = rows.loc[rows[d.ID].isin(without)]
    content = {}
    for label, column in (('social_continence_documented', 'social_continence_documented'),
                          ('incontinence_documented', 'incontinence_documented'),
                          ('pad_use_documented', 'pad_use_documented')):
        if column in wrows.columns:
            content[label] = int(wrows.loc[eda.truth(wrows[column]), d.ID].nunique())
    if 'continence_status' in wrows.columns:
        status = wrows.assign(_s=wrows.continence_status.astype(str).str.strip().str.lower())
        counts = status.loc[status._s.ne('')].groupby('_s')[d.ID].nunique()
        content['continence_status_values_men'] = {k: int(v) for k, v in counts.items()
                                                   if v >= 3 and len(k) <= 40 and not any(ch.isdigit() for ch in k)}
        content['continence_status_blank_men'] = int(len(without) - status.loc[status._s.ne(''), d.ID].nunique())
    result['content_of_records_without_pad_status'] = {'men': int(len(without)), **content}
    return result


def main(argv):
    ap = argparse.ArgumentParser()
    cohort_mod.add_cohort_args(ap)
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args(argv)
    cohort_name = args.cohort
    out_path = cohort_mod.output_path(EVIDENCE, cohort_name)
    if not args.verify:
        cohort_mod.assert_writable_output(out_path)

    d = load('drv06', '06_derive_observed_assessments.py')
    E = load('est05', '05_observed_estimators.py')
    eda = d.eda
    ID = d.ID
    res = d.source_derive(cohort=cohort_name)
    if res['source_verification']['bound_inputs_before'] != 122:
        fail('BOUND_INPUT_COUNT')
    annotated, candidate, sets, robotic = res['annotated'], res['candidate'], res['sets'], set(res['robotic'])
    annotated = annotated.loc[annotated[ID].isin(robotic)]
    candidate_ids = set(candidate[ID])

    wide = pd.read_csv(d.RELEASE / 'tables/patient_wide.csv', dtype=str, keep_default_na=False,
                       usecols=[ID, 'country', 'operation_centre'])
    id_set = set(wide[ID].astype(str))
    wide = wide.loc[wide[ID].isin(robotic)]
    strata = {
        'by_country': {c: set(wide.loc[wide.country.eq(c), ID]) for c in d.COUNTRIES},
        'by_centre': {c: set(wide.loc[wide.operation_centre.eq(c), ID]) for c in CENTRES},
    }
    if sum(len(v) for v in strata['by_centre'].values()) != len(robotic):
        fail('CENTRE_PARTITION')

    early_users = set(sets['early_users'])
    doc_three = documentation(d, annotated, candidate_ids, robotic, set(sets['early_status_known']), 'early', strata)
    doc_year = documentation(d, annotated, candidate_ids, early_users, set(sets['year_status_known']) & early_users,
                             'year', strata)

    # Recording of safety pads and diapers among usable postoperative observations of the cohort.
    def device(frame):
        safety = eda.truth(frame.safety_pad_documented)
        diaper = eda.numeric(frame.diaper_count_min).gt(0) | eda.numeric(frame.diaper_count_max).gt(0)
        out = {'observation_rows': int(len(frame)), 'men': int(frame[ID].nunique()),
               'rows_with_safety_pad': int(safety.sum()), 'men_with_safety_pad': int(frame.loc[safety, ID].nunique()),
               'rows_with_diaper': int(diaper.sum()), 'men_with_diaper': int(frame.loc[diaper, ID].nunique())}
        return out

    devices = {'all': device(candidate)}
    for c in d.COUNTRIES:
        devices[c] = device(candidate.loc[candidate[ID].isin(strata['by_country'][c])])

    # Three-month assessment day and one-year pad freedom among the men compared.
    f = res['patients'].copy().reset_index(drop=True)
    f = f.loc[f['_burden'].isin(['one', 'two_or_more']) & f['_year_status'].notna()]
    day = pd.to_numeric(f['_early_day'], errors='coerce')
    if day.isna().any():
        fail('EARLY_DAY_MISSING')
    timing = {}
    for label, mask in (('days_60_89', day.lt(90)), ('days_90_120', day.ge(90))):
        block = {}
        for group in ('one', 'two_or_more'):
            sub = f.loc[mask & f['_burden'].eq(group)]
            block[group] = cell(E, int(sub['_year_status'].eq(1).sum()), int(len(sub)))
        both = f.loc[mask]
        block['both_groups'] = cell(E, int(both['_year_status'].eq(1).sum()), int(len(both)))
        timing[label] = block

    # Extreme allocation of men with unclear or conflicting three-month counts and a one-year record.
    g = res['patients']
    g = g.loc[g['_year_status'].notna()]
    one, two = g.loc[g['_burden'].eq('one')], g.loc[g['_burden'].eq('two_or_more')]
    unc = g.loc[~g['_burden'].isin(['one', 'two_or_more'])]
    n1, e1 = len(one), int(one['_year_status'].eq(1).sum())
    n2, e2 = len(two), int(two['_year_status'].eq(1).sum())
    nu, eu = len(unc), int(unc['_year_status'].eq(1).sum())
    extreme = {
        'unclassifiable_men': int(nu), 'unclassifiable_pad_free': int(eu),
        'main': newcombe(E, e1, n1, e2, n2),
        'pad_users_to_one_pad_and_pad_free_to_two_or_more': newcombe(E, e1, n1 + (nu - eu), e2 + eu, n2 + eu),
        'pad_free_to_one_pad_and_pad_users_to_two_or_more': newcombe(E, e1 + eu, n1 + eu, e2, n2 + (nu - eu)),
    }

    # One-year pad freedom by the pad count at six months, among men using pads at three and six months.
    s18 = load('pad18', '18_one_year_pad_category.py')
    selection = res['selection']
    grouped_six = s18.build_day_groups(d, selection['selected']['six'], candidate)
    grouped_early = s18.build_day_groups(d, selection['selected']['early'], candidate)
    grouped_year = s18.build_day_groups(d, selection['selected']['year'], candidate)
    h = res['patients'].copy().reset_index(drop=True)
    six_users = h.loc[h['_six_status'].eq(0) & h['_year_status'].notna()]
    six_level = {}
    for pid in six_users[ID]:
        rows = grouped_six.get(pid)
        if rows is None or len(rows) == 0:
            fail('SIX_MONTH_ROWS_MISSING')
        level, _, _ = d.classify_day(rows)
        six_level[pid] = level if level in ('one', 'two_or_more') else 'unclear_or_conflicting'
    six_users = six_users.assign(_six_level=six_users[ID].map(six_level))
    six_count = {'men': int(len(six_users)), 'pad_free_at_one_year': int(six_users['_year_status'].eq(1).sum())}
    for level in ('one', 'two_or_more', 'unclear_or_conflicting'):
        sub = six_users.loc[six_users['_six_level'].eq(level)]
        six_count[level] = cell(E, int(sub['_year_status'].eq(1).sum()), int(len(sub)))
    six_count['one_minus_two_or_more'] = newcombe(E, six_count['one']['n'], six_count['one']['N'],
                                                  six_count['two_or_more']['n'], six_count['two_or_more']['N'])
    if sum(six_count[k]['N'] for k in ('one', 'two_or_more', 'unclear_or_conflicting')) != six_count['men']:
        fail('SIX_MONTH_LEVEL_SUM')
    heavier = {}
    for level in ('one', 'two_or_more', 'unclear_or_conflicting'):
        sub = six_users.loc[six_users['_six_level'].eq(level)]
        cats = [s18.classify_one_year_category(d, grouped_year, pid, st)[0]
                for pid, st in zip(sub[ID], sub['_year_status'])]
        heavier[level] = {'more_than_one_pad_per_day': cell(E, cats.count('two_or_more'), int(len(sub))),
                          'pads_count_not_recorded': int(cats.count('not_classifiable'))}
    six_count['one_year_pad_use_by_six_month_pad_count'] = heavier

    # One-year outcome from the record nearest day 365 anywhere between the six-month and two-year
    # windows, for men using one pad or two or more pads at three months.
    wide_chosen, _ = d.select_window(candidate, WIDER_YEAR_WINDOW, 'nearest')
    wide_status = dict(zip(wide_chosen[ID], pd.to_numeric(wide_chosen['_status'], errors='coerce')))
    wide_day = dict(zip(wide_chosen[ID], pd.to_numeric(wide_chosen['_day'], errors='coerce')))
    w = res['patients'].copy().reset_index(drop=True)
    w = w.loc[w['_burden'].isin(['one', 'two_or_more'])]
    w = w.assign(_wide_status=w[ID].map(wide_status), _wide_day=w[ID].map(wide_day))
    paired = w.loc[w['_year_status'].notna()]
    if (paired['_wide_status'].isna().any() or not paired['_wide_day'].between(305, 425).all()
            or not paired['_wide_status'].eq(pd.to_numeric(paired['_year_status'], errors='coerce')).all()):
        fail('WIDER_WINDOW_DISAGREES_WITH_ONE_YEAR_WINDOW')
    periods = (('days_211_304', 211, 304), ('days_305_425', 305, 425), ('days_426_669', 426, 669))
    wider = {'window_days': [WIDER_YEAR_WINDOW[0], WIDER_YEAR_WINDOW[1]], 'target_day': WIDER_YEAR_WINDOW[2]}
    for group in ('one', 'two_or_more'):
        sub = w.loc[w['_burden'].eq(group)]
        have = sub.loc[sub['_wide_status'].notna()]
        block = {'men_using_pads_at_three_months': int(len(sub)),
                 'pad_free': cell(E, int(have['_wide_status'].eq(1).sum()), int(len(have))),
                 'by_day_of_record': {}}
        for name, low, high in periods:
            part = have.loc[have['_wide_day'].between(low, high)]
            block['by_day_of_record'][name] = cell(E, int(part['_wide_status'].eq(1).sum()), int(len(part)))
        if sum(v['N'] for v in block['by_day_of_record'].values()) != len(have):
            fail('WIDER_WINDOW_PERIOD_SUM')
        wider[group] = block
    wider['one_minus_two_or_more'] = newcombe(E, wider['one']['pad_free']['n'], wider['one']['pad_free']['N'],
                                              wider['two_or_more']['pad_free']['n'], wider['two_or_more']['pad_free']['N'])
    if (wider['one']['by_day_of_record']['days_305_425']['N'], wider['two_or_more']['by_day_of_record']['days_305_425']['N']) != (n1, n2):
        fail('WIDER_WINDOW_MAIN_GROUPS')

    # Pad use at one year by country and three-month pad level, and the three-month level mix by country.
    h['_fine_level'] = [s18.three_month_fine_level(d, grouped_early, pid, str(b)) for pid, b in zip(h[ID], h['_burden'])]
    level_names = {'one': 'one', 'two': 'two', 'three_or_more': 'three_or_more',
                   'two_or_more_unseparated': 'two_or_more_unseparated'}
    by_country = {}
    for country in d.COUNTRIES:
        hc = h.loc[h['_country'].eq(country)]
        mix = {name: int(hc['_fine_level'].eq(key).sum()) for key, name in level_names.items()}
        mix['unclear_or_conflicting'] = int((~hc['_fine_level'].isin(level_names)).sum())
        mix['men_using_pads_at_three_months'] = int(len(hc))
        if sum(v for k, v in mix.items() if k != 'men_using_pads_at_three_months') != len(hc):
            fail('COUNTRY_LEVEL_MIX_SUM', country)
        outcome = {}
        with_year = hc.loc[hc['_year_status'].notna()]
        for key, name in level_names.items():
            sub = with_year.loc[with_year['_fine_level'].eq(key)]
            cats = [s18.classify_one_year_category(d, grouped_year, pid, st)[0] for pid, st in zip(sub[ID], sub['_year_status'])]
            outcome[name] = {'pad_free': cell(E, int(sub['_year_status'].eq(1).sum()), int(len(sub))),
                             'more_than_one_pad_per_day': cell(E, cats.count('two_or_more'), int(len(sub))),
                             'pads_count_not_recorded': int(cats.count('not_classifiable'))}
        # Cochran-Armitage trend in pad freedom across exactly one, exactly two, and three or more pads.
        trend = s18.armitage([{'n': outcome[k]['pad_free']['N'], 'events': outcome[k]['pad_free']['n']}
                              for k in ('one', 'two', 'three_or_more')], [1, 2, 3])
        by_country[country] = {'three_month_level_mix': mix, 'one_year_by_three_month_level': outcome,
                               'pad_freedom_trend_one_two_three_or_more': trend}
    if sum(b['three_month_level_mix']['men_using_pads_at_three_months'] for b in by_country.values()) != len(h):
        fail('COUNTRY_PARTITION_INCOMPLETE')

    # More than one pad per day at one year when one-year records are missing. The weights repeat the
    # record-availability model of script 16 among men using one pad or two or more pads at three months,
    # and must reproduce its weighted pad-free proportions.
    cov = pd.read_csv(d.RELEASE / 'tables/patient_wide.csv', dtype=str, keep_default_na=False,
                      usecols=[ID, 'operation_centre', 'surgery_date', 'nerve_sparing_state', 'pT_ordinal'])
    cov = cov.set_index(cov[ID].astype(str)).loc[h[ID].astype(str).to_numpy()].reset_index(drop=True)
    surgery = pd.to_datetime(cov['surgery_date'].str.strip(), errors='coerce')
    if surgery.isna().any():
        fail('SURGERY_DATE')
    pt = pd.to_numeric(cov['pT_ordinal'].str.strip().replace('', np.nan), errors='coerce').to_numpy(float)
    ns = cov['nerve_sparing_state'].astype(str).str.strip().to_numpy()
    centre = cov['operation_centre'].astype(str).to_numpy()
    burden = h['_burden'].astype(str).to_numpy()
    # As in script 16, only men whose one-year window had ended enter the availability model.
    window_ended = ((surgery + pd.Timedelta(days=d.WINDOWS['year'][1])) < pd.Timestamp('2026-04-01')).to_numpy()
    in_groups = np.isin(burden, ['one', 'two_or_more']) & window_ended
    design = pd.DataFrame({
        'intercept': 1.0,
        'two_or_more': (burden == 'two_or_more').astype(float),
        'age_per10_cent65': (pd.to_numeric(h['_age'], errors='coerce').to_numpy(float) - 65.0) / 10.0,
        'early_day_per30_cent90': (pd.to_numeric(h['_early_day'], errors='coerce').to_numpy(float) - 90.0) / 30.0,
        'centre_belchatow': (centre == 'Bełchatów').astype(float),
        'centre_salve': (centre == 'Salve Medica').astype(float),
        'period_recent': (surgery.dt.year.to_numpy() >= cohort_mod.recent_period_start_year(cohort_name)).astype(float),
        'nerve_sparing_not_performed': (ns == 'not_performed').astype(float),
        'nerve_sparing_not_stated': (~np.isin(ns, ['performed', 'not_performed'])).astype(float),
        'pt3_or_higher': np.where(np.isnan(pt), np.nan, (np.nan_to_num(pt) >= 2).astype(float)),
    })
    Aw = design.loc[in_groups].reset_index(drop=True)
    if Aw.isna().any().any():
        fail('AVAILABILITY_COVARIATES_INCOMPLETE')
    hw = h.loc[in_groups].reset_index(drop=True)
    rec = hw['_year_status'].notna().to_numpy()
    free = hw['_year_status'].eq(1).fillna(False).to_numpy(bool)
    two_w = hw['_burden'].astype(str).eq('two_or_more').to_numpy()
    level = hw['_fine_level'].astype(str).to_numpy()
    cat = np.array([s18.classify_one_year_category(d, grouped_year, pid, st)[0] if pd.notna(st) else ''
                    for pid, st in zip(hw[ID], hw['_year_status'])])
    heavy = cat == 'two_or_more'
    uncounted = cat == 'not_classifiable'

    def availability_weights(Am, r):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                fit = sm.Logit(r.astype(float), Am).fit(disp=False, maxiter=200)
            except Exception:
                return None
        if not fit.mle_retvals.get('converged', False) or not np.all(np.isfinite(fit.params.to_numpy(float))):
            return None
        prob = 1 / (1 + np.exp(-(Am.to_numpy(float) @ fit.params.to_numpy(float))))
        return np.where(r, 1 / prob, 0.0)

    def weighted_share(wv, mask, event):
        den = float(wv[mask].sum())
        return float((wv[mask] * event[mask]).sum() / den) if den > 0 else None

    wt = availability_weights(Aw, rec)
    if wt is None:
        fail('AVAILABILITY_MODEL')
    s16 = json.loads(cohort_mod.output_path(HERE / 'evidence/STRENGTHENING_ANALYSES.json', cohort_name).read_text())
    ref_av = s16['record_availability']
    if (len(hw) != ref_av['n']
            or abs(weighted_share(wt, rec & ~two_w, free) - ref_av['weighted_one_pad']) > 1e-9
            or abs(weighted_share(wt, rec & two_w, free) - ref_av['weighted_two_or_more']) > 1e-9):
        fail('AVAILABILITY_WEIGHTS_DISAGREE_WITH_SCRIPT_16')
    rng = np.random.default_rng(HEAVIER_SEED)
    draws = {key: [] for key in HEAVIER_LEVELS}
    draws['three_or_more_minus_one'] = []
    failed_fits = 0
    for _ in range(HEAVIER_DRAWS):
        idx = rng.integers(0, len(hw), len(hw))
        wb = availability_weights(Aw.iloc[idx].reset_index(drop=True), rec[idx])
        if wb is None:
            failed_fits += 1
            continue
        vals = {key: weighted_share(wb, rec[idx] & (level[idx] == key), heavy[idx]) for key in HEAVIER_LEVELS}
        for key in HEAVIER_LEVELS:
            if vals[key] is not None:
                draws[key].append(vals[key])
        if vals['one'] is not None and vals['three_or_more'] is not None:
            draws['three_or_more_minus_one'].append(vals['three_or_more'] - vals['one'])
    heavier_missing = {'men': int(len(hw)), 'men_with_one_year_record': int(rec.sum()), 'seed': HEAVIER_SEED,
                       'draws': HEAVIER_DRAWS, 'failed_fits': failed_fits, 'max_weight': float(wt.max()),
                       'covariates': list(Aw.columns), 'by_three_month_level': {}}
    for key in HEAVIER_LEVELS:
        at_level = level == key
        m = rec & at_level
        N, n_rec, x, u = int(at_level.sum()), int(m.sum()), int(heavy[m].sum()), int(uncounted[m].sum())
        observed = x / n_rec
        heavier_missing['by_three_month_level'][key] = {
            'men_at_three_months': N, 'men_without_one_year_record': N - n_rec,
            'observed': cell(E, x, n_rec),
            'pads_count_not_recorded': u,
            'if_uncounted_men_used_more_than_one_pad': cell(E, x + u, n_rec),
            'weighted_for_record_availability': {
                'share': weighted_share(wt, m, heavy),
                'bootstrap_lower': float(np.percentile(draws[key], 2.5)),
                'bootstrap_upper': float(np.percentile(draws[key], 97.5)), 'valid_draws': len(draws[key])},
            'all_men_under_assumed_share_among_men_without_a_record': {
                name: {'assumed_share': min(1.0, factor * observed),
                       'share_of_all_men': (x + (N - n_rec) * min(1.0, factor * observed)) / N}
                for name, factor in HEAVIER_FACTORS},
        }
    w_one = heavier_missing['by_three_month_level']['one']['weighted_for_record_availability']['share']
    w_three = heavier_missing['by_three_month_level']['three_or_more']['weighted_for_record_availability']['share']
    heavier_missing['weighted_three_or_more_minus_one'] = {
        'difference': w_three - w_one,
        'bootstrap_lower': float(np.percentile(draws['three_or_more_minus_one'], 2.5)),
        'bootstrap_upper': float(np.percentile(draws['three_or_more_minus_one'], 97.5)),
        'valid_draws': len(draws['three_or_more_minus_one'])}
    for key in HEAVIER_LEVELS:
        pooled = sum(by_country[c]['one_year_by_three_month_level'][key]['more_than_one_pad_per_day']['n'] for c in d.COUNTRIES)
        pooled_n = sum(by_country[c]['one_year_by_three_month_level'][key]['more_than_one_pad_per_day']['N'] for c in d.COUNTRIES)
        obs = heavier_missing['by_three_month_level'][key]['observed']
        if (pooled, pooled_n) != (obs['n'], obs['N']):
            fail('HEAVIER_USE_DISAGREES_WITH_COUNTRY_BLOCK', key)

    # Both blocks must agree with the one-year pad category record of script 18.
    ref_path = cohort_mod.output_path(HERE / 'evidence/ONE_YEAR_PAD_CATEGORY.json', cohort_name)
    ref = json.loads(ref_path.read_text())
    ref_six = ref['table_d_recovery_after_six_months']['six_month_pad_use_with_year_record']['overall']
    if (six_count['men'], six_count['pad_free_at_one_year']) != (ref_six['N'], ref_six['n']):
        fail('SIX_MONTH_REFERENCE_MISMATCH')

    gates = {'eligible_men': len(robotic), 'three_month_usable': doc_three['all']['usable_pad_status'],
             'early_users': len(early_users), 'one_year_usable': doc_year['all']['usable_pad_status'],
             'compared_men': int(len(f)), 'one_n': int(n1), 'one_events': int(e1), 'two_n': int(n2),
             'two_events': int(e2), 'unclassifiable_n': int(nu)}
    try:
        cohort_mod.check_or_record_gates('19_documentation_and_timing', cohort_name, gates, record=args.record_gates)
    except cohort_mod.GateError as exc:
        fail(exc.code, exc.detail)

    record = {
        'analysis_id': 'M1-DOCUMENTATION-TIMING',
        'status': 'exploratory_descriptive',
        'cohort': res['cohort'],
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'window_days': {'three_month': list(d.WINDOWS['early'][:2]), 'one_year': list(d.WINDOWS['year'][:2])},
        'category_definitions': {
            'usable_pad_status': 'a usable assessment with an explicit pad status was selected in the window',
            'pad_status_recorded_not_usable': 'a dated postoperative record in the window states a pad status, '
                                              'but no usable assessment was selected',
            'continence_record_without_pad_status': 'dated postoperative records in the window, none stating a '
                                                    'pad status',
            'record_at_other_time_only': 'no record located in the window, valid dated observations at other '
                                         'times',
            'no_dated_continence_record': 'no record located in the window and no valid dated postoperative '
                                          'observation at any other time',
        },
        'documentation_three_month_window_all_men': doc_three,
        'documentation_one_year_window_men_using_pads_at_three_months': doc_year,
        'safety_pad_and_diaper_recording_usable_observations': devices,
        'pad_freedom_at_one_year_by_three_month_assessment_day': timing,
        'extreme_allocation_of_unclassifiable_counts': extreme,
        'one_year_pad_freedom_by_six_month_pad_count': six_count,
        'pad_use_by_country_and_three_month_level': by_country,
        'pad_freedom_near_one_year_in_the_wider_window': wider,
        'more_than_one_pad_at_one_year_when_records_are_missing': heavier_missing,
    }
    text = json.dumps(d.strict(record), indent=2, sort_keys=True, allow_nan=False, ensure_ascii=False)
    for pid in id_set:
        if pid and len(pid) > 3 and pid in text:
            fail('IDENTIFIER_LEAK')
    scan = dict(record)
    cscan = dict(scan['cohort'])
    cscan.pop('common_extract_date', None)
    scan['cohort'] = cscan
    if DATE_SHAPED.search(json.dumps(d.strict(scan), sort_keys=True, allow_nan=False)):
        fail('DATE_SHAPED_TOKEN')

    if args.verify:
        if not out_path.is_file() or json.loads(out_path.read_text()) != json.loads(text):
            fail('SAVED_RECORD_MISMATCH')
        print(json.dumps({'status': 'saved_documentation_and_timing_recomputed_exactly', 'cohort': cohort_name}))
        return 0
    out_path.write_text(text + '\n')
    print(json.dumps({'status': 'written', 'cohort': cohort_name, 'path': str(out_path)}))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
