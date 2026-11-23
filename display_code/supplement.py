"""Build Supplementary Tables S1-S9 (Markdown and CSV) from completed-window slots."""
from centre_labels import DEFAULT_MODE, centre_label
from extract_display_values import (
    Bound,
    DASH,
    MINUS,
    OY_CATEGORY_KEYS,
    OY_CATEGORY_LABELS,
    RULE_DEFS,
    TASK,
    build_all,
    cat,
)
from tables import bound_table_products

OUT_SUPP = TASK / 'supplement'


def _as_b(x: Bound | str) -> Bound:
    return x if isinstance(x, Bound) else cat(x)


def _npct(cnt_b: Bound, pct_b: Bound) -> Bound:
    if cnt_b.text == '0':
        return cnt_b
    return cat(cnt_b, ' (', pct_b, '%)')


def _mediqr(bdict: dict, prefix: str) -> Bound:
    return cat(bdict[f'{prefix}_median'], ' (', bdict[f'{prefix}_q1'], DASH, bdict[f'{prefix}_q3'], ')')


def _frac(n_b: Bound, d_b: Bound, pct_b: Bound) -> Bound:
    return cat(n_b, '/', d_b, ' (', pct_b, '%)')


def _merge_blocks(stem: str, title_b: Bound | str, blocks: list[tuple[Bound | str, list[Bound | str], list[tuple[str, list[Bound | str]]]]], notes_b: list[Bound | str]) -> dict[str, Bound]:
    """Assemble multi-part supplementary CSV and Markdown with full ledger bindings."""
    import csv as _csv
    import io as _io

    def csv_row_b(cells: list[Bound | str]) -> Bound:
        parts: list[Bound | str] = []
        for j, cell in enumerate(cells):
            c = _as_b(cell)
            if j > 0:
                parts.append(',')
            buf = _io.StringIO()
            _csv.writer(buf, lineterminator='').writerow([c.text])
            s = buf.getvalue()
            if s.startswith('"') and s.endswith('"'):
                parts.extend(['"', c, '"'])
            else:
                parts.append(c)
        parts.append('\n')
        return cat(*parts)

    csv_lines: list[Bound | str] = []
    md_parts: list[Bound | str] = ['# ', _as_b(title_b), '\n\n']

    for idx_b, (subhead, hdr, rows) in enumerate(blocks):
        sub_b = _as_b(subhead)
        if sub_b.text:
            md_parts.extend(['#### ', sub_b, '\n\n'])

        if len(blocks) > 1:
            csv_lines.append(csv_row_b(['Part'] + [_as_b(h) for h in hdr]))
        else:
            csv_lines.append(csv_row_b(hdr))

        part_tag = chr(ord('A') + idx_b)
        for kind, raw_cells in rows:
            if len(blocks) > 1:
                csv_lines.append(csv_row_b([part_tag] + raw_cells))
            else:
                csv_lines.append(csv_row_b(raw_cells))

        b_hdr = [_as_b(h) for h in hdr]
        md_parts.append('| ')
        for i, h in enumerate(b_hdr):
            if i > 0:
                md_parts.append(' | ')
            md_parts.append(h)
        md_parts.append(' |\n| ' + ' | '.join(['---'] * len(b_hdr)) + ' |\n')
        for kind, raw_cells in rows:
            bcells = [_as_b(c) for c in raw_cells]
            md_parts.append('| ')
            for i, c in enumerate(bcells):
                if i > 0:
                    md_parts.append(' | ')
                if kind == 'section' and i == 0 and c.text:
                    md_parts.extend(['**', c, '**'])
                else:
                    md_parts.append(c)
            md_parts.append(' |\n')
        md_parts.append('\n')

    for note in notes_b:
        md_parts.extend([_as_b(note), '\n\n'])

    return {
        f'supplement/{stem}.csv': cat(*csv_lines),
        f'supplement/{stem}.md': cat(*md_parts),
    }


