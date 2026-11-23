"""Assemble the Neurourology and Urodynamics submission files for manuscript 1.

Sources: the manager-written texts in this folder and the display outputs in
delegated_tasks/ms1-nau-rebase-20261121/displays_v8 and
the documentation record in evidence/. Output: build/ (Markdown, DOCX and PNG review copies)
and upload/ (the files for the journal portal). Run from any directory with the project Python.
"""
import json
import re
import shutil
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
M1 = HERE.parents[1]
DISP = M1.parent / 'delegated_tasks/ms1-nau-rebase-20261121/displays_v9'
DOC = json.loads((M1 / 'evidence/DOCUMENTATION_AND_TIMING_COMPLETED_WINDOW.json').read_text())
PADCAT = json.loads((M1 / 'evidence/ONE_YEAR_PAD_CATEGORY_COMPLETED_WINDOW.json').read_text())
BUILD = HERE / 'build'
UPLOAD = HERE / 'upload'
REF = M1 / 'submission/reference-style.docx'
REF_LANDSCAPE = M1 / 'submission/build/reference-landscape.docx'
PANDOC = shutil.which('pandoc')

# Display file number -> supplementary table number in order of first mention in the text.
RENUMBER = {'S1': 'S1', 'S2': 'S2', 'S3': 'S3', 'S4': 'S4', 'S6': 'S5', 'S7': 'S6', 'S8': 'S7', 'S9': 'S8', 'S5': 'S9'}
ORDER = ['S1', 'S2', 'S3', 'S4', 'S6', 'S7', 'S8', 'S9', 'S5']

FIG1 = ('Patient selection and pad use at one year by the daily pad count about three months after robot-assisted '
        'radical prostatectomy. (A) Selection from the database to the 189 men compared (shaded), with the number '
        'leaving at each step. (B) Pad use at one year by three-month pad count, as percentages of men with a '
        'one-year record. Segments show men who were pad-free, used pads but at most one per day, used more than one '
        'pad per day or used pads without a recorded count. The text column gives pad-free men over men with a '
        'one-year record. The 136 men pad-free at three months are not among the 189 men compared, and 80 of them '
        'had a one-year record. Eleven further men used two or more pads without a record separating two '
        'from three or more (1 pad-free, 9 at most one pad, 1 more than one pad). (C) Documented pad freedom at one year overall and by pad group '
        'within Poland and within the United States. Overall rows include men with unclear or conflicting counts. '
        '(D) One-pad-minus-two-or-more differences overall and within '
        'each country (heterogeneity p = 0.3). Three-month and one-year assessments were the records nearest '
        'postoperative days 90 and 365 within days 60–120 and 305–425. Proportions have Wilson score 95% confidence '
        'intervals, and differences have whole-patient percentile bootstrap 95% confidence intervals from 2000 '
        'resamples. Differences were computed from unrounded proportions and can differ by one point from the '
        'difference of the displayed percentages. CI = confidence interval. The dashed line marks no difference.')

FIG2 = ('Sensitivity analyses of the one-pad-minus-two-or-more difference in pad freedom at one year after '
        'robot-assisted radical prostatectomy. (A) Differences grouped by the source of error each analysis '
        'addresses. Assessment-selection rules repeat the whole selection, and the narrower rule used days 75–105 '
        'and 335–395. Measurement rows keep only exact counts, exclude counts from the Expanded Prostate Cancer '
        'Index Composite (EPIC) questionnaire, assign the 24 unclear or conflicting counts wholly to one group, or split them in the least favourable way '
        '(Newcombe interval). '
        'Follow-up rows add men whose one-year window had not ended but who already had a one-year record, keep operations '
        'in 2017–2024 or extend the one-year window to day 545. The row weighted for record availability weights men with '
        'a one-year record by the inverse probability of having one. Adjustment rows show standardized or weighted probabilities and the adjusted '
        'difference. Centre models include operative period (2024–2025 vs earlier). Clinical covariates (nerve '
        'sparing, pathological stage, grade group and body mass index) were added to the centre model among 171 men '
        'with complete data. The row weighted for pad group weights each of these men by the inverse probability of his '
        'own pad group, and the last row excludes men '
        'with a record of starting radiotherapy (RT) or androgen deprivation therapy (ADT) between the assessments. Text columns '
        'give pad-free men over group totals, or adjusted probabilities, with differences and whole-patient '
        'percentile bootstrap 95% confidence intervals from 2000 resamples. (B) Difference among all 189 one-pad '
        'and 137 two-or-more users under assumed pad freedom among the 85 and 52 men without a one-year record. '
        'Grey lines mark 10-point steps, the orange line marks no difference and the shaded area marks a reversed '
        'difference. The blue diamond assumes that unobserved men resemble observed men in their group. The open '
        'circle is the tipping point when both assumptions move by the same amount in opposite directions, and the '
        'dashed line joins these two points. The dotted diagonal assigns equal pad freedom to both unobserved '
        'groups. CI = confidence interval. The dashed line in A marks no difference.')

FIGS1 = ('Assessment windows and pad-count groups. Surgery is day 0. Blue bands show the three-month window (days '
         '60–120, nearest day 90) and the one-year window (days 305–425, nearest day 365). Grey bands show the '
         'six-month window (days 150–210, nearest day 180) and the two-year window (days 670–790, nearest day 730). '
         'The one-pad group required every record with a count to show exactly one ordinary pad per day, and the '
         'two-or-more group at least two. Counts were unclear when all records lacked a count or a range spanned one and two pads, and '
         'incompatible or invalid records were conflicting. The one-year outcome was an explicit record of no pad '
         'use. The schematic shows definitions only and no patient data.')


