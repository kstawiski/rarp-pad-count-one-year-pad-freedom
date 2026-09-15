"""Fill the v6 supplementary-material template with tables built from frozen records.

Inputs are aggregate only: the selection, post hoc, clinical-adjustment and observed-status evidence records
and the previously verified supplementary CSV exports. Percentages and difference limits
use two significant figures rounded half up (D-P1). Odds ratios keep two decimals.
"""
import csv
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from math import exp, sqrt
from pathlib import Path

M1 = Path('/umed-projekty/PROSTATA_JOBCZYK2026_v2/manuscript1')
EV = M1 / 'evidence'
OLD = M1 / 'supplement/rendered'
TEMPLATE = M1 / 'supplement/drafts/supplementary-template-v6.md'
OUT = M1 / 'supplement/drafts/supplementary-material-v6.md'
SEL = json.loads((EV / 'SELECTION_FOLLOWUP_SENSITIVITY.json').read_text())
PH = json.loads((EV / 'POSTHOC_TWOGROUP.json').read_text())
CLIN = json.loads((EV / 'CLINICAL_ADJUSTMENT.json').read_text())
ST = json.loads((EV / 'STRENGTHENING_ANALYSES.json').read_text())
DASH, MINUS = '–', '−'
CENTRES = (('Bełchatów Hospital', 'Bełchatów'), ('SalveMedica', 'Salve Medica'),
           ("Brigham and Women's Hospital", "Brigham and Women's Hospital"))


def sig2(v):
    if v == 0:
        return '0'
    d = Decimal(repr(float(v)))
    e = d.copy_abs().adjusted()
    q = Decimal(1).scaleb(e - 1)
    r = d.quantize(q, rounding=ROUND_HALF_UP)
    if r.copy_abs().adjusted() > e:
        q = Decimal(1).scaleb(e)
        r = d.quantize(q, rounding=ROUND_HALF_UP)
    s = str(int(r)) if q >= 1 else format(r, 'f')
    return s.replace('-', MINUS)


def pp(x):
    return sig2(100 * x)


def rng(lo, hi):
    sep = ' to ' if lo < 0 or hi < 0 else DASH
    return f'{pp(lo)}{sep}{pp(hi)}'


def ci(e, lo, hi):
    return f'{pp(e)} ({rng(lo, hi)})'