def _s1(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s1']
    ca = centre_label('Bełchatów', mode)
    cb = centre_label('Salve Medica', mode)
    cc = centre_label("Brigham and Women's Hospital", mode)

    hdr_a = [
        'Characteristic',
        cat('With a three-month assessment (n = ', s['with_early_assessment_n'], ')'),
        cat('Without a three-month assessment (n = ', s['without_early_assessment_n'], ')'),
    ]
    rows_a: list[tuple[str, list[Bound | str]]] = [('section', ['Country', '', ''])]
    for c in ('Poland', 'United States'):
        rows_a.append(('row', [c, _npct(s[f'with_early_assessment_country_{c}'], s[f'with_early_assessment_country_{c}_pct']),
                               _npct(s[f'without_early_assessment_country_{c}'], s[f'without_early_assessment_country_{c}_pct'])]))
    rows_a.append(('section', ['Centre', '', '']))
    for raw_k, disp in (('Bełchatów', ca), ('Salve Medica', cb), ("Brigham and Women's Hospital", cc)):
        rows_a.append(('row', [disp, _npct(s[f'with_early_assessment_centre_{raw_k}'], s[f'with_early_assessment_centre_{raw_k}_pct']),
                               _npct(s[f'without_early_assessment_centre_{raw_k}'], s[f'without_early_assessment_centre_{raw_k}_pct'])]))
    rows_a.append(('section', ['Year of surgery', '', '']))
    for lbl, pk in (
        (cat(m['yr_2014'], DASH, m['yr_2022']), '2014-2022'),
        (m['yr_2023'], '2023'),
        (m['yr_2024'], '2024'),
        (m['yr_2025'], '2025-2026'),
    ):
        rows_a.append(('row', [lbl, _npct(s[f'with_early_assessment_operative_period_{pk}'], s[f'with_early_assessment_operative_period_{pk}_pct']),
                               _npct(s[f'without_early_assessment_operative_period_{pk}'], s[f'without_early_assessment_operative_period_{pk}_pct'])]))
    rows_a.append(('row', ['Age, yr, median (IQR)', _mediqr(s, 'with_early_assessment_age'), _mediqr(s, 'without_early_assessment_age')]))
    for fld, lbl in (
        ('any_valid_dated_postoperative_continence_record', 'Any dated postoperative continence record'),
        ('no_dated_postoperative_contact', 'No last-contact date in the database follow-up field'),
    ):
        rows_a.append(('row', [lbl, _npct(s[f'with_early_assessment_{fld}'], s[f'with_early_assessment_{fld}_pct']),
                               _npct(s[f'without_early_assessment_{fld}'], s[f'without_early_assessment_{fld}_pct'])]))

    hdr_b = ['Year of surgery', 'With a one-year record', 'Without a one-year record', 'Men using pads', 'Availability']
    rows_b: list[tuple[str, list[Bound | str]]] = []
    for yk, ym in (('2017', 'yr_2017'), ('2019', 'yr_2019'), ('2020', 'yr_2020'), ('2021', 'yr_2021'), ('2022', 'yr_2022')):
        rows_b.append(('row', [m[ym], 'Not separately recorded', 'Not separately recorded', s[f's1b_yr_{yk}_tot'], 'Not separately recorded']))
    for lbl, pk in (
        (cat(m['yr_2017'], DASH, m['yr_2022']), 'period_2017-2022'),
        (m['yr_2023'], 'period_2023'),
        (m['yr_2024'], 'period_2024'),
        (m['yr_2025'], 'period_2025-2026'),
    ):
        rows_b.append(('row', [lbl, s[f's1b_{pk}_with'], s[f's1b_{pk}_without'], s[f's1b_{pk}_tot'], cat(s[f's1b_{pk}_pct'], '%')]))
    rows_b.append(('row', [cat(m['yr_2017'], DASH, m['yr_2024']), s['s1b_2017_2024_with'], s['s1b_2017_2024_without'], s['s1b_2017_2024_tot'], cat(s['s1b_2017_2024_pct'], '%')]))
    rows_b.append(('row', ['Total', s['s1b_total_with'], s['s1b_total_without'], s['s1b_total_tot'], cat(s['s1b_total_pct'], '%')]))

    notes = [
        cat(
            'IQR = interquartile range. In part A, percentages use the column total across ', s['total_1022'], ' robot-assisted procedures meeting follow-up eligibility. ',
            'Of the ', s['without_early_assessment_no_dated_postoperative_contact'], ' men without a three-month assessment and without a database last-contact date, ',
            s['no_contact_without_pl'], ' were treated in Poland and ', s['no_contact_without_us'], ' in the United States. ',
            'No last-contact date was present for ', s['no_contact_with_us'], ' men in the United States who had a three-month pad record.',
        ),
        cat(
            'In part B, availability is the percentage of men using pads at three months in that row who had a one-year record. ',
            'Individual years ', m['yr_2017'], DASH, m['yr_2022'], ' report total men using pads from the derivation summary; one-year record splits for those single years are combined in the ',
            m['yr_2017'], DASH, m['yr_2022'], ' row in the aggregate sensitivity record.',
        ),
    ]
    return _merge_blocks(
        'S1',
        'Supplementary Table S1. Selection before and after the three-month assessment',
        [
            ('A. Men treated with robot-assisted radical prostatectomy, with and without a three-month pad-status assessment', hdr_a, rows_a),
            ('B. Availability of a one-year record by year of surgery among men using pads at three months', hdr_b, rows_b),
        ],
        notes,
    )


def _s2(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s2']
    t1 = refs['t1']
    t2 = refs['t2']
    row_labels_a = [
        ('pad_free_at_three_months', 'No pads (pad-free at three months)'),
        ('one', 'One pad'),
        ('two', 'Two pads'),
        ('three_or_more', 'Three or more pads'),
        ('two_or_more_unseparated', 'Two or more pads, not separable'),
        ('nonconflicting_quantity_uncertain', 'Unclear count'),
        ('unresolved_quantity_evidence', 'Conflicting count'),
        ('two_or_more_all', 'Two or more pads, all'),
        ('all_pad_users', 'All men using pads'),
    ]
    hdr_a = ['Three-month pad group', 'Men with a one-year record'] + [
        cat(OY_CATEGORY_LABELS[ck], ', n/N (%; ', m['confidence'], '% CI)') for ck in OY_CATEGORY_KEYS
    ]
    rows_a = [
        ('row', [lbl, s['A'][rk]['N']] + [s['A'][rk]['cols'][ck] for ck in OY_CATEGORY_KEYS])
        for rk, lbl in row_labels_a
    ]

    hdr_b = ['Three-month pad group or comparison', cat('Result (', m['confidence'], '% CI)'), 'Pads, count not recorded at one year']
    rows_b: list[tuple[str, list[Bound | str]]] = [
        ('row', ['One pad', s['B']['row_one']['cell'], s['B']['row_one']['excluded']]),
        ('row', ['Two pads', s['B']['row_two']['cell'], s['B']['row_two']['excluded']]),
        ('row', ['Three or more pads', s['B']['row_three_or_more']['cell'], s['B']['row_three_or_more']['excluded']]),
        ('row', ['Two or more pads, all', s['B']['row_two_or_more_all']['cell'], s['B']['row_two_or_more_all']['excluded']]),
        ('row', ['All two or more pads minus one pad, percentage points (bootstrap; Newcombe)', cat(s['B']['diff_two_or_more_all_minus_one']['boot'], '; Newcombe ', s['B']['diff_two_or_more_all_minus_one']['newcombe']), DASH]),
        ('row', ['Three or more pads minus one pad, percentage points (bootstrap; Newcombe)', cat(s['B']['diff_three_or_more_minus_one']['boot'], '; Newcombe ', s['B']['diff_three_or_more_minus_one']['newcombe']), DASH]),
        ('row', ['Cochran–Armitage trend across one, two, and three or more pads', s['B']['trend_cochran_armitage_one_two_three_or_more'], DASH]),
        ('row', ['Trend sensitivity counting unseparated men as two pads', s['B']['trend_sensitivity_unseparated_as_two'], DASH]),
        ('row', ['Trend sensitivity counting unseparated men as three or more pads', s['B']['trend_sensitivity_unseparated_as_three_or_more'], DASH]),
    ]

    hdr_c = ['Country and three-month pad group', 'Men with a one-year record'] + [
        cat(OY_CATEGORY_LABELS[ck], ', n/N (%; ', m['confidence'], '% CI)') for ck in OY_CATEGORY_KEYS
    ]
    rows_c: list[tuple[str, list[Bound | str]]] = []
    for country in ('Poland', 'United States'):
        for rk, rlbl in (('pad_free_at_three_months', 'No pads (pad-free at three months)'), ('one', 'One pad'), ('two_or_more_all', 'Two or more pads, all')):
            rows_c.append(('row', [f'{country}, {rlbl.lower()}', s['C'][country][rk]['N']] + [s['C'][country][rk]['cols'][ck] for ck in OY_CATEGORY_KEYS]))

    hdr_d = ['Six-month pad status and three-month pad group', cat('Pad-free at one year, n/N (%; ', m['confidence'], '% CI)')]
    rows_d: list[tuple[str, list[Bound | str]]] = [
        ('section', ['Pad-free at six months', '']),
        ('row', ['One pad at three months', s['D']['six_month_pad_free_with_year_record']['one']]),
        ('row', ['Two or more pads at three months', s['D']['six_month_pad_free_with_year_record']['two_or_more']]),
        ('row', ['Unclear or conflicting count at three months', s['D']['six_month_pad_free_with_year_record']['other_uncertain_or_unresolved']]),
        ('row', ['All men using pads at three months', s['D']['six_month_pad_free_with_year_record']['overall']]),
        ('section', ['Using pads at six months', '']),
        ('row', ['One pad at three months', s['D']['six_month_pad_use_with_year_record']['one']]),
        ('row', ['Two or more pads at three months', s['D']['six_month_pad_use_with_year_record']['two_or_more']]),
        ('row', ['Unclear or conflicting count at three months', s['D']['six_month_pad_use_with_year_record']['other_uncertain_or_unresolved']]),
        ('row', ['All men using pads at three months', s['D']['six_month_pad_use_with_year_record']['overall']]),
    ]

    ac = s['D_acct']
    notes = [
        cat(
            'CI = confidence interval. One-year pad categories follow the social-continence upper-bound rule: ',
            '"Pad-free" = explicit record of no pad use; ',
            '"Using pads, at most one per day" = pad use with every valid count or upper bound at most one pad; ',
            '"More than one pad per day" = any valid count or upper bound above one pad; ',
            '"Pads, count not recorded" = pad use without a classifiable count. ',
            'Proportions use Wilson score ', m['confidence'], '% confidence intervals.',
        ),
        cat(
            'Part B restricts to men with a classifiable one-year pad category ("Pad-free", "Using pads, at most one per day", or "More than one pad per day"). ',
            'Part C shows countries separately; no men had unknown or other country. ',
            'In part D, among ', ac['early_users'], ' men using pads at three months, ', ac['early_users_with_six_month_record'],
            ' had a six-month record (days ', m['six_0'], DASH, m['six_1'], '; ', ac['early_users_six_month_pad_free'],
            ' pad-free and ', ac['early_users_six_month_pad_use'], ' using pads), and ', ac['early_users_with_six_and_year_record'],
            ' had both six-month and one-year records (', ac['six_month_pad_free_with_year_record'], ' pad-free and ',
            ac['six_month_pad_use_with_year_record'], ' using pads at six months).',
        ),
    ]
    return _merge_blocks(
        'S2',
        'Supplementary Table S2. Pad use at one year by daily pad count at three months',
        [
            ('A. One-year pad-use category by three-month pad count', hdr_a, rows_a),
            ('B. More than one pad per day at one year among men with a classifiable one-year count', hdr_b, rows_b),
            ('C. One-year pad-use category by country', hdr_c, rows_c),
            ('D. One-year pad freedom by six-month and three-month status', hdr_d, rows_d),
        ],
        notes,
    )


def _s3(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s3']
    ca = centre_label('Bełchatów', mode)
    cb = centre_label('Salve Medica', mode)
    cc = centre_label("Brigham and Women's Hospital", mode)

    sa = s['A']
    hdr_a = ['Three-month pad count', 'Men with a one-year record', cat('Pad-free at one year, n (%; ', m['confidence'], '% CI)')]
    rows_a = [
        ('row', ['No pads (pad-free at three months)', sa['pad_free_at_three_months']['N'], sa['pad_free_at_three_months']['cell']]),
        ('row', ['One pad', sa['one']['N'], sa['one']['cell']]),
        ('row', ['Two pads', sa['two']['N'], sa['two']['cell']]),
        ('row', ['Three or more pads', sa['three_or_more']['N'], sa['three_or_more']['cell']]),
        ('row', ['Two or more pads, not separable into two or three or more', sa['two_or_more_unseparated']['N'], sa['two_or_more_unseparated']['cell']]),
        ('row', ['Trend across one, two, and three or more pads', DASH, sa['trend_pad_users_exact']]),
        ('row', ['Trend across no pads to three or more pads', DASH, sa['trend_including_pad_free_at_three_months']]),
        ('row', [cat('Trend with the ', sa['two_or_more_unseparated']['N'], ' unseparated men counted as two pads'), DASH, sa['trend_unseparated_as_two']]),
        ('row', [cat('Trend with the ', sa['two_or_more_unseparated']['N'], ' unseparated men counted as three or more pads'), DASH, sa['trend_unseparated_as_three_or_more']]),
        ('row', [cat('Odds ratio for pad freedom per additional pad level (', sa['or_n'], ' men)'), DASH, sa['or_ci']]),
    ]

    sb = s['B']
    hdr_b = ['Three-month pad group', 'One-year record', 'Men', 'Pad-free at six months, n/N (%)', 'Pad-free at two years, n/N (%)']
    rows_b = [
        ('row', ['One pad', 'Yes', sb['one|with_year_record']['n'], sb['one|with_year_record']['6m'], sb['one|with_year_record']['2y']]),
        ('row', ['One pad', 'No', sb['one|without_year_record']['n'], sb['one|without_year_record']['6m'], sb['one|without_year_record']['2y']]),
        ('row', ['Two or more pads', 'Yes', sb['two_or_more|with_year_record']['n'], sb['two_or_more|with_year_record']['6m'], sb['two_or_more|with_year_record']['2y']]),
        ('row', ['Two or more pads', 'No', sb['two_or_more|without_year_record']['n'], sb['two_or_more|without_year_record']['6m'], sb['two_or_more|without_year_record']['2y']]),
    ]

    sc = s['C']
    av = sc['av']
    fz = sc['firth']
    hdr_c = ['Analysis', 'Men', 'Pad-free, one pad vs two or more', cat('Difference (bootstrap ', m['confidence'], '% CI)'), cat('Newcombe ', m['confidence'], '% CI'), 'Notes']
    rows_c = [
        ('row', [
            'Weighted for availability of a one-year record',
            cat(av['n'], ' men'), av['rates'], av['diff'], DASH,
            cat('Largest weight ', av['max_w'], '; effective sample sizes ', av['ess1'], ' and ', av['ess2'], '; ', av['failed'], ' of ', m['draws'], ' refits not converged'),
        ]),
        ('row', [
            'Unclassifiable counts assigned to one pad',
            cat(sc['all_assigned_one']['n'], ' men'), sc['all_assigned_one']['rates'], sc['all_assigned_one']['boot'], sc['all_assigned_one']['newc'],
            cat(sc['unclass_pf'], ' of ', sc['unclass_n'], ' unclassifiable men pad-free'),
        ]),
        ('row', [
            'Unclassifiable counts assigned to two or more pads',
            cat(sc['all_assigned_two_or_more']['n'], ' men'), sc['all_assigned_two_or_more']['rates'], sc['all_assigned_two_or_more']['boot'], sc['all_assigned_two_or_more']['newc'],
            cat(sc['unclass_pf'], ' of ', sc['unclass_n'], ' unclassifiable men pad-free'),
        ]),
        ('row', [
            cat('One-year window extended to days ', m['extended_0'], DASH, m['extended_1']),
            cat(sc['widened']['n'], ' men'), sc['widened']['rates'], sc['widened']['boot'], sc['widened']['newc'],
            cat(sc['widened_added'], ' men added'),
        ]),
        ('row', [
            'Social continence at one year (no pads or at most one pad per day)',
            cat(sc['social']['n'], ' men'), sc['social']['rates'], sc['social']['boot'], sc['social']['newc'],
            cat(sc['social_excl'], ' pad users without a valid count excluded'),
        ]),
        ('row', [cat(ca, ' left out'), cat(sc['without_belchatow']['n'], ' men'), sc['without_belchatow']['rates'], sc['without_belchatow']['boot'], sc['without_belchatow']['newc'], DASH]),
        ('row', [cat(cb, ' left out'), cat(sc['without_salve_medica']['n'], ' men'), sc['without_salve_medica']['rates'], sc['without_salve_medica']['boot'], sc['without_salve_medica']['newc'], DASH]),
        ('row', [cat(cc, ' left out (Poland only)'), cat(sc['without_brigham']['n'], ' men'), sc['without_brigham']['rates'], sc['without_brigham']['boot'], sc['without_brigham']['newc'], DASH]),
        ('row', [
            'Clinical model, Firth-penalized',
            cat(fz['n'], ' men with complete data'), fz['rates'], fz['boot'], DASH,
            cat('Odds ratio ', fz['or'], '; ', fz['failed'], ' of ', m['draws'], ' refits not converged'),
        ]),
    ]

    sd = s['D']
    hdr_d = ['EPIC-CP score', 'Group: men; median (IQR)', 'Comparison group: men; median (IQR)', 'Mann–Whitney test']
    rows_d = [
        ('row', ['Three months', cat('One pad: ', sd['three_month_score_one_vs_two_or_more']['group_a']), cat('Two or more pads: ', sd['three_month_score_one_vs_two_or_more']['group_b']), sd['three_month_score_one_vs_two_or_more']['p']]),
        ('row', ['Twelve months', cat('Pad-free at one year: ', sd['twelve_month_score_pad_free_vs_pad_use']['group_a']), cat('Using pads at one year: ', sd['twelve_month_score_pad_free_vs_pad_use']['group_b']), sd['twelve_month_score_pad_free_vs_pad_use']['p']]),
        ('row', ['Before surgery', cat('One pad: ', sd['preoperative_score_one_vs_two_or_more']['group_a']), cat('Two or more pads: ', sd['preoperative_score_one_vs_two_or_more']['group_b']), sd['preoperative_score_one_vs_two_or_more']['p']]),
    ]

    se = s['E']
    hdr_e = ['Analysis', 'Result']
    rows_e = [
        ('row', ['Risk ratio for pad freedom, one pad vs two or more', se['rr_ci']]),
        ('row', ['Still using pads at one year', se['persist']]),
        ('row', ['Difference between country differences, Poland minus United States, percentage points', se['het_diff']]),
        ('row', ['Pad-group-by-country interaction in a logistic model', se['het_int']]),
        ('row', [se['lr_hdr'], se['lr_val']]),
        ('row', ['c statistic, clinical model without pad group', se['c_without']]),
        ('row', ['c statistic, clinical model with pad group', se['c_with']]),
        ('row', ['Gain in apparent c statistic from pad group', se['c_gain']]),
        ('row', ['c statistic, pad group alone', se['c_alone']]),
        ('row', ['E-value for the crude risk ratio', se['e_crude']]),
        ('row', [se['rr_std_hdr'], se['rr_std_val']]),
        ('row', ['Two or more pads as a marker of pad use at one year', se['marker']]),
        ('row', ['Calibration slope of the clinical model with pad group, optimism-corrected', se['cal_slope']]),
        ('row', [se['tip_hdr'], se['tip_val']]),
    ]

    notes = [
        cat(
            'CI = confidence interval; IQR = interquartile range; EPIC = Expanded Prostate Cancer Index Composite; ',
            'EPIC-CP = EPIC for Clinical Practice. In part A, men pad-free at three months are shown for reference and are not part of the contrast. ',
            'Part B includes the one-pad and two-or-more users across six-month (days ', m['six_0'], DASH, m['six_1'], ') and two-year (days ', m['two_year_0'], DASH, m['two_year_1'], ') windows; each window has its own denominator.',
        ),
        cat(
            'In part C, the unclassifiable counts are the unclear and conflicting counts, and differences are one pad minus two or more pads in percentage points. ',
            'Social continence counts men with no pads or with every valid count at most one pad per day, and leaving out a centre removes its men from both groups. ',
            'Part D excludes men whose pad count came from the EPIC questionnaire; EPIC-CP scores range from ', m['epic_lo'], ' to ', m['epic_hi'], ', and higher scores indicate worse incontinence. ',
            'In part E, c statistics were corrected for optimism by bootstrap refitting, and a calibration slope below ', m['cal_slope_ideal'],
            ' means predicted probabilities were more extreme than observed outcomes. The E-value is the minimum risk ratio an unmeasured confounder would need with both exposure and outcome to explain away the observed risk ratio.',
        ),
    ]
    return _merge_blocks(
        'S3',
        'Supplementary Table S3. Additional analyses of the main comparison',
        [
            ('A. Pad freedom at one year by daily pad count at three months', hdr_a, rows_a),
            ('B. Six-month and two-year status of men with and without a one-year record', hdr_b, rows_b),
            ('C. Weighted and bounded estimates', hdr_c, rows_c),
            ('D. Agreement of pad records with EPIC-CP urinary incontinence scores', hdr_d, rows_d),
            ('E. Risk ratio, heterogeneity between countries, and prognostic value', hdr_e, rows_e),
        ],
        notes,
    )


def _s4(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s4']
    hdr_a = [
        'Three-month pad group',
        cat('Six months (days ', m['six_0'], DASH, m['six_1'], ')'),
        cat('One year (days ', m['year_0'], DASH, m['year_1'], ')'),
        cat('Two years (days ', m['two_year_0'], DASH, m['two_year_1'], ')'),
    ]
    row_order = [
        'All men using pads', 'One pad', 'Two or more pads', 'Unclear count', 'Conflicting count',
        'Poland', 'United States',
        'One pad, Poland', 'One pad, United States',
        'Two or more pads, Poland', 'Two or more pads, United States',
        'Unclear count, Poland', 'Unclear count, United States',
        'Conflicting count, Poland', 'Conflicting count, United States',
    ]
    rows_a = [('row', [rl, s['A'][rl]['six'], s['A'][rl]['year'], s['A'][rl]['two_year']]) for rl in row_order]

    hdr_b = ['Window', 'Pad-free at the later assessment among men pad-free at three months']
    rows_b = [
        ('row', ['Six months', s['B']['six']]),
        ('row', ['One year', s['B']['year']]),
        ('row', ['Two years', s['B']['two_year']]),
    ]
    notes = [
        cat(
            'Values are pad-free men over men with an assessment in that window (percentage; Wilson score ', m['confidence'], '% confidence interval). ',
            'Each window has its own denominator. "No men" marks country and group combinations without patients.',
        ),
    ]
    return _merge_blocks(
        'S4',
        'Supplementary Table S4. Documented pad freedom by three-month pad group and country at six months, one year, and two years',
        [
            ('A. Men using pads at three months', hdr_a, rows_a),
            ('B. Men pad-free at three months', hdr_b, rows_b),
        ],
        notes,
    )


def _s5(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s5']
    sa = s['A']
    sb = s['B']
    t1 = refs['t1']
    fig1_213 = refs['fig1_213']

    hdr_a = ['Check', 'Both countries', 'Poland', 'United States']
    rows_a = [
        ('row', ['Largest change in the difference after removing one patient, percentage points', sa['both']['max_change'], sa['Poland']['max_change'], sa['United States']['max_change']]),
        ('row', ['Sign changes after removing one patient', sa['both']['sign_changes'], sa['Poland']['sign_changes'], sa['United States']['sign_changes']]),
        ('row', [cat('Monte Carlo SD of the lower ', m['confidence'], '% confidence limit, percentage points'), 'Not reported in source record', 'Not reported in source record', 'Not reported in source record']),
        ('row', [cat('Monte Carlo SD of the upper ', m['confidence'], '% confidence limit, percentage points'), 'Not reported in source record', 'Not reported in source record', 'Not reported in source record']),
        ('row', ['Bootstrap resamples lacking a pad group', sa['both']['invalid_draws'], sa['Poland']['invalid_draws'], sa['United States']['invalid_draws']]),
    ]

    hdr_b = ['Recording check', 'Result']
    rows_b = [
        ('row', ['Men using pads with a recorded range on the three-month day', 'Not reported in source record']),
        ('row', ['Two-or-more classifications relying on a range, among men with a one-year record', sb['range_reliant_two']]),
        ('row', [cat('Diapers or safety pads recorded on the three-month day, among the ', t1['n_total'], ' men compared'), sb['device_189']]),
        ('row', [cat('Men with EPIC questionnaire pad counts, among the ', fig1_213, ' men with a one-year record'), sb['epic_pairs']]),
        ('row', ['Platform data-quality flag, all patients', 'Not reported in source record']),
        ('row', [
            'Platform data-quality flag, men with a one-year record',
            cat(sb['platform_pairs'], ' (one pad ', sb['platform_one_n'], '; unclear or conflicting ', sb['platform_noncontrast'], ', subgroup and one-year outcome detail not reported)'),
        ]),
        ('row', [cat('Difference after excluding flagged men, percentage points (', m['confidence'], '% CI)'), sb['platform_excl_ci']]),
    ]

    notes = [
        cat(
            'CI = confidence interval; SD = standard deviation; EPIC = Expanded Prostate Cancer Index Composite. ',
            'Patients with a platform data-quality flag had source records naming different surgical platforms. ',
            'Across all early pad users, the derivation record notes ', sb['crossing_ranges_note'],
            ' men with a crossing range on the three-month day, ', sb['disagreement_note'],
            ' with category-stable numeric disagreements, and ', sb['device_364_note'],
            ' with diaper or safety-pad evidence without ordinary pad counts.',
        ),
        'Monte Carlo bootstrap SDs, overall recorded-range counts across all early users, all-patient platform-flag counts, and the subgroup/pad-free split of the single non-contrast flagged man with a one-year record are not contained in the study summary records.',
    ]
    return _merge_blocks(
        'S5',
        'Supplementary Table S5. Diagnostics for the main comparison',
        [
            ('A. Influence of single patients and Monte Carlo variation', hdr_a, rows_a),
            ('B. Recording checks', hdr_b, rows_b),
        ],
        notes,
    )


def _s6(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s6']
    ca = centre_label('Bełchatów', mode)
    cb = centre_label('Salve Medica', mode)
    cc = centre_label("Brigham and Women's Hospital", mode)

    hdr = [
        cat('Characteristic (n = ', s['n'], ', ', s['events'], ' with a one-year record)'),
        cat('Odds ratio for a one-year record (', m['confidence'], '% CI)'),
    ]
    rows = [
        ('row', ['Two or more pads vs one pad', s['two_or_more']]),
        ('row', [cat('Age, per ', m['age_years'], ' years from ', m['age_center']), s['age_per10_cent65']]),
        ('row', [cat('Three-month assessment day, per ', m['day_step'], ' days from day ', m['early_target']), s['early_day_per30_cent90']]),
        ('row', [cat(ca, ' vs ', cc), s['centre_belchatow']]),
        ('row', [cat(cb, ' vs ', cc), s['centre_salve']]),
    ]
    notes = ['CI = confidence interval. The model describes which men had a one-year record. It does not adjust the main comparison.']
    return _merge_blocks(
        'S6',
        'Supplementary Table S6. Descriptive logistic model of the availability of a one-year record among men using one pad or two or more pads at three months',
        [('', hdr, rows)],
        notes,
    )


def _s7(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s7']
    hdr = ['Scenario', cat('Study cohort (one pad ', s['one_hdr'], ', two or more ', s['two_hdr'], ')')]
    rows = [
        ('row', ['One pad', s['one_desc']]),
        ('row', ['Two or more pads', s['two_desc']]),
        ('row', ['Difference if unobserved men resemble observed men in their group', s['mar']]),
        ('row', [cat('Difference if both unobserved groups are ', s['q_lbl_0.0'], '% pad-free'), s['eq_0.0']]),
        ('row', [cat('Difference if both unobserved groups are ', s['q_lbl_0.25'], '% pad-free'), s['eq_0.25']]),
        ('row', [cat('Difference if both unobserved groups are ', s['q_lbl_0.5'], '% pad-free'), s['eq_0.5']]),
        ('row', [cat('Difference if both unobserved groups are ', s['q_lbl_0.75'], '% pad-free'), s['eq_0.75']]),
        ('row', [cat('Difference if both unobserved groups are ', s['q_lbl_1.0'], '% pad-free'), s['eq_1.0']]),
        ('row', ['Pad freedom among unobserved one-pad users that removes the difference, if unobserved two-or-more users resemble observed ones', s['q1_tip']]),
        ('row', ['Pad freedom among unobserved two-or-more users that removes the difference, if unobserved one-pad users resemble observed ones', s['q2_tip']]),
        ('row', ['Equal and opposite shift from observed proportions that removes the difference, percentage points', s['sym']]),
        ('row', ['Lowest and highest possible difference', s['bounds']]),
        ('row', [cat('Share of assumption pairs, in ', m['unit_step'], '-point steps, with a positive difference'), s['pos_share']]),
    ]
    notes = [
        'Differences are one pad minus two or more pads, in percentage points, for all men using pads in the two groups, observed or not. Unobserved men are those without a one-year record. Ranges follow from stated assumptions and are not confidence intervals.',
    ]
    return _merge_blocks(
        'S7',
        'Supplementary Table S7. Documented pad freedom at one year under assumptions about men without a one-year record',
        [('', hdr, rows)],
        notes,
    )


def _s8(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s8']
    hdr_a = ['Rule', 'Men using pads', 'With a one-year record', 'Also in main analysis', 'Added', 'Removed', 'Three-month day changed', 'One-year day changed', 'Pad group changed']
    rows_a = []
    for pol, _, short_lbl in RULE_DEFS:
        r = s['A'][pol]
        if pol == 'P5':
            lbl: Bound | str = cat('Recorded ', m['milestone_3'], '- and ', m['milestone_12'], '-month milestones')
        else:
            lbl = short_lbl
        rows_a.append(('row', [lbl, r['users'], r['with_yr'], r['both'], r['added'], r['removed'], r['early_chg'], r['year_chg'], r['grp_chg']]))

    hdr_b = ['Rule', 'One pad', 'Two or more pads', 'Unclear count', 'Conflicting count', 'All', cat('Difference (bootstrap ', m['confidence'], '% CI)'), cat('Newcombe ', m['confidence'], '% CI')]
    rows_b = []
    for pol, _, short_lbl in RULE_DEFS:
        r = s['B'][pol]
        if pol == 'P5':
            lbl = cat('Recorded ', m['milestone_3'], '- and ', m['milestone_12'], '-month milestones')
        else:
            lbl = short_lbl
        rows_b.append(('row', [lbl, r['one'], r['two_or_more'], r['nonconflicting_quantity_uncertain'], r['unresolved_quantity_evidence'], r['overall'], r['boot'], r['newc']]))

    notes = [
        cat(
            'CI = confidence interval. The main analysis selected the records nearest days ', m['early_target'], ' and ', m['year_target'],
            ' within days ', m['early_0'], DASH, m['early_1'], ' and ', m['year_0'], DASH, m['year_1'], '. ',
            'The conflicting-window rule removed windows containing a day with conflicting pad status. ',
            'The first-usable rule selected the first usable record in each window. ',
            'The narrower rule used days ', m['narrow_early_0'], DASH, m['narrow_early_1'], ' and ', m['narrow_year_0'], DASH, m['narrow_year_1'], '. ',
            'The uncertain-date rule excluded men with an ambiguous or missing date in either window. ',
            'The milestone rule used the ', m['milestone_3'], '- and ', m['milestone_12'], '-month status stored in the database and gives no pad-count comparison.',
        ),
        cat(
            '"Also in main analysis", "Added", and "Removed" compare men with a one-year record with the main analysis. ',
            'Changes in assessment day are counted among men with that assessment under both rules (', s['notes_early_500'],
            ' with a three-month assessment and ', s['notes_year_457'], ' with a one-year assessment in the main analysis). ',
            'Estimates are pad-free men over men with a one-year record (percentage; Wilson score ', m['confidence'], '% confidence interval).',
        ),
    ]
    return _merge_blocks(
        'S8',
        'Supplementary Table S8. Membership and estimates under each assessment rule',
        [
            ('A. Membership', hdr_a, rows_a),
            ('B. Estimates', hdr_b, rows_b),
        ],
        notes,
    )


def _s9(refs: dict, mode: str) -> dict[str, Bound]:
    m = refs['meta']
    s = refs['s9']
    t1 = refs['t1']
    ca = centre_label('Bełchatów', mode)
    cb = centre_label('Salve Medica', mode)
    cc = centre_label("Brigham and Women's Hospital", mode)

    hdr_a = ['Comparison', 'Men with a one-year record', 'One pad, pad-free', 'Two or more pads, pad-free', cat('Difference (bootstrap ', m['confidence'], '% CI)'), cat('Newcombe ', m['confidence'], '% CI')]
    a_specs = [
        ('reference', 'Main comparison'),
        ('exact_count_records', 'Exact counts only'),
        ('epic_instrument_excluded', 'EPIC questionnaire counts excluded'),
        ('platform_flag_excluded', 'Platform data-quality flag excluded'),
        ('including_later_operations', 'Later operations included'),
    ]
    if 'operative_era_2017_2024' in s['A']:
        a_specs.append(('operative_era_2017_2024', cat('Operated ', m['yr_2017'], DASH, m['yr_2024'])))
    rows_a = [('row', [lbl, s['A'][ck]['pairs'], s['A'][ck]['one'], s['A'][ck]['two'], s['A'][ck]['boot'], s['A'][ck]['newc']]) for ck, lbl in a_specs]

    # S9B
    mcols = [
        ('m1', 'Age, country, three-month day'),
        ('m2', 'Age, country, both assessment days'),
        ('m3', 'Centre, period, age, three-month day'),
        ('m4', 'Centre, period, age, both assessment days'),
    ]
    hdr_b = [cat('Term, odds ratio (', m['confidence'], '% CI)')] + [lbl for _, lbl in mcols]
    rows_b: list[tuple[str, list[Bound | str]]] = []
    period_label = cat('Operation in ', m['yr_2024'], DASH, m['yr_2025'], ' vs earlier')
    rspec_b = [
        ('Two or more pads vs one pad', ('two_or_more', 'burden_two_or_more')),
        (cat('Age, per ', m['age_years'], ' years from ', m['age_center']), ('age_per10_cent65',)),
        (cat('Three-month assessment day, per ', m['day_step'], ' days from day ', m['early_target']), ('early_day_per30_cent90',)),
        (cat('One-year assessment day, per ', m['day_step'], ' days from day ', m['year_target']), ('year_day_per30_cent365',)),
        ('United States vs Poland', ('country_us',)),
        (cat(ca, ' vs ', cc), ('centre_belchatow',)),
        (cat(cb, ' vs ', cc), ('centre_salve',)),
        (period_label, ('period_recent',)),
        ('Intercept (odds)', ('intercept',)),
    ]
    for rlbl, keys in rspec_b:
        row_cells: list[Bound | str] = [rlbl]
        for mk, _ in mcols:
            pdict = s['B'][mk]['params']
            hit = next((k for k in keys if k in pdict), None)
            row_cells.append(pdict[hit] if hit else DASH)
        rows_b.append(('row', row_cells))
    rows_b.append(('row', ['Standardized pad freedom, one pad vs two or more'] + [s['B'][mk]['rates'] for mk, _ in mcols]))
    rows_b.append(('row', [cat('Standardized difference, percentage points (bootstrap ', m['confidence'], '% CI)')] + [s['B'][mk]['diff'] for mk, _ in mcols]))
    rows_b.append(('row', [cat('Bootstrap refits not converged, of ', m['draws'])] + [s['B'][mk]['failed'] for mk, _ in mcols]))
    rows_b.append(('row', ['Men (pad-free)'] + [s['B'][mk]['n_ev'] for mk, _ in mcols]))

    # S9C
    ccols = [
        ('clin', 'Clinical model'),
        ('no_int', 'Clinical model, interim treatment excluded'),
        ('ipw', 'Clinical covariates, inverse probability weighting'),
        ('us', 'United States model'),
    ]
    hdr_c = [cat('Term, odds ratio (', m['confidence'], '% CI)')] + [lbl for _, lbl in ccols]
    rspec_c = [
        ('Two or more pads vs one pad', 'two_or_more'),
        (cat('Age, per ', m['age_years'], ' years from ', m['age_center']), 'age_per10_cent65'),
        (cat('Three-month assessment day, per ', m['day_step'], ' days from day ', m['early_target']), 'early_day_per30_cent90'),
        (cat(ca, ' vs ', cc), 'centre_belchatow'),
        (cat(cb, ' vs ', cc), 'centre_salve'),
        (period_label, 'period_recent'),
        ('Nerve sparing not performed vs performed', 'nerve_sparing_not_performed'),
        ('Nerve sparing not stated vs performed', 'nerve_sparing_not_stated'),
        (cat('Pathological stage pT3', DASH, m['stage_max'], ' vs pT2'), 'pt3_or_higher'),
        (cat('Grade group ', m['isup_3'], DASH, m['isup_5'], ' vs ', m['isup_1'], DASH, m['isup_2']), 'isup_3_or_higher'),
        (cat('Body mass index, per ', m['bmi_step'], ' kg/m² from ', m['bmi_center']), 'bmi_per5_cent28'),
        (cat('Prostate volume, per ', m['vol_step'], ' ml from ', m['vol_center']), 'volume_per10_cent40'),
        (cat('ASA class ', m['asa_3'], DASH, m['asa_4'], ' vs ', m['asa_2']), 'asa_3_or_4'),
        (cat('Surgeon case number, per ', m['surg_dbl'], '-fold increase from ', m['surg_center']), 'surgeon_sequence_log2_cent32'),
        ('Intercept (odds)', 'intercept'),
    ]
    rows_c: list[tuple[str, list[Bound | str]]] = []
    for rlbl, key in rspec_c:
        row_cells = [rlbl] + [s['C'][ck]['params'].get(key, DASH) for ck, _ in ccols]
        rows_c.append(('row', row_cells))
    rows_c.append(('row', ['Standardized or weighted pad freedom, one pad vs two or more'] + [s['C'][ck]['rates'] for ck, _ in ccols]))
    rows_c.append(('row', [cat('Adjusted difference, percentage points (bootstrap ', m['confidence'], '% CI)')] + [s['C'][ck]['adj'] for ck, _ in ccols]))
    rows_c.append(('row', [cat('Crude difference in the same men, percentage points (bootstrap ', m['confidence'], '% CI)')] + [s['C'][ck]['crude'] for ck, _ in ccols]))
    rows_c.append(('row', ['Largest absolute standardized mean difference, before and after weighting'] + [s['C'][ck].get('smd', DASH) for ck, _ in ccols]))
    rows_c.append(('row', ['Effective sample size, one pad and two or more; largest weight'] + [s['C'][ck].get('ess', DASH) for ck, _ in ccols]))
    rows_c.append(('row', [cat('Bootstrap refits not converged, of ', m['draws'])] + [s['C'][ck]['failed'] for ck, _ in ccols]))
    rows_c.append(('row', ['Men (pad-free)'] + [s['C'][ck]['n_ev'] for ck, _ in ccols]))

    notes = [
        cat(
            'CI = confidence interval; EPIC = Expanded Prostate Cancer Index Composite; ASA = American Society of Anesthesiologists; ',
            DASH, ' = term not included in that model. Exact counts means every valid record on the selected three-month day gave a single count or equal bounds. ',
            'Later operations included shows results without the follow-up eligibility cutoff.',
        ),
        cat(
            'Differences are one pad minus two or more pads, in percentage points, with whole-patient percentile bootstrap intervals from ',
            m['draws'], ' resamples and Newcombe hybrid score intervals. Odds ratios have Wald ', m['confidence'], '% confidence intervals. ',
            'Centre models include operative period (', m['yr_2024'], DASH, m['yr_2025'], ' vs earlier; recent period threshold ',
            m['recent_start_yr'], '). Interim treatment excluded ', s['notes']['interim_excl'],
            ' men with complete clinical covariates (of ', s['notes']['interim_total'], ' total among the ', t1['n_total'],
            ' men) who started radiotherapy or androgen deprivation therapy between the two assessments.',
        ),
    ]
    return _merge_blocks(
        'S9',
        'Supplementary Table S9. Restricted and adjusted comparisons of pad freedom at one year',
        [
            ('A. Restricted comparisons', hdr_a, rows_a),
            (cat('B. Adjusted logistic models among the ', t1['n_total'], ' men compared'), hdr_b, rows_b),
            ('C. Clinically adjusted analyses', hdr_c, rows_c),
        ],
        notes,
    )


def bound_products(refs: dict, mode: str = DEFAULT_MODE) -> dict[str, Bound]:
    out: dict[str, Bound] = {}
    for fn in (_s1, _s2, _s3, _s4, _s5, _s6, _s7, _s8, _s9):
        out.update(fn(refs, mode))
    return out


def main():
    _, _, _, refs = build_all()
    OUT_SUPP.mkdir(exist_ok=True)
    bmap = bound_products(refs, DEFAULT_MODE)
    for rel_path, bound in bmap.items():
        (TASK / rel_path).write_text(bound.text, encoding='utf8', newline='')
    print(f'Generated {len(bmap)} supplementary files (S1-S9 CSV and Markdown).')


if __name__ == '__main__':
    main()