def labels(text):
    """Supporting-information labels of the journal (Appendix S1, Figure S1, Table S1)."""
    for old, new in (('Supplementary Tables S', 'Tables S'), ('Supplementary Table S', 'Table S'),
                     ('Supplementary Figure S1', 'Figure S1'), ('SM Methods S1', 'Appendix S1'),
                     ('Supplementary Methods S1', 'Appendix S1'), ('the Supplementary Methods', 'Appendix S1'),
                     ('# Supplementary material', '# Supporting information'),
                     ('the Supplementary material (SM)', 'the supporting information (SM)')):
        text = text.replace(old, new)
    if 'Supplementary T' in text or 'Supplementary F' in text or 'Supplementary M' in text:
        sys.exit('LABELS_INCOMPLETE')
    return text


def must_replace(text, old, new, count=1):
    if text.count(old) != count:
        sys.exit(f'REPLACE_COUNT {text.count(old)} != {count}: {old[:70]!r}')
    return text.replace(old, new)


def pct(n, total):
    """Percentage in the style of the display tables: integers from 10%, two significant figures below."""
    if n == 0:
        return '0%'
    v = Decimal(100 * n) / Decimal(total)
    places = '1' if v >= Decimal('9.95') else ('0.1' if v >= Decimal('0.995') else '0.01')
    return f'{v.quantize(Decimal(places), rounding=ROUND_HALF_UP)}%'


def num(v):
    """Percentage-point value in the style of the display tables, with a true minus sign."""
    a = abs(v)
    t = f'{a:.0f}' if a >= 9.95 else f'{a:.1f}'
    return ('−' if v < 0 else '') + t


def set_widths(text, header_start, widths):
    """Give the pipe table whose header row starts with `header_start` relative column widths."""
    lines = text.split('\n')
    hits = [i for i, line in enumerate(lines) if line.startswith(header_start)]
    if len(hits) != 1 or not lines[hits[0] + 1].startswith('| ---'):
        sys.exit(f'WIDTH_TARGET {header_start!r}: {len(hits)}')
    if len(widths) != lines[hits[0]].count('|') - 1:
        sys.exit(f'WIDTH_COUNT {header_start!r}')
    lines[hits[0] + 1] = '| ' + ' | '.join('-' * w for w in widths) + ' |'
    return '\n'.join(lines)


CENTRE_LABELS = (('Bełchatów', 'Centre A (Poland)'), ('Salve Medica', 'Centre B (Poland)'),
                 ("Brigham and Women's Hospital", 'Centre C (United States)'))
DOC_COLUMNS = ('usable_pad_status', 'pad_status_recorded_not_usable', 'continence_record_without_pad_status',
               'record_at_other_time_only', 'no_dated_continence_record')


def documentation_part():
    """Supplementary Table S1 part C, written from the documentation record."""
    def row(label, block):
        cells = [f"{block[c]} ({pct(block[c], block['men'])})" for c in DOC_COLUMNS]
        return f"| {label} | {block['men']} | " + ' | '.join(cells) + ' |'

    out = ['#### C. What the records held in each assessment window', '',
           '| Window and group | Men | Usable pad status | Pad status recorded in the window, no usable assessment selected | Record in the window without pad status | Valid observations only outside the window | No record in the window and no valid observation elsewhere |',
           '| ---------------------- | ------ | ---------- | ---------- | ---------- | ---------- | ---------- |']
    for title, key in (('**Three-month window (days 60–120), all men of the study cohort**',
                        'documentation_three_month_window_all_men'),
                       ('**One-year window (days 305–425), men using pads at three months**',
                        'documentation_one_year_window_men_using_pads_at_three_months')):
        block = DOC[key]
        out.append(f'| {title} |  |  |  |  |  |  |')
        out.append(row('All', block['all']))
        out.append(row('Poland', block['by_country']['Poland']))
        for source, label in CENTRE_LABELS[:2]:
            out.append(row(label, block['by_centre'][source]))
        out.append(row('Centre C (United States)', block['by_centre'][CENTRE_LABELS[2][0]]))
        if block['by_centre'][CENTRE_LABELS[2][0]] != block['by_country']['United States']:
            sys.exit('DOC_COUNTRY_CENTRE')
    three = DOC['documentation_three_month_window_all_men']['all']
    extra = three['without_valid_dated_record_at_any_time']
    if any(extra[c] for c in DOC_COLUMNS[:2]) or extra['record_at_other_time_only']:
        sys.exit('DOC_NO_VALID_PATTERN')
    never = extra['continence_record_without_pad_status'] + extra['no_dated_continence_record']
    poland = DOC['documentation_three_month_window_all_men']['by_country']['Poland'][
        'without_valid_dated_record_at_any_time']
    never_poland = poland['continence_record_without_pad_status'] + poland['no_dated_continence_record']
    note = ('In part C, each man is counted once in each window, in the first column that applies from left to right. '
            'A record without pad status described continence without saying whether pads were used. A valid '
            'observation was a dated postoperative record marked in the database as a usable continence '
            f"observation. Of the men with a record without pad status in the three-month window, "
            f"{extra['continence_record_without_pad_status']} had no valid observation at any time. With the "
            f"{extra['no_dated_continence_record']} men of the last column they are the {never} men of part A "
            f'without a valid dated postoperative continence observation, of whom {never_poland} were treated in '
            'Poland.')
    return '\n'.join(out), note


def wilson_cell(b):
    """n/N (%; 95% CI) from a record cell, in the style of the display tables."""
    def lim(v):
        v = 100 * v
        if v == 0:
            return '0'
        return f'{v:.0f}' if v >= 9.95 else (f'{v:.1f}' if v >= 0.995 else f'{v:.2f}')
    return f"{b['n']}/{b['N']} ({pct(b['n'], b['N'])}; {lim(b['lower'])}–{lim(b['upper'])})"