def whole(v):
    return str(int(Decimal(repr(float(v))).quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def mediqr(m):
    return f"{whole(m['median'])} ({whole(m['q1'])}{DASH}{whole(m['q3'])})"


def two_dec(v):
    return format(Decimal(repr(float(v))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')


def orci(o, lo, hi):
    return f'{two_dec(o)} ({two_dec(lo)}{DASH}{two_dec(hi)})'


def npct(n, d):
    return f'{n} ({sig2(100 * n / d)}%)' if n else '0'


def frac(n, d):
    return f'{n}/{d} ({sig2(100 * n / d)}%)'


def table(header, rows):
    # Dash counts set pandoc's relative column widths, so wide label columns get more room.
    widths = [max([len(re.sub(r'\*', '', str(r[i]))) for r in rows] + [max(len(word) for word in h.split()) + 2])
              for i, h in enumerate(header)]
    dashes = ['-' * max(16, min(34, w + 2)) for w in widths]
    out = ['| ' + ' | '.join(header) + ' |', '| ' + ' | '.join(dashes) + ' |']
    for r in rows:
        out.append('| ' + ' | '.join(r) + ' |')
    return '\n'.join(out)


def restyle_estimate(text):
    """'39/198 (20%, 15–26)' keeps its recorded Wilson limits; only the separator changes."""
    return text.replace('%, ', '%; ')


def s1a():
    r = SEL['robotic_early_assessment']
    a, b = r['with_early_assessment'], r['without_early_assessment']
    na, nb = a['n'], b['n']
    rows = [['**Country**', '', '']]
    for c in ('Poland', 'United States'):
        rows.append([c, npct(a['country'].get(c, 0), na), npct(b['country'].get(c, 0), nb)])
    rows.append(['**Centre**', '', ''])
    for label, key in CENTRES:
        rows.append([label, npct(a['centre'].get(key, 0), na), npct(b['centre'].get(key, 0), nb)])
    rows.append(['**Year of surgery**', '', ''])
    for label, key in (('2014' + DASH + '2022', '2014-2022'), ('2023', '2023'), ('2024', '2024'), ('2025' + DASH + '2026', '2025-2026')):
        rows.append([label, npct(a['operative_period'].get(key, 0), na), npct(b['operative_period'].get(key, 0), nb)])
    if 'missing' in a['operative_period'] or 'missing' in b['operative_period']:
        raise SystemExit('unexpected missing operative year')
    rows.append(['Age, yr, median (IQR)', mediqr(a['age']), mediqr(b['age'])])
    rows.append(['Any dated postoperative continence record', npct(a['any_valid_dated_postoperative_continence_record'], na),
                 npct(b['any_valid_dated_postoperative_continence_record'], nb)])
    rows.append(['No last-contact date in the database follow-up field', npct(a['no_dated_postoperative_contact'], na),
                 npct(b['no_dated_postoperative_contact'], nb)])
    return table(['Characteristic', f'With a three-month assessment (n = {na})', f'Without a three-month assessment (n = {nb})'], rows)


def s1b():
    rows = []
    for r in csv.DictReader((OLD / 'S6_operative_year_availability.csv').open()):
        year = r['Operative year'].replace('-', DASH)
        w, t = int(r['With a one-year record']), int(r['Early pad users'])
        if int(r['Without a one-year record']) + w != t:
            raise SystemExit('S1B arithmetic')
        rows.append([year, str(w), r['Without a one-year record'], str(t), f'{sig2(100 * w / t)}%'])
    return table(['Year of surgery', 'With a one-year record', 'Without a one-year record', 'Men using pads', 'Availability'], rows)


GROUP_LABELS = {
    'All burden levels': 'All men using pads',
    'One ordinary pad documented': 'One pad',
    'Two or more ordinary pads documented': 'Two or more pads',
    'Pad quantity unclear, no conflicting evidence': 'Unclear count',
    'Pad quantity conflicting or invalid': 'Conflicting count',
}


def s2():
    windows = {'Early-user pairs, six months': 'six', 'Early-user pairs, year': 'year', 'Early-user pairs, two years': 'two'}
    cells, order = {}, []
    transitions = {}
    for r in csv.reader((OLD / 'S4_other_windows.csv').open()):
        if r[0] in windows:
            label = r[1]
            if 'Unknown or other' in label:
                continue
            parts = label.split(', ')
            if parts[-1] in ('Poland', 'United States') and len(parts) > 1:
                base = ', '.join(parts[:-1])
                display = f"{GROUP_LABELS.get(base, base)}, {parts[-1]}"
            else:
                display = GROUP_LABELS.get(label, label)
            if display not in order:
                order.append(display)
            value = restyle_estimate(r[4])
            cells[(display, windows[r[0]])] = 'no men' if value.startswith('0/0') else value
        elif r[0].startswith('All-status pairs') and len(r) > 4 and r[2] == 'Early pad free' and r[3] == 'Later pad free':
            transitions[r[0].split(', ')[1]] = restyle_estimate(r[4])
    rows = [[d] + [cells.get((d, w), 'no men') for w in ('six', 'year', 'two')] for d in order]
    part_a = table(['Three-month pad group', 'Six months (days 150' + DASH + '210)', 'One year (days 305' + DASH + '425)',
                    'Two years (days 670' + DASH + '790)'], rows)
    part_b = table(['Window', 'Pad-free at the later assessment among men pad-free at three months'],
                   [['Six months', transitions['six months']], ['One year', transitions['year']], ['Two years', transitions['two years']]])
    return part_a, part_b


def s3():
    diag = {}
    for r in csv.DictReader((OLD / 'S5_diagnostics.csv').open()):
        diag[(r['Check'], r['Population'], r['Measure'])] = r['Value']
    pops = ('Pooled', 'Poland', 'United States')
    spec = [
        ('Largest change in the difference after removing one patient, percentage points', 'Leave-one-patient-out influence', 'Maximum absolute change'),
        ('Sign changes after removing one patient', 'Leave-one-patient-out influence', 'Sign changes'),
        ('Monte Carlo SD of the lower 95% confidence limit, percentage points', 'Bootstrap endpoint variability', 'Lower endpoint standard deviation'),
        ('Monte Carlo SD of the upper 95% confidence limit, percentage points', 'Bootstrap endpoint variability', 'Upper endpoint standard deviation'),
        ('Bootstrap resamples lacking a pad group', 'Bootstrap endpoint variability', 'Failed draws'),
    ]
    rows = [[label] + [diag[(check, p, measure)] for p in pops] for label, check, measure in spec]
    part_a = table(['Check', 'Both countries', 'Poland', 'United States'], rows)
    c = SEL['counts_in_classifiable_pairs']
    pf = SEL['contrasts']['platform_flag_excluded']
    rng = lambda pop, measure: diag[('Range flag', pop, measure)]
    plat = lambda pop, measure: diag[('Platform-conflict flag', pop, measure)]
    rows_b = [
        ['Men using pads with a recorded range on the three-month day', f"{rng('Early users', 'Flagged early users')} (one pad {rng('One ordinary pad documented', 'Flagged early users')}, two or more {rng('Two or more ordinary pads documented', 'Flagged early users')}, unclear {rng('Pad quantity unclear, no conflicting evidence', 'Flagged early users')}, conflicting {rng('Pad quantity conflicting or invalid', 'Flagged early users')})"],
        ['Two-or-more classifications relying on a range, among men with a one-year record', str(c['range_reliant_two_or_more'])],
        ['Diapers or safety pads recorded on the three-month day, among the 201 men compared', str(c['device_evidence_one'] + c['device_evidence_two_or_more'])],
        ['Men with EPIC questionnaire pad counts, among the 226 men with a one-year record', str(c['epic_pairs'])],
        ['Platform data-quality flag, all patients (all recorded as robot-assisted)', plat('All released patients', 'Flagged patients')],
        ['Platform data-quality flag, men with a one-year record', f"{plat('Observed year pairs', 'Flagged patients')} (one pad {plat('One ordinary pad documented', 'Flagged observed year pairs')}, unclear {plat('Pad quantity unclear, no conflicting evidence', 'Flagged observed year pairs')}, pad-free {plat('Pairs with later pad freedom', 'Flagged observed year pairs')})"],
        ['Difference after excluding flagged men, percentage points (95% CI)', ci(pf['difference'], pf['bootstrap_lower'], pf['bootstrap_upper'])],
    ]
    if c['platform_flag_pairs'] != int(plat('Observed year pairs', 'Flagged patients')):
        raise SystemExit('platform flag reconciliation')
    part_b = table(['Recording check', 'Result'], rows_b)
    return part_a, part_b


def s4():
    m = SEL['availability']['model_one_vs_two_or_more']
    p = m['params']
    spec = [('Two or more pads vs one pad', 'two_or_more'), ('Age, per 10 years', 'age_per10_cent65'),
            ('Three-month assessment day, per 30 days', 'early_day_per30_cent90'),
            ('Bełchatów Hospital vs Brigham and Women\'s Hospital', 'centre_belchatow'),
            ('SalveMedica vs Brigham and Women\'s Hospital', 'centre_salve'),
            ('One-year window not closed before 1 April 2026', 'window_open_at_extract')]
    rows = [[label, orci(p[k]['or'], *p[k]['wald_ci'])] for label, k in spec]
    return table([f"Characteristic (n = {m['n']}, {m['events_with_year']} with a one-year record)",
                  'Odds ratio for a one-year record (95% CI)'], rows)


def s5():
    cols = (('window_closed_before_common_extract', 'One-year window closed'), ('all_early_users', 'All one-pad and two-or-more users'))
    mo = {k: SEL['missing_outcome'][k] for k, _ in cols}

    def row(label, fn):
        return [label] + [fn(mo[k]) for k, _ in cols]

    def group(m, g):
        x = m['groups'][g]
        return f"{x['events']}/{x['observed']} pad-free, {x['unobserved']} without a record"

    def q1tip(m):
        v = m['q1_tipping_if_unobserved_two_or_more_like_observed']
        if v < 0:
            g1, g2 = m['groups']['one'], m['groups']['two']
            d0 = g1['events'] / g1['early_users'] - (g2['events'] + g2['unobserved'] * m['observed_two']) / g2['early_users']
            return f'Not reached (difference {pp(d0)} points at 0%)'
        return f'{pp(v)}%'

    eq = lambda m, q: pp(m['equal_unobserved_proportion_difference'][q])
    rows = [
        row('One pad', lambda m: group(m, 'one')),
        row('Two or more pads', lambda m: group(m, 'two')),
        row('Difference if unobserved men resemble observed men in their group', lambda m: pp(m['mar_within_group_difference'])),
        row('Difference if both unobserved groups are 0% pad-free', lambda m: eq(m, '0.0')),
        row('Difference if both unobserved groups are 25% pad-free', lambda m: eq(m, '0.25')),
        row('Difference if both unobserved groups are 50% pad-free', lambda m: eq(m, '0.5')),
        row('Difference if both unobserved groups are 75% pad-free', lambda m: eq(m, '0.75')),
        row('Difference if both unobserved groups are 100% pad-free', lambda m: eq(m, '1.0')),
        row('Pad freedom among unobserved one-pad users that removes the difference, if unobserved two-or-more users resemble observed ones', q1tip),
        row('Pad freedom among unobserved two-or-more users that removes the difference, if unobserved one-pad users resemble observed ones',
            lambda m: f"{pp(m['q2_tipping_if_unobserved_one_pad_like_observed'])}%"),
        row('Equal and opposite shift from observed proportions that removes the difference, percentage points',
            lambda m: pp(m['symmetric_shift_tipping_delta'])),
        row('Lowest and highest possible difference', lambda m: f"{pp(m['lower_bound'])} to {pp(m['upper_bound'])}"),
        row('Share of assumption pairs, in 1-point steps, with a positive difference',
            lambda m: f"{pp(m['share_of_unit_square_with_positive_difference_step_0_01'])}%"),
    ]
    header = ['Scenario'] + [f"{lab} (one pad {mo[k]['groups']['one']['early_users']}, two or more {mo[k]['groups']['two']['early_users']})" for k, lab in cols]
    return table(header, rows)


RULES = (('Reference nearest assessment', 'Reference rule'),
         ('Exclude windows with any conflicting status', 'Conflicting windows excluded'),
         ('First usable assessment', 'First usable assessment'),
         ('Narrower assessment windows', 'Narrower windows'),
         ('Exclude potential date-selection impact', 'Uncertain assessment dates excluded'),
         ('Recorded three- and twelve-month milestones', 'Recorded 3- and 12-month milestones'))


def s6():
    mem, coupled = {}, {}
    for r in csv.reader((OLD / 'S2_membership.csv').open()):
        if r[0] == 'Membership':
            mem[(r[1], r[2])] = r[3:8]
        elif r[0] in ('Coupled changes', 'Milestone coupled changes') and r[1]:
            coupled[(r[1], r[2])] = (r[3], r[5])
    rows_a = []
    for key, label in RULES:
        users = mem[(key, 'Early pad users')][1]
        ref, size, both, entering, leaving = mem[(key, 'Early-user year pairs')]
        if key == 'Recorded three- and twelve-month milestones':
            changes = ['not applicable'] * 3
        elif key == 'Reference nearest assessment':
            changes = ['0', '0', '0']
        else:
            changes = []
            for measure in ('Selected early day changed', 'Selected year day changed', 'Early documentation group changed'):
                n, d = coupled[(key, measure)]
                changes.append(f'{n}/{d}')
        rows_a.append([label, users, size, both, entering, leaving] + changes)
    part_a = table(['Rule', 'Men using pads', 'With a one-year record', 'Also in reference', 'Added', 'Removed',
                    'Three-month day changed', 'One-year day changed', 'Pad group changed'], rows_a)
    est = {}
    for r in csv.reader((OLD / 'S3_estimates.csv').open()):
        if len(r) >= 7 and r[0] != 'Section':
            est[(r[1], r[2], r[3])] = (r[4], r[5], r[6])
    rows_b = []
    for key, label in RULES:
        g = lambda pop: restyle_estimate(est.get((key, 'Documentation group', pop), ('not applicable',))[0])
        overall = restyle_estimate(est[(key, 'Overall', 'All early-user pairs')][0])
        diff = est.get((key, 'Ordered-group difference', 'One documented pad minus two or more documented pads'))
        boot, newc = (diff[1], diff[2]) if diff else ('not applicable', 'not applicable')
        rows_b.append([label, g('One ordinary pad documented'), g('Two or more ordinary pads documented'),
                       g('Pad quantity unclear, no conflicting evidence'), g('Pad quantity conflicting or invalid'),
                       overall, boot, newc])
    part_b = table(['Rule', 'One pad', 'Two or more pads', 'Unclear count', 'Conflicting count', 'All',
                    'Difference (bootstrap 95% CI)', 'Newcombe 95% CI'], rows_b)
    return part_a, part_b


def s7():
    c = SEL['contrasts']
    spec = [('reference', 'Reference comparison'),
            ('exact_count_records', 'Exact counts only'),
            ('epic_instrument_excluded', 'EPIC questionnaire counts excluded'),
            ('platform_flag_excluded', 'Platform data-quality flag excluded'),
            ('window_closed_before_common_extract', 'One-year window closed before 1 April 2026'),
            ('window_closed_poland', 'One-year window closed, Poland'),
            ('window_closed_united_states', 'One-year window closed, United States'),
            ('operative_era_2017_2024', 'Operated 2017' + DASH + '2024')]
    rows_a = []
    for k, label in spec:
        x = c[k]
        rows_a.append([label, str(x['pairs']), frac(x['one_events'], x['one_n']), frac(x['two_events'], x['two_n']),
                       ci(x['difference'], x['bootstrap_lower'], x['bootstrap_upper']),
                       rng(x['newcombe_lower'], x['newcombe_upper'])])
    part_a = table(['Comparison', 'Men with a one-year record', 'One pad, pad-free', 'Two or more pads, pad-free',
                    'Difference (bootstrap 95% CI)', 'Newcombe 95% CI'], rows_a)

    def params(model, key, coef_scale):
        p = model['params'].get(key)
        if p is None:
            return '' + DASH
        if coef_scale:
            lo, hi = (exp(v) for v in p['wald_ci'])
        else:
            lo, hi = p['wald_ci_or']
        return orci(p['or'], lo, hi)

    models = [(SEL['posthoc_country_model_without_year_day'], False, 'Age, country, three-month day'),
              (PH['posthoc_adjusted_two_group_model'], True, 'Age, country, both assessment days'),
              (PH['centre_adjusted_sensitivity']['no_yearday'], True, 'Centre, period, age, three-month day'),
              (PH['centre_adjusted_sensitivity']['with_yearday'], True, 'Centre, period, age, both assessment days')]
    names = {'two_or_more': 'Two or more pads vs one pad', 'burden_two_or_more': 'Two or more pads vs one pad'}
    rowspec = [('Two or more pads vs one pad', ('two_or_more', 'burden_two_or_more')),
               ('Age, per 10 years from 65', ('age_per10_cent65',)),
               ('Three-month assessment day, per 30 days from day 90', ('early_day_per30_cent90',)),
               ('One-year assessment day, per 30 days from day 365', ('year_day_per30_cent365',)),
               ('United States vs Poland', ('country_us',)),
               ('Bełchatów Hospital vs Brigham and Women\'s Hospital', ('centre_belchatow',)),
               ('SalveMedica vs Brigham and Women\'s Hospital', ('centre_salve',)),
               ('Operation in 2025' + DASH + '2026 vs earlier', ('period_recent',)),
               ('Intercept (odds)', ('intercept',))]
    rows_b = []
    for label, keys in rowspec:
        row = [label]
        for model, coef_scale, _ in models:
            key = next((k for k in keys if k in model['params']), None)
            row.append(params(model, key, coef_scale) if key else DASH)
        rows_b.append(row)
    rows_b.append(['Standardized pad freedom, one pad vs two or more'] +
                  [f"{pp(m['standardized_one_pad'])}% vs {pp(m['standardized_two_or_more'])}%" for m, _, _ in models])
    rows_b.append(['Standardized difference, percentage points (bootstrap 95% CI)'] +
                  [ci(m['standardized_difference'], m['bootstrap']['lower'], m['bootstrap']['upper']) for m, _, _ in models])
    rows_b.append(['Bootstrap refits not converged, of 2000'] + [str(m['bootstrap']['failed_fits']) for m, _, _ in models])
    rows_b.append(['Men (pad-free)'] + [f"{m.get('n', 201)} ({m.get('events', 82)})" for m, _, _ in models])
    part_b = table(['Term, odds ratio (95% CI)'] + [lab for _, _, lab in models], rows_b)

    iw = CLIN['ipw_clinical']
    clin_cols = [(CLIN['clinical']['model'], CLIN['clinical']['crude_same_men'], 'Clinical model'),
                 (CLIN['clinical_no_interim_treatment']['model'], CLIN['clinical_no_interim_treatment']['crude_same_men'],
                  'Clinical model, interim treatment excluded'),
                 (None, CLIN['clinical']['crude_same_men'], 'Clinical covariates, inverse probability weighting'),
                 (CLIN['united_states']['model'], CLIN['united_states']['crude_same_men'], 'United States model')]
    if iw['n'] != CLIN['clinical']['model']['n'] or CLIN['clinical']['crude_same_men']['n'] != iw['n']:
        raise SystemExit('weighted and clinical populations differ')
    for m, c, lab in clin_cols:
        if m is not None and (m['n'] != c['n'] or m['events'] != c['one_events'] + c['two_events']):
            raise SystemExit(f'model and crude populations differ: {lab}')
    rowspec_c = [('Two or more pads vs one pad', 'two_or_more'),
                 ('Age, per 10 years from 65', 'age_per10_cent65'),
                 ('Three-month assessment day, per 30 days from day 90', 'early_day_per30_cent90'),
                 ("Bełchatów Hospital vs Brigham and Women's Hospital", 'centre_belchatow'),
                 ("SalveMedica vs Brigham and Women's Hospital", 'centre_salve'),
                 ('Operation in 2025' + DASH + '2026 vs earlier', 'period_recent'),
                 ('Nerve sparing not performed vs performed', 'nerve_sparing_not_performed'),
                 ('Nerve sparing not stated vs performed', 'nerve_sparing_not_stated'),
                 ('Pathological stage pT3' + DASH + '4 vs pT2', 'pt3_or_higher'),
                 ('Grade group 3' + DASH + '5 vs 1' + DASH + '2', 'isup_3_or_higher'),
                 ('Body mass index, per 5 kg/m² from 28', 'bmi_per5_cent28'),
                 ('Prostate volume, per 10 ml from 40', 'volume_per10_cent40'),
                 ('ASA class 3' + DASH + '4 vs 2', 'asa_3_or_4'),
                 ('Surgeon case number, per doubling from 32', 'surgeon_sequence_log2_cent32'),
                 ('Intercept (odds)', 'intercept')]
    rows_c = []
    for label, key in rowspec_c:
        rows_c.append([label] + [params(m, key, False) if m is not None and key in m['params'] else DASH
                                 for m, _, _ in clin_cols])
    rows_c.append(['Standardized or weighted pad freedom, one pad vs two or more'] +
                  [f"{pp(m['standardized_one_pad'])}% vs {pp(m['standardized_two_or_more'])}%" if m is not None
                   else f"{pp(iw['weighted_one_pad'])}% vs {pp(iw['weighted_two_or_more'])}%" for m, _, _ in clin_cols])
    rows_c.append(['Adjusted difference, percentage points (bootstrap 95% CI)'] +
                  [ci(m['standardized_difference'], m['bootstrap']['lower'], m['bootstrap']['upper']) if m is not None
                   else ci(iw['weighted_difference'], iw['bootstrap']['lower'], iw['bootstrap']['upper'])
                   for m, _, _ in clin_cols])
    rows_c.append(['Crude difference in the same men, percentage points (bootstrap 95% CI)'] +
                  [ci(c['difference'], c['bootstrap_lower'], c['bootstrap_upper']) for _, c, _ in clin_cols])
    rows_c.append(['Largest absolute standardized mean difference, before and after weighting'] +
                  [DASH if m is not None else f"{two_dec(iw['max_abs_smd_unweighted'])} and {two_dec(iw['max_abs_smd_weighted'])}"
                   for m, _, _ in clin_cols])
    rows_c.append(['Effective sample size, one pad and two or more; largest weight'] +
                  [DASH if m is not None else
                   f"{whole(iw['effective_sample_size']['one'])} and {whole(iw['effective_sample_size']['two_or_more'])}; {sig2(iw['max_weight'])}"
                   for m, _, _ in clin_cols])
    rows_c.append(['Bootstrap refits not converged, of 2000'] +
                  [str((m or iw)['bootstrap']['failed_fits']) for m, _, _ in clin_cols])
    rows_c.append(['Men (pad-free)'] + [f"{c['n']} ({c['one_events'] + c['two_events']})" for _, c, _ in clin_cols])
    part_c = table(['Term, odds ratio (95% CI)'] + [lab for _, _, lab in clin_cols], rows_c)
    return part_a, part_b, part_c


def sig1(v):
    d = Decimal(repr(float(v)))
    q = Decimal(1).scaleb(d.copy_abs().adjusted())
    return format(d.quantize(q, rounding=ROUND_HALF_UP), 'f')


def ptext(p):
    if p < 0.001:
        return 'p < 0.001'
    return f'p = {sig1(p) if p < 0.01 else sig2(p)}'


def num1(v):
    v = float(v)
    return whole(v) if v == int(v) else format(Decimal(repr(v)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP), 'f')


def wilson(x, n, z=1.959963984540054):
    p = x / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - h), min(1.0, c + h)


def s8():
    g = ST['gradient']
    if g['one']['n'] != 110 or g['one']['events'] != 58:
        raise SystemExit('gradient calibration')
    rows_a = []
    for key, label in (('pad_free_at_three_months', 'No pads (pad-free at three months)'), ('one', 'One pad'),
                       ('two', 'Exactly two pads'), ('three_or_more', 'Three or more pads'),
                       ('two_or_more_unseparated', 'Two or more pads, not separable into two or three or more')):
        c = g[key]
        lo, hi = wilson(c['events'], c['n'])
        rows_a.append([label, str(c['n']), f"{c['events']} ({pp(c['events'] / c['n'])}%; {pp(lo)}{DASH}{pp(hi)})"])
    for key, label in (('trend_pad_users_exact', 'Trend across one, two and three or more pads'),
                       ('trend_including_pad_free_at_three_months', 'Trend across no pads to three or more pads')):
        t = g[key]
        rows_a.append([label, DASH, f"z = {two_dec(t['z']).replace('-', MINUS)}; {ptext(t['p_two_sided'])}"])
    for key, label in (('trend_unseparated_as_two', 'exactly two pads'), ('trend_unseparated_as_three_or_more', 'three or more pads')):
        t = g[key]
        rows_a.append([f"Trend with the {g['two_or_more_unseparated']['n']} unseparated men counted as {label}", DASH,
                       f"z = {two_dec(t['z']).replace('-', MINUS)}; {ptext(t['p_two_sided'])}"])
    o = g['odds_ratio_per_pad_level']
    rows_a.append([f"Odds ratio for pad freedom per additional pad level ({o['n']} men)", DASH, orci(o['or'], *o['wald_ci'])])
    part_a = table(['Three-month pad count', 'Men with a one-year record', 'Pad-free at one year, n (%; 95% CI)'], rows_a)

    av = ST['record_availability']
    sb = av['status_by_record_availability']
    rows_b = []
    for gkey, glabel in (('one', 'One pad'), ('two_or_more', 'Two or more pads')):
        for rkey, rlabel in (('with_year_record', 'Yes'), ('without_year_record', 'No')):
            c = sb[f'{gkey}|{rkey}']
            rows_b.append([glabel, rlabel, str(c['n']), frac(c['six_month_pad_free'], c['six_month_record']),
                           frac(c['two_year_pad_free'], c['two_year_record'])])
    part_b = table(['Three-month pad group', 'One-year record', 'Men, window closed', 'Pad-free at six months, n/N (%)',
                    'Pad-free at two years, n/N (%)'], rows_b)

    b = ST['unclassified_bounds']
    ess = av['effective_sample_size']
    rows_c = [['Weighted for availability of a one-year record', f"{av['n']} men whose one-year window had closed",
               f"{pp(av['weighted_one_pad'])}% vs {pp(av['weighted_two_or_more'])}%",
               ci(av['weighted_difference'], av['bootstrap_lower'], av['bootstrap_upper']), DASH,
               f"Largest weight {sig2(av['max_weight'])}; effective sample sizes {whole(ess['one'])} and {whole(ess['two_or_more'])}; "
               f"{av['failed_fits']} of 2000 refits not converged"]]
    for key, label in (('all_assigned_one', 'Unclassifiable counts assigned to one pad'),
                       ('all_assigned_two_or_more', 'Unclassifiable counts assigned to two or more pads')):
        x = b[key]
        rows_c.append([label, f"{x['n']} men with a one-year record", f"{frac(x['one_events'], x['one_n'])} vs {frac(x['two_events'], x['two_n'])}",
                       ci(x['difference'], x['bootstrap_lower'], x['bootstrap_upper']), rng(x['newcombe_lower'], x['newcombe_upper']),
                       f"{b['unclassified_pad_free']} of {b['unclassified_n']} unclassifiable men pad-free"])
    od = ST['outcome_definitions']

    def crow(label, x, note):
        return [label, f"{x['n']} men", f"{frac(x['one_events'], x['one_n'])} vs {frac(x['two_events'], x['two_n'])}",
                ci(x['difference'], x['bootstrap_lower'], x['bootstrap_upper']), rng(x['newcombe_lower'], x['newcombe_upper']), note]

    wd = od['widened_one_year_window']
    rows_c.append(crow('One-year window extended to days 305' + DASH + '545', wd, f"{wd['added_men']} men added"))
    sc = od['social_continence_no_pads_or_at_most_one']
    rows_c.append(crow('Social continence at one year (no pads or at most one pad per day)', sc,
                       f"{sc['excluded_pad_users_without_a_valid_count']} pad users without a valid count excluded"))
    for key, label in (('without_belchatow', 'Bełchatów Hospital left out'), ('without_salve_medica', 'SalveMedica left out'),
                       ('without_brigham', "Brigham and Women's Hospital left out (Poland only)")):
        rows_c.append(crow(label, ST['country_heterogeneity']['leave_one_centre_out'][key], DASH))
    fz = ST['clinical_model_checks']['firth']
    rows_c.append(['Clinical model, Firth-penalized', f"{ST['prognostic_value']['n']} men with complete data",
                   f"{pp(fz['standardized_one_pad'])}% vs {pp(fz['standardized_two_or_more'])}%",
                   ci(fz['standardized_difference'], fz['bootstrap_lower'], fz['bootstrap_upper']), DASH,
                   f"Odds ratio {two_dec(fz['odds_ratio_two_or_more'])}; {fz['failed_fits']} of 2000 refits not converged"])
    part_c = table(['Analysis', 'Men', 'Pad-free, one pad vs two or more', 'Difference (bootstrap 95% CI)', 'Newcombe 95% CI',
                    'Notes'], rows_c)

    e = ST['epic_agreement']

    def med(m):
        return f"{m['n']}; {num1(m['median'])} ({num1(m['q1'])}{DASH}{num1(m['q3'])})"

    rows_d = []
    for key, label, ga, gb in (('three_month_score_one_vs_two_or_more', 'Three months', 'One pad', 'Two or more pads'),
                               ('twelve_month_score_pad_free_vs_pad_use', 'Twelve months', 'Pad-free at one year', 'Using pads at one year'),
                               ('preoperative_score_one_vs_two_or_more', 'Before surgery', 'One pad', 'Two or more pads')):
        x = e[key]
        rows_d.append([label, f"{ga}: {med(x['group_a'])}", f"{gb}: {med(x['group_b'])}", ptext(x['mann_whitney_p'])])
    part_d = table(['EPIC-CP score', 'Group: men; median (IQR)', 'Comparison group: men; median (IQR)', 'Mann' + DASH + 'Whitney test'], rows_d)

    rr = ST['risk_ratio']
    h = ST['country_heterogeneity']
    pv = ST['prognostic_value']
    rows_e = [
        ['Risk ratio for pad freedom, one pad vs two or more',
         f"{two_dec(rr['estimate'])} (Katz 95% CI {two_dec(rr['katz_lower'])}{DASH}{two_dec(rr['katz_upper'])}; "
         f"bootstrap {two_dec(rr['bootstrap_lower'])}{DASH}{two_dec(rr['bootstrap_upper'])})"],
        ['Still using pads at one year',
         f"{frac(rr['persistent_pad_use_one']['n'], rr['persistent_pad_use_one']['of'])} one-pad users; "
         f"{frac(rr['persistent_pad_use_two_or_more']['n'], rr['persistent_pad_use_two_or_more']['of'])} two-or-more users"],
        ['Difference between country differences, Poland minus United States, percentage points',
         f"{pp(h['difference_poland_minus_united_states'])} (bootstrap 95% CI {rng(h['bootstrap_lower'], h['bootstrap_upper'])}); Wald {ptext(h['wald_p'])}"],
        ['Pad-group-by-country interaction in a logistic model',
         f"Odds ratio {two_dec(h['logistic_interaction_or'])}; likelihood-ratio {ptext(h['logistic_interaction_p'])}"],
        [f"Adding pad group to the clinical model ({pv['n']} men, {pv['events']} pad-free)",
         f"Likelihood-ratio chi-square {num1(round(pv['lr_chi2_adding_pad_group'], 1))}; {ptext(pv['lr_p'])}"],
        ['c statistic, clinical model without pad group',
         f"Apparent {two_dec(pv['c_apparent_without_pad_group'])}; optimism-corrected {two_dec(pv['c_corrected_without_pad_group'])}"],
        ['c statistic, clinical model with pad group',
         f"Apparent {two_dec(pv['c_apparent_with_pad_group'])}; optimism-corrected {two_dec(pv['c_corrected_with_pad_group'])}"],
        ['Gain in apparent c statistic from pad group',
         f"{two_dec(pv['c_apparent_with_pad_group'] - pv['c_apparent_without_pad_group'])} (bootstrap 95% CI "
         f"{two_dec(pv['gain_bootstrap_lower'])}{DASH}{two_dec(pv['gain_bootstrap_upper'])}; {pv['failed_draws']} of 2000 resamples without a converged fit)"],
        ['c statistic, pad group alone', two_dec(pv['c_pad_group_alone'])],
    ]
    cm = ST['clinical_model_checks']
    cl = rr['classification_of_persistent_pad_use_by_two_or_more']
    rows_e += [
        ['E-value for the crude risk ratio', f"{two_dec(rr['e_value'])} ({two_dec(rr['e_value_katz_lower_limit'])} for the lower confidence limit)"],
        [f"Risk ratio of standardized probabilities, clinical model ({pv['n']} men)",
         f"{two_dec(cm['standardized_risk_ratio'])} (bootstrap 95% CI {two_dec(cm['standardized_risk_ratio_bootstrap_lower'])}{DASH}"
         f"{two_dec(cm['standardized_risk_ratio_bootstrap_upper'])}); E-value {two_dec(cm['e_value'])} ({two_dec(cm['e_value_lower_limit'])} for the lower confidence limit)"],
        ['Two or more pads as a marker of pad use at one year',
         f"Sensitivity {pp(cl['sensitivity'])}%; specificity {pp(cl['specificity'])}%; positive predictive value {pp(cl['positive_predictive_value'])}%; "
         f"negative predictive value {pp(cl['negative_predictive_value'])}%"],
        ['Calibration slope of the clinical model with pad group, optimism-corrected', two_dec(pv['calibration_slope_optimism_corrected'])],
        [f"Equal and opposite shift in pad freedom among unobserved men that brings the completed difference to zero ({av['n']} men, window closed)",
         f"{pp(av['tipping_shift_point_estimate'])} points for the estimate; {pp(av['tipping_shift_lower_confidence_limit'])} points for the lower 95% confidence limit"],
    ]
    part_e = table(['Analysis', 'Result'], rows_e)
    return part_a, part_b, part_c, part_d, part_e


def main():
    text = TEMPLATE.read_text()
    s2a, s2b = s2()
    s3a, s3b = s3()
    s6a, s6b = s6()
    s7a, s7b, s7c = s7()
    s8a, s8b, s8c, s8d, s8e = s8()
    fills = {'S1A': s1a(), 'S1B': s1b(), 'S2A': s2a, 'S2B': s2b, 'S3A': s3a, 'S3B': s3b, 'S4': s4(), 'S5': s5(),
             'S6A': s6a, 'S6B': s6b, 'S7A': s7a, 'S7B': s7b, 'S7C': s7c,
             'S8A': s8a, 'S8B': s8b, 'S8C': s8c, 'S8D': s8d, 'S8E': s8e}
    for k, v in fills.items():
        token = '{{' + k + '}}'
        if token not in text:
            raise SystemExit(f'template lacks {token}')
        text = text.replace(token, v)
    left = re.findall(r'\{\{[A-Z0-9]+\}\}', text)
    if left:
        raise SystemExit(f'unfilled tokens {left}')
    OUT.write_text(text)
    print(f'written {OUT}')


if __name__ == '__main__':
    main()