def wilson_text(x, n):
    """n (%; Wilson score 95% CI) for a count, in the style of the display tables."""
    z = 1.959963984540054
    ph = x / n
    centre = (ph + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    def lim(v):
        v = 100 * max(0.0, min(1.0, v))
        if v < 0.005:
            return '0'
        return f'{v:.0f}' if v >= 9.95 else (f'{v:.1f}' if v >= 0.995 else f'{v:.2f}')
    return f'{x} ({pct(x, n)}; {lim(centre - half)}–{lim(centre + half)})'


def six_month_part():
    """Supplementary Table S2 part E, written from the documentation record."""
    s = DOC['one_year_pad_freedom_by_six_month_pad_count']
    if (s['men'], s['pad_free_at_one_year']) != (93, 27):
        sys.exit('SIX_MONTH_TOTALS')
    if sum(s[k]['N'] for k in ('one', 'two_or_more', 'unclear_or_conflicting')) != s['men'] or \
            sum(s[k]['n'] for k in ('one', 'two_or_more', 'unclear_or_conflicting')) != s['pad_free_at_one_year']:
        sys.exit('SIX_MONTH_SUM')
    diff = s['one_minus_two_or_more']
    use = s['one_year_pad_use_by_six_month_pad_count']
    out = ['#### E. One-year pad use by pad count at six months, men using pads at six months', '',
           '| Six-month pad count or comparison | Pad-free at one year, n/N (%; 95% CI) | More than one pad per day at '
           'one year, n/N (%; 95% CI) | Pads, count not recorded at one year, n |', '| --- | --- | --- | --- |']
    for key, label in (('one', 'One pad'), ('two_or_more', 'Two or more pads'),
                       ('unclear_or_conflicting', 'Unclear or conflicting count')):
        if use[key]['more_than_one_pad_per_day']['N'] != s[key]['N']:
            sys.exit('SIX_MONTH_USE_DENOMINATOR')
        out.append(f"| {label} at six months | {wilson_cell(s[key])} | "
                   f"{wilson_cell(use[key]['more_than_one_pad_per_day'])} | {use[key]['pads_count_not_recorded']} |")
    out.append('| One pad minus two or more pads at six months, percentage points (Newcombe 95% CI) | '
               f"{num(100 * diff['difference'])} ({num(100 * diff['newcombe_lower'])}–"
               f"{num(100 * diff['newcombe_upper'])}) | – | – |")
    note = (f"Part E divides the {s['men']} men of part D who used pads at six months by the pad count on the "
            'selected six-month day, classified by the rules used for the three-month count.')
    return '\n'.join(out), note


def heavier_missing_part():
    """Supplementary Table S2 part G: more than one pad per day at one year under other readings and with
    missing one-year records, written from the documentation record and the one-year pad category record."""
    h = DOC['more_than_one_pad_at_one_year_when_records_are_missing']
    strict = PADCAT['classification_rule_audit']['strict_rule_by_three_month_level']
    if (h['men'], h['men_with_one_year_record']) != (326, 189):
        sys.exit('HEAVIER_MISSING_TOTALS')

    def share(v):
        v = 100 * v
        if v == 0:
            return '0'
        return f'{v:.0f}' if v >= 9.95 else f'{v:.1f}'

    out = ['#### G. More than one pad per day at one year under other readings and with missing one-year records', '',
           '| Three-month pad count | Recorded, n/N (%; 95% CI) | Counting men with pads but no recorded count, n/N (%) | '
           'Every record at two or more pads, n/N (%) | Weighted for record availability, % (95% CI) | Men at three '
           'months, of whom without a one-year record | All men at three months if men without a record used more '
           'than one pad at half, the same or twice the recorded share |',
           '| --- | --- | --- | --- | --- | --- | --- |']
    for key, label in (('one', 'One pad'), ('two', 'Two pads'), ('three_or_more', 'Three or more pads')):
        b = h['by_three_month_level'][key]
        st = strict[key]
        if st['with_year_record'] != b['observed']['N'] or st['classified'] + st['not_classifiable'] != st['with_year_record']:
            sys.exit('HEAVIER_STRICT_DENOMINATOR')
        up = b['if_uncounted_men_used_more_than_one_pad']
        if up['n'] != b['observed']['n'] + b['pads_count_not_recorded']:
            sys.exit('HEAVIER_UNCOUNTED')
        w = b['weighted_for_record_availability']
        a = b['all_men_under_assumed_share_among_men_without_a_record']
        out.append(f"| {label} | {wilson_cell(b['observed'])} | {up['n']}/{up['N']} ({pct(up['n'], up['N'])}) | "
                   f"{st['two_or_more']}/{st['classified']} ({pct(st['two_or_more'], st['classified'])}) | "
                   f"{share(w['share'])} ({share(w['bootstrap_lower'])}–{share(w['bootstrap_upper'])}) | "
                   f"{b['men_at_three_months']}, {b['men_without_one_year_record']} | "
                   f"{share(a['half_the_observed_share']['share_of_all_men'])}%, "
                   f"{share(a['the_observed_share']['share_of_all_men'])}%, "
                   f"{share(a['twice_the_observed_share']['share_of_all_men'])}% |")
    d = h['weighted_three_or_more_minus_one']
    out.append('| Three or more pads minus one pad, weighted, percentage points (95% CI) | – | – | – | '
               f"{num(100 * d['difference'])} ({num(100 * d['bootstrap_lower'])}–{num(100 * d['bootstrap_upper'])}) | – | – |")
    note = ('Part G repeats the share of men using more than one pad per day at one year under other readings. The '
            'third column counts men who used pads without a recorded count as using more than one. The stricter '
            'reading counts a man only when every valid record showed two or more pads and leaves out men it cannot '
            'classify. Weights are the inverse probability of having a one-year record from the weighting model '
            f"described under Record availability in Supplementary Methods S1, with percentile intervals from {h['draws']} bootstrap resamples "
            f"({h['failed_fits']} refit did not converge). The last column applies an assumed share to the men "
            'without a one-year record and gives the share among all men who used that many pads at three months.')
    return '\n'.join(out), note


def country_level_part():
    """Supplementary Table S2 part F, written from the documentation record."""
    block = DOC['pad_use_by_country_and_three_month_level']
    labels = (('one', 'one pad'), ('two', 'two pads'), ('three_or_more', 'three or more pads'),
              ('two_or_more_unseparated', 'two or more pads, not separable'))
    totals = {'one': [0, 0, 0], 'two': [0, 0, 0], 'three_or_more': [0, 0, 0], 'two_or_more_unseparated': [0, 0, 0]}
    out = ['#### F. Three-month pad count and one-year pad use by country', '',
           '| Country and three-month pad count | Men using pads at three months, n (% of pad users in the country) | '
           'Pad-free at one year, n/N (%; 95% CI) | More than one pad per day at one year, n/N (%; 95% CI) | Pads, '
           'count not recorded at one year, n |', '| --- | --- | --- | --- | --- |']
    for country in ('Poland', 'United States'):
        mix, outcome = block[country]['three_month_level_mix'], block[country]['one_year_by_three_month_level']
        men = mix['men_using_pads_at_three_months']
        for key, label in labels:
            o = outcome[key]
            for i, v in enumerate((o['pad_free']['N'], o['pad_free']['n'], o['more_than_one_pad_per_day']['n'])):
                totals[key][i] += v
            out.append(f"| {country}, {label} | {mix[key]} ({pct(mix[key], men)}) | {wilson_cell(o['pad_free'])} | "
                       f"{wilson_cell(o['more_than_one_pad_per_day'])} | {o['pads_count_not_recorded']} |")
        other = mix['unclear_or_conflicting']
        out.append(f'| {country}, unclear or conflicting count | {other} ({pct(other, men)}) | – | – | – |')
    if (totals['one'], totals['two'], totals['three_or_more'], totals['two_or_more_unseparated']) != \
            ([104, 54, 3], [36, 15, 4], [38, 8, 13], [11, 1, 1]):
        sys.exit(f'COUNTRY_LEVEL_TOTALS {totals}')
    if [block[c]['three_month_level_mix']['men_using_pads_at_three_months'] for c in ('Poland', 'United States')] != \
            [155, 209]:
        sys.exit('COUNTRY_LEVEL_MEN')
    note = ('Part F gives, for each country, the share of men using pads at three months at each pad count and the '
            'one-year results of those with a one-year record. Outcome denominators are men with a one-year record. '
            'One-year pad freedom of men with unclear or conflicting counts is in Supplementary Table S4.')
    return '\n'.join(out), note


def country_main_table():
    """Main Table 2: one-year pad use by three-month pad count, pooled and by country, from the documentation record."""
    block = DOC['pad_use_by_country_and_three_month_level']
    levels = (('one', 'One pad'), ('two', 'Two pads'), ('three_or_more', 'Three or more pads'))

    def cells(country):
        out = {}
        for key, _ in levels:
            o = block[country]['one_year_by_three_month_level'][key]
            n, free, heavy, blank = (o['pad_free']['N'], o['pad_free']['n'], o['more_than_one_pad_per_day']['n'],
                                     o['pads_count_not_recorded'])
            if o['more_than_one_pad_per_day']['N'] != n:
                sys.exit('TABLE2_DENOMINATOR')
            out[key] = (n, free, n - heavy - blank, heavy, blank)
        return out

    poland, usa = cells('Poland'), cells('United States')
    pooled = {key: tuple(a + b for a, b in zip(poland[key], usa[key])) for key, _ in levels}
    if pooled != {'one': (104, 54, 99, 3, 2), 'two': (36, 15, 32, 4, 0), 'three_or_more': (38, 8, 24, 13, 1)}:
        sys.exit(f'TABLE2_POOLED {pooled}')
    out = ['### Table 2', '',
           'Pad use at one year by daily pad count about three months after robot-assisted radical prostatectomy, in '
           'both countries together and in each country, among men with a one-year pad-status record.', '',
           '| Three-month pad count | Men with a one-year record | Pad-free, n (%; 95% CI) | Pad-free or at most one pad per '
           'day, n (%) | More than one pad per day, n (%; 95% CI) |',
           '| ---------------------- | ------------ | ------------ | ---------------- | ------------ |']
    for title, group in (('**Both countries**', pooled), ('**Poland**', poland), ('**United States**', usa)):
        out.append(f'| {title} |  |  |  |  |')
        for key, label in levels:
            n, free, social, heavy, _ = group[key]
            out.append(f'| {label} | {n} | {wilson_text(free, n)} | {social} ({pct(social, n)}) | '
                       f'{wilson_text(heavy, n)} |')
            o = block[title.strip('*')]['one_year_by_three_month_level'][key] if title != '**Both countries**' else None
            if o is not None and wilson_cell(o['pad_free']).split('/')[0] + ' (' + wilson_cell(o['pad_free']).split(' (', 1)[1] != wilson_text(free, n):
                sys.exit('TABLE2_WILSON_DISAGREES_WITH_RECORD')
    def p_value(country):
        trend = block[country]['pad_freedom_trend_one_two_three_or_more']
        if not trend['estimable']:
            sys.exit('TABLE2_TREND')
        p = trend['p_two_sided']
        return '< 0.001' if p < 0.001 else (f'= {p:.3f}' if p < 0.01 else f'= {p:.2f}')

    # The journal's statistics guideline (rule 3.7) asks for estimates without P values within subgroups.
    trend_note = ''
    blanks = [pooled[key][4] for key, _ in levels]
    if blanks != [2, 0, 1]:
        sys.exit('TABLE2_BLANKS')
    out += ['', 'Pad counts are exactly one, exactly two, and three or more pads per day at three months. Percentages '
                'use the men with a one-year record in each row. Three men who used pads at one year without a recorded '
                'count (two after one pad and one after three or more pads) are in the denominators and in neither of '
                'the last two columns. Eleven men who used two or more pads without a record separating two from three '
                'or more are not shown. CI = confidence interval (Wilson score).' + trend_note]
    text = '\n'.join(out)
    for fig_value in ('54 (52%; 42–61)', '15 (42%; 27–58)', '8 (21%; 11–36)', '13 (34%; 21–50)'):
        if fig_value not in text:
            sys.exit(f'TABLE2_CI {fig_value}')
    return text


def wider_window_row():
    """One row for Supplementary Table S3 part C and its note, written from the documentation record."""
    w = DOC['pad_freedom_near_one_year_in_the_wider_window']
    a, b, diff = w['one'], w['two_or_more'], w['one_minus_two_or_more']
    if (a['men_using_pads_at_three_months'], b['men_using_pads_at_three_months']) != (189, 137):
        sys.exit('WIDER_GROUPS')
    if (a['by_day_of_record']['days_305_425']['n'], a['by_day_of_record']['days_305_425']['N'],
            b['by_day_of_record']['days_305_425']['n'], b['by_day_of_record']['days_305_425']['N']) != (54, 104, 24, 85):
        sys.exit('WIDER_MAIN')
    fa, fb = a['pad_free'], b['pad_free']
    lo, hi = w['window_days']
    added = fa['N'] + fb['N'] - 189

    def frac(block, key):
        c = block['by_day_of_record'][key]
        return f"{c['n']}/{c['N']}"

    row = (f"| One-year outcome from the record nearest day 365 within days {lo}–{hi} | {fa['N'] + fb['N']} men | "
           f"{fa['n']}/{fa['N']} ({pct(fa['n'], fa['N'])}) vs {fb['n']}/{fb['N']} ({pct(fb['n'], fb['N'])}) | "
           f"{num(100 * diff['difference'])} (–) | {num(100 * diff['newcombe_lower'])}–"
           f"{num(100 * diff['newcombe_upper'])} | {added} men added |")
    note = (f" The row using the record nearest day 365 within days {lo}–{hi} gives an outcome to "
            f"{fa['N'] + fb['N']} of the 326 one-pad and two-or-more users, with a Newcombe interval only. Among the "
            f"{added} men added, pad freedom was {frac(a, 'days_211_304')} after one pad and "
            f"{frac(b, 'days_211_304')} after two or more when the record fell on days 211–304, and "
            f"{frac(a, 'days_426_669')} and {frac(b, 'days_426_669')} when it fell on days 426–669.")
    return row, note


def extreme_rows():
    """Two rows for Supplementary Table S3 part C, written from the documentation record."""
    e = DOC['extreme_allocation_of_unclassifiable_counts']
    users, free = e['unclassifiable_men'] - e['unclassifiable_pad_free'], e['unclassifiable_pad_free']
    rows = []
    for key, label, note in (
            ('pad_users_to_one_pad_and_pad_free_to_two_or_more', 'lowest possible difference',
             f'{users} pad users to one pad; {free} pad-free men to two or more'),
            ('pad_free_to_one_pad_and_pad_users_to_two_or_more', 'highest possible difference',
             f'{free} pad-free men to one pad; {users} pad users to two or more')):
        b = e[key]
        a, c = b['group_a'], b['group_b']
        lo, hi = 100 * b['newcombe_lower'], 100 * b['newcombe_upper']
        interval = f'{num(lo)} to {num(hi)}' if lo < 0 else f'{num(lo)}–{num(hi)}'
        rows.append(f"| Unclassifiable counts assigned by one-year outcome, {label} | {a['N'] + c['N']} men | "
                    f"{a['n']}/{a['N']} ({pct(a['n'], a['N'])}) vs {c['n']}/{c['N']} ({pct(c['n'], c['N'])}) | "
                    f"{num(100 * b['difference'])} (–) | {interval} | {note} |")
    return '\n'.join(rows)


def timing_part():
    """Supplementary Table S3 part F, written from the documentation record."""
    t = DOC['pad_freedom_at_one_year_by_three_month_assessment_day']

    def cell(b):
        return f"{b['n']}/{b['N']} ({pct(b['n'], b['N'])}; {100 * b['lower']:.0f}–{100 * b['upper']:.0f})"

    out = ['#### F. Pad freedom at one year by day of the three-month assessment', '',
           '| Three-month assessment day | One pad, n/N (%; 95% CI) | Two or more pads, n/N (%; 95% CI) | Both groups, '
           'n/N (%; 95% CI) |', '| --- | --- | --- | --- |']
    for key, label in (('days_60_89', 'Days 60–89'), ('days_90_120', 'Days 90–120')):
        out.append(f"| {label} | {cell(t[key]['one'])} | {cell(t[key]['two_or_more'])} | {cell(t[key]['both_groups'])} |")
    return '\n'.join(out)


def renumber(text):
    return re.sub(r'Supplementary Table (S\d)\b', lambda m: 'Supplementary Table ' + RENUMBER[m.group(1)], text)


def table_md(name):
    t = (DISP / 'tables' / f'{name}.md').read_text().strip()
    if name == 'Table1':
        t = must_replace(t, 'Year of surgery is grouped as 2017–2024 and 2025 because the aggregate source summary '
                            'does not separate 2017–2022, 2023, and 2024–2025.\n\n', '')
        t = must_replace(t, '| Telephone | 3 (2.9%) | 0 |', '| Telephone | 3 (2.9%) | 0 (0%) |')
        t = must_replace(t, '| Not established from the record | 65 (63%) | 62 (73%) |',
                         '| Not recorded | 65 (63%) | 62 (73%) |')
        t = must_replace(t, '"Not stated in the record" and "Not established from the record" mean that the record was '
                            'read but did not settle the item.',
                         '"Not stated in the record" means that the record was read but did not settle the item.')
        t = must_replace(t, '| Any complication within 30 days, n/N (%) | 39/95 (41%) | 25/72 (35%) |\n'
                            '| \u2003Not recorded, n | 9 | 13 |\n'
                            '| Any complication within 90 days, n/N (%) | 43/95 (45%) | 35/76 (46%) |\n'
                            '| \u2003Not recorded, n | 9 | 9 |\n', '')
        t = must_replace(t, 'Percentages use the column total, except complication percentages, which use men with a '
                            'recorded complication status (n/N). ',
                         'Percentages use the column total and are rounded, so they may not sum to 100%. ')
        t = must_replace(t, 'Prostate volume was recorded for',
                         'No man in the comparison was operated on before 2017.\n\n'
                         'Prostate volume was recorded for')
        t = must_replace(t, 'Preoperative PSA, ng/ml, median (IQR)', 'Preoperative PSA, ng/mL, median (IQR)')
        t = must_replace(t, 'Prostate volume, ml, median (IQR)', 'Prostate volume, mL, median (IQR)')
        t = set_widths(t, '| Characteristic | One pad per day', [46, 24, 24])
    if name == 'Table2':
        t = must_replace(t, 'between postoperative days 305–425', 'within postoperative days 305–425')
    return renumber(t)


def supp_table(key):
    t = (DISP / 'supplement' / f'{key}.md').read_text().strip()
    if key == 'S1':
        for year in ('2017', '2019', '2020', '2021', '2022'):
            t = re.sub(rf'\n\| {year} \| Not separately recorded .*', '', t)
        if 'Not separately recorded' in t:
            sys.exit('S1_EDIT_INCOMPLETE')
        t = must_replace(t, 'across 1022 robot-assisted procedures meeting follow-up eligibility',
                         'across the 1022 men of the study cohort')
        t = must_replace(t, ' Individual years 2017–2022 report total men using pads from the derivation summary; '
                            'one-year record splits for those single years are combined in the 2017–2022 row in '
                            'the aggregate sensitivity record.', '')
        part_c, note_c = documentation_part()
        t = must_replace(t, '| Any dated postoperative continence record |',
                         '| Any valid dated postoperative continence observation |')
        t = must_replace(t, '\n\nIQR = interquartile range. In part A,', '\n\n' + part_c +
                         '\n\nIQR = interquartile range. In part A,')
        t = t.rstrip() + '\n\n' + note_c
    if key == 'S2':
        t = must_replace(t, 'One-year pad categories follow the social-continence upper-bound rule: "Pad-free" = '
                            'explicit record of no pad use; "Using pads, at most one per day" = pad use with every valid count '
                            'or upper bound at most one pad; "More than one pad per day" = any valid count or upper '
                            'bound above one pad; "Pads, count not recorded" = pad use without a classifiable count.',
                         'One-year pad categories were defined as follows. Pad-free means an explicit record of no '
                         'pad use. Using pads, at most one per day means pad use with every valid count at most one pad. More '
                         'than one pad per day means pad use with any valid count above one pad. Pads, count not '
                         'recorded means pad use without a valid count.')
        t = must_replace(t, '162 had a six-month record (days 150–210; 31 pad-free and 131 using pads), and 120 had both '
                            'six-month and one-year records (27 pad-free and 93 using pads at six months).',
                         '162 had a six-month record (days 150–210; 31 pad-free and 131 using pads). Both six-month and '
                         'one-year records were available for 120 men (27 pad-free and 93 using pads at six months).')
        part_e, note_e = six_month_part()
        part_f, note_f = country_level_part()
        part_g, note_g = heavier_missing_part()
        t = must_replace(t, '\n\nCI = confidence interval. One-year pad categories',
                         '\n\n' + part_e + '\n\n' + part_f + '\n\n' + part_g + '\n\nCI = confidence interval. One-year pad categories')
        t = t.rstrip() + ' ' + note_e + ' ' + note_f + ' ' + note_g
    if key == 'S3':
        t = must_replace(t, '#### C. Weighted and bounded estimates',
                         '#### C. Weighted estimates, alternative assignments and other sensitivity analyses')
        t = must_replace(t, 'In part C, the unclassifiable counts are the unclear and conflicting counts,',
                         'In part C, the weighted analysis estimates the difference for the 326 one-pad and two-or-more '
                         'users from the 189 with a one-year record. The unclassifiable counts are the unclear and '
                         'conflicting counts,')
        t = must_replace(t, 'that brings the completed difference to zero (326 men)',
                         'that brings the difference for all 326 men to zero')
        anchor = [line for line in t.split('\n') if line.startswith('| Unclassifiable counts assigned to two or more pads |')]
        if len(anchor) != 1:
            sys.exit('S3_EXTREME_ANCHOR')
        wider_row, wider_note = wider_window_row()
        t = must_replace(t, anchor[0], anchor[0] + '\n' + extreme_rows() + '\n' + wider_row)
        t = must_replace(t, 'and differences are one pad minus two or more pads in percentage points.',
                         'and differences are one pad minus two or more pads in percentage points. The rows assigning '
                         'these counts by one-year outcome give the lowest and highest difference that any assignment '
                         'of the 24 men could produce, with Newcombe intervals only.' + wider_note)
        t = must_replace(t, '| c statistic, pad group alone | 0.61 |', '| c statistic, pad group alone (171 men) | 0.61 |')
        t = must_replace(t, '| Social continence at one year (no pads or at most one pad per day) |',
                         '| Pad-free or at most one pad per day at one year |')
        t = must_replace(t, 'Social continence counts men with no pads or with every valid count at most one pad per day,',
                         'The outcome of pad freedom or at most one pad per day counts men with no pads or with every '
                         'valid count at most one pad per day,')
        poland = [c for c in json.loads((DISP / 'data/plot_data.json').read_text())['contrasts'] if c['label'] == 'Poland']
        if len(poland) != 1 or poland[0]['text'] != '30 (12–49)':
            sys.exit('S3_POLAND_INTERVAL')
        t = must_replace(t, '| Centre C (United States) left out (Poland only) | 76 men | 16/39 (41%) vs 4/37 (11%) | 30 (12–48) |',
                         '| Centre C (United States) left out (Poland only) | 76 men | 16/39 (41%) vs 4/37 (11%) | '
                         + poland[0]['text'] + ' |')
        t = must_replace(t, 'Odds ratio 0.36; 0 of 2000 refits not converged',
                         'Odds ratio for pad freedom, two or more pads vs one pad, 0.36; 0 of 2000 refits not converged')
        t = must_replace(t, '\n\nCI = confidence interval; IQR = interquartile range;',
                         '\n\n' + timing_part() + '\n\nCI = confidence interval; IQR = interquartile range;')
        t = must_replace(t, 'and higher scores indicate worse incontinence.',
                         'and higher scores indicate worse incontinence. The score includes an item on pads per day.')
        t = t.rstrip() + ('\n\nPart F divides the 189 men compared by the day of the selected three-month assessment. '
                          'The odds ratio for that day is in Supplementary Table S9.')
        t = set_widths(t, '| Analysis | Men | Pad-free, one pad vs two or more', [27, 12, 21, 15, 13, 22])
    if key == 'S4':
        t = must_replace(t, '| Three-month pad group | Six months (days 150–210) | One year (days 305–425) | Two years '
                            '(days 670–790) |',
                         '| Three-month pad group | Pad-free at six months (days 150–210), n/N (%; 95% CI) | Pad-free at '
                         'one year (days 305–425), n/N (%; 95% CI) | Pad-free at two years (days 670–790), n/N (%; 95% '
                         'CI) |')
    if key == 'S5':
        t = must_replace(t, '#### A. Influence of single patients and Monte Carlo variation',
                         '#### A. Influence of single patients')
        t = re.sub(r'\n\| Monte Carlo SD of the (lower|upper) 95% confidence limit, percentage points \|.*', '', t)
        t = re.sub(r'\n\| Men using pads with a recorded range on the three-month day \|.*', '', t)
        t = re.sub(r'\n\| Platform data-quality flag, all patients \|.*', '', t)
        t = must_replace(t, '4 (one pad 3; unclear or conflicting 1, subgroup and one-year outcome detail not reported)',
                         '4 (one pad 3, unclear or conflicting count 1)')
        t = must_replace(t, 'CI = confidence interval; SD = standard deviation; EPIC', 'CI = confidence interval; EPIC')
        t = must_replace(t, ' Across all early pad users, the derivation record notes 12 men with a crossing range on '
                            'the three-month day, 18 with category-stable numeric disagreements, and 1 with diaper '
                            'or safety-pad evidence without ordinary pad counts.', '')
        t = re.sub(r'\n\nMonte Carlo bootstrap SDs, overall recorded-range counts.*', '', t)
        if 'Not reported in source record' in t or 'Monte Carlo' in t:
            sys.exit('S5_EDIT_INCOMPLETE')
    if key == 'S9':
        t = must_replace(t, 'with whole-patient percentile bootstrap intervals from 2000 resamples and Newcombe hybrid '
                            'score intervals.',
                         'with whole-patient percentile bootstrap intervals from 2000 resamples and Newcombe hybrid '
                         'score intervals. Differences were computed from unrounded values. In part A, men with a '
                         'one-year record are all men using pads at three months in that analysis, including men '
                         'with unclear or conflicting counts, who stay in the bootstrap resampling.')
        t = must_replace(t, 'Later operations included shows results without the follow-up eligibility cutoff.',
                         'Later operations included adds men whose one-year window had not ended but who already had a '
                         'one-year record.')
        t = must_replace(t, '(2024–2025 vs earlier; recent period threshold 2024)', '(2024–2025 vs earlier)')
        t = t.rstrip() + (' Odds ratios for covariates describe men who all used pads at three months and come from '
                          'models with five to seven men in the less frequent outcome class per term. They are not '
                          'estimates of the effect of a covariate on continence.')
        t = must_replace(t, 'Prostate volume, per 10 ml from 40', 'Prostate volume, per 10 mL from 40')
    head, _, rest = t.partition('\n')
    m = re.match(r'^# Supplementary Table (S\d)\. (.*)$', head)
    if not m:
        sys.exit(f'TITLE_FORMAT {key}')
    return f'# Supplementary Table {RENUMBER[m.group(1)]}\n\n{m.group(2)}.\n' + renumber(rest)


def polish_docx(path, line_numbers=False, breaks_before=()):
    """Set page size, margins, page numbers and table pagination in a Word file written by pandoc."""
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches

    d = docx.Document(str(path))
    for sec in d.sections:
        if not (sec.page_width and sec.page_height and sec.page_width > sec.page_height):
            sec.page_width, sec.page_height = Inches(8.5), Inches(11)
        sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Inches(1)
        footer = sec.footer
        footer.is_linked_to_previous = False
        para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para._p.get_or_add_pPr().append(OxmlElement('w:suppressLineNumbers'))
        for kind, text in (('begin', None), (None, 'PAGE'), ('end', None)):
            run = para.add_run()
            if kind:
                fld = OxmlElement('w:fldChar')
                fld.set(qn('w:fldCharType'), kind)
            else:
                fld = OxmlElement('w:instrText')
                fld.set(qn('xml:space'), 'preserve')
                fld.text = text
            run._r.append(fld)
        if line_numbers:
            ln = OxmlElement('w:lnNumType')
            ln.set(qn('w:countBy'), '1')
            ln.set(qn('w:restart'), 'continuous')
            sec._sectPr.find(qn('w:pgMar')).addnext(ln)
    for table in d.tables:
        for i, row in enumerate(table.rows):
            tr_pr = row._tr.get_or_add_trPr()
            tr_pr.append(OxmlElement('w:cantSplit'))
            if i == 0:
                tr_pr.append(OxmlElement('w:tblHeader'))
    paragraphs = {p._p: p for p in d.paragraphs}
    for el in d.element.body:
        if el.tag != qn('w:tbl'):
            continue
        prev, steps = el.getprevious(), 0
        while prev is not None and prev in paragraphs and steps < 3 and len(paragraphs[prev].text) < 400:
            paragraphs[prev].paragraph_format.keep_with_next = True
            prev, steps = prev.getprevious(), steps + 1
    for p in d.paragraphs:
        if p.text.strip() in breaks_before:
            p.paragraph_format.page_break_before = True
        if p._p.findall('.//' + qn('w:drawing')):
            p.paragraph_format.keep_with_next = True
            nxt = p._p.getnext()
            if nxt is not None and nxt in paragraphs:
                paragraphs[nxt].paragraph_format.keep_together = True
    d.save(str(path))


def pandoc(src, dst, ref=REF):
    subprocess.run([PANDOC, str(src), '-o', str(dst), '--reference-doc', str(ref),
                    '--from', 'markdown+superscript+pipe_tables', '--resource-path', str(BUILD)], check=True)


def main():
    for d in (BUILD, UPLOAD):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    main_md = (HERE / 'main-document.md').read_text().rstrip()
    t1 = table_md('Table1')
    t2 = table_md('Table2')
    t1 = must_replace(t1, '**Table 1. Characteristics of men using one ordinary pad or two or more pads per day about '
                          'three months after robot-assisted radical prostatectomy, among 189 men with a one-year '
                          'pad-status record**',
                      '### Table 1\n\nCharacteristics of men using one pad or two or more pads per day about '
                      'three months after robot-assisted radical prostatectomy, among the 189 men with a classified '
                      'three-month count and a one-year pad-status record.')
    t2 = must_replace(t2, '**Table 2. Availability of a one-year pad-status record among men using pads about three '
                          'months after robot-assisted radical prostatectomy**',
                      '### Table 3\n\nAvailability of a one-year pad-status record among men using pads about three '
                      'months after robot-assisted radical prostatectomy.')
    full = (main_md + '\n\n## Figure legends\n\n### Figure 1\n\n' + FIG1 + '\n\n### Figure 2\n\n' + FIG2 +
            '\n\n## Tables\n\n' + t1 + '\n\n' + country_main_table() + '\n\n' + t2 + '\n')
    full = labels(full)
    (BUILD / 'Main_document.md').write_text(full)

    supp = (HERE / 'supplement-methods.md').read_text().rstrip()
    shutil.copy(DISP / 'figures/FigureS1.png', BUILD / 'FigureS1.png')
    supp += '\n\n# Supplementary Figure S1\n\n![](FigureS1.png){width=20cm}\n\n' + FIGS1
    for key in ORDER:
        supp += '\n\n' + supp_table(key)
    supp += '\n\n' + (HERE / 'supplement-s10.md').read_text().strip() + '\n'
    supp = labels(must_replace(supp, 'p = 0.31', 'p = 0.3'))
    (BUILD / 'Supplementary_material.md').write_text(supp)

    (BUILD / 'Title_page.md').write_text(labels((HERE / 'title-page.md').read_text()))
    (BUILD / 'Cover_letter.md').write_text(labels((HERE / 'cover-letter.md').read_text()))
    names = ['Main_document', 'Supplementary_material', 'Title_page', 'Cover_letter']
    if (HERE / 'reporting-checklist.md').exists():
        (BUILD / 'Reporting_checklist_STROBE_RECORD.md').write_text(labels((HERE / 'reporting-checklist.md').read_text()))
        names.append('Reporting_checklist_STROBE_RECORD')
    for name in names:
        wide = name in ('Supplementary_material', 'Reporting_checklist_STROBE_RECORD')
        pandoc(BUILD / f'{name}.md', BUILD / f'{name}.docx', REF_LANDSCAPE if wide else REF)
        breaks = {'Main_document': ('Figure legends', 'Tables', 'Table 2', 'Table 3'),
                  'Supplementary_material': ('Figure S1',) + tuple(
                      f'Table S{i}' for i in range(1, 11))}.get(name, ())
        polish_docx(BUILD / f'{name}.docx', line_numbers=(name == 'Main_document'), breaks_before=breaks)
        shutil.copy(BUILD / f'{name}.docx', UPLOAD / f'{name}.docx')
    for fig in ('Figure1', 'Figure2'):
        shutil.copy(DISP / 'figures' / f'{fig}.tiff', UPLOAD / f'{fig}.tiff')
        shutil.copy(DISP / 'figures' / f'{fig}.png', BUILD / f'{fig}.png')
        shutil.copy(DISP / 'figures' / f'{fig}.pdf', BUILD / f'{fig}.pdf')
    shutil.copy(DISP / 'figures/FigureS1.png', BUILD / 'FigureS1.png')

    body = full.split('## Introduction')[1].split('## Acknowledgements')[0]
    body = re.sub(r' \[[0-9,–S]+\]', '', body)
    abstract = full.split('## Abstract')[1].split('**Keywords')[0]
    abstract_words = re.sub(r'^#+ .*$', '', abstract, flags=re.M).split()
    refs = len(re.findall(r'^\d+\. ', full.split('## References')[1].split('## Figure legends')[0], flags=re.M))
    print({'main_text_words': len([w for w in body.split() if not w.startswith('#')]),
           'abstract_words': len(abstract_words), 'references': refs})


if __name__ == '__main__':
    main()
