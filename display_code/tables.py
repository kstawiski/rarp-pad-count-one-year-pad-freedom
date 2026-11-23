"""Build editable Table 1, Table 2 (CSV, Markdown, DOCX) and standalone captions."""
from pathlib import Path
import csv
import io
import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt

from centre_labels import DEFAULT_MODE, centre_label
from extract_display_values import Bound, DASH, TASK, build_all, cat

OUT_TABLES = TASK / 'tables'
OUT_CAPTIONS = TASK / 'captions'


def _npct(cnt_b: Bound, pct_b: Bound | None) -> Bound:
    if cnt_b.text == '0' or pct_b is None:
        return cnt_b
    return cat(cnt_b, ' (', pct_b, '%)')


def _mediqr(bdict: dict, prefix: str) -> Bound:
    return cat(bdict[f'{prefix}_median'], ' (', bdict[f'{prefix}_q1'], DASH, bdict[f'{prefix}_q3'], ')')


def _frac(n_b: Bound, d_b: Bound, pct_b: Bound) -> Bound:
    return cat(n_b, '/', d_b, ' (', pct_b, '%)')


def bound_table_products(stem: str, title_b: Bound | str, headers_b: list[Bound | str], rows_b: list[tuple[str, list[Bound | str]]], notes_b: list[Bound | str], base_dir: str = 'tables') -> tuple[dict[str, Bound], dict]:
    """Serialize one table into Bound CSV and Bound Markdown plus plain DOCX structure."""
    def as_bound(x: Bound | str) -> Bound:
        return x if isinstance(x, Bound) else cat(x)

    title_b = as_bound(title_b)
    hdr = [as_bound(h) for h in headers_b]

    # CSV: header row then flat row cells (section titles keep empty cells)
    csv_lines: list[Bound] = []
    # Use csv module on plain text per line only if no commas break structure, OR wrap csv.writer on cell strings!
    # Wait: csv quoting never alters numeric tokens unless quoting itself touches digits (never).
    # Construct line-by-line Bound for CSV so slot order is preserved identically!
    def csv_line(cells: list[Bound]) -> Bound:
        buf = io.StringIO()
        csv.writer(buf, lineterminator='\n').writerow([c.text for c in cells])
        raw_line = buf.getvalue()
        # Re-map cells deterministically into serialized CSV row by finding quotes/commas without digits:
        parts: list[Bound | str] = []
        for idx, c in enumerate(cells):
            if idx > 0:
                parts.append(',')
            b = io.StringIO()
            csv.writer(b, lineterminator='').writerow([c.text])
            s = b.getvalue()
            if s.startswith('"') and s.endswith('"'):
                parts.extend(['"', c, '"'])
            else:
                parts.append(c)
        parts.append('\n')
        return cat(*parts)

    csv_parts = [csv_line(hdr)]
    for kind, cells in rows_b:
        csv_parts.append(csv_line([as_bound(c) for c in cells]))
    csv_bound = cat(*csv_parts)

    # Markdown: title, blank line, pipe table, notes
    md_parts: list[Bound | str] = ['**', title_b, '**\n\n| ']
    for i, h in enumerate(hdr):
        if i > 0:
            md_parts.append(' | ')
        md_parts.append(h)
    md_parts.append(' |\n| ' + ' | '.join(['---'] * len(hdr)) + ' |\n')

    docx_rows: list[tuple[str, list[str]]] = []
    for kind, raw_cells in rows_b:
        bcells = [as_bound(c) for c in raw_cells]
        docx_rows.append((kind, [c.text for c in bcells]))
        md_parts.append('| ')
        for i, c in enumerate(bcells):
            if i > 0:
                md_parts.append(' | ')
            if kind == 'section' and i == 0 and c.text:
                md_parts.extend(['**', c, '**'])
            else:
                md_parts.append(c)
        md_parts.append(' |\n')
    for note in notes_b:
        md_parts.extend(['\n', as_bound(note), '\n'])
    md_bound = cat(*md_parts)

    return (
        {f'{base_dir}/{stem}.csv': csv_bound, f'{base_dir}/{stem}.md': md_bound},
        {'stem': stem, 'title': title_b.text, 'header': [h.text for h in hdr], 'rows': docx_rows, 'notes': [as_bound(n).text for n in notes_b]},
    )


def _table1(refs: dict, mode: str = DEFAULT_MODE):
    m = refs['meta']
    t = refs['t1']
    centre_a = centre_label('Bełchatów', mode)
    centre_b = centre_label('Salve Medica', mode)
    centre_c = centre_label("Brigham and Women's Hospital", mode)

    title = cat(
        'Table ', m['tbl_1'], '. Characteristics of men using one ordinary pad or two or more pads per day about three months after ',
        'robot-assisted radical prostatectomy, among ', t['n_total'], ' men with a one-year pad-status record',
    )
    header = [
        'Characteristic',
        cat('One pad per day (n = ', t['n_one'], ')'),
        cat('Two or more pads per day (n = ', t['n_two_or_more'], ')'),
    ]
    rows: list[tuple[str, list[Bound | str]]] = []

    def sec(lbl: Bound | str):
        rows.append(('section', [lbl, '', '']))

    def row(lbl: Bound | str, a: Bound | str, b: Bound | str):
        rows.append(('row', [lbl, a, b]))

    row('Age, yr, median (IQR)', _mediqr(t, 'age_one'), _mediqr(t, 'age_two_or_more'))
    sec('Country, n (%)')
    for c in ('Poland', 'United States'):
        row(c, _npct(t[f'country_one_{c}'], t[f'country_one_{c}_pct']), _npct(t[f'country_two_or_more_{c}'], t[f'country_two_or_more_{c}_pct']))
    sec('Centre, n (%)')
    for raw_k, disp in (('Bełchatów', centre_a), ('Salve Medica', centre_b), ("Brigham and Women's Hospital", centre_c)):
        row(disp, _npct(t[f'centre_one_{raw_k}'], t[f'centre_one_{raw_k}_pct']), _npct(t[f'centre_two_or_more_{raw_k}'], t[f'centre_two_or_more_{raw_k}_pct']))
    sec('Year of surgery, n (%)')
    row(cat(m['yr_2017'], DASH, m['yr_2024']), _npct(t['period_one_2017-2024'], t['period_one_2017-2024_pct']), _npct(t['period_two_or_more_2017-2024'], t['period_two_or_more_2017-2024_pct']))
    row(m['yr_2025'], _npct(t['period_one_2025-2026'], t['period_one_2025-2026_pct']), _npct(t['period_two_or_more_2025-2026'], t['period_two_or_more_2025-2026_pct']))

    row('Body mass index, kg/m², median (IQR)', _mediqr(t, 'bmi_one'), _mediqr(t, 'bmi_two_or_more'))
    row('\u2003Not recorded, n', t['bmi_one_missing'], t['bmi_two_or_more_missing'])
    row('Preoperative PSA, ng/ml, median (IQR)', _mediqr(t, 'psa_preop_one'), _mediqr(t, 'psa_preop_two_or_more'))
    row('\u2003Not recorded, n', t['psa_preop_one_missing'], t['psa_preop_two_or_more_missing'])
    row('Prostate volume, ml, median (IQR)', _mediqr(t, 'prostate_volume_one'), _mediqr(t, 'prostate_volume_two_or_more'))
    row('\u2003Not recorded, n', t['prostate_volume_one_missing'], t['prostate_volume_two_or_more_missing'])

    sec('Biopsy ISUP grade group, n (%)')
    for lbl, gk in ((m['isup_1'], '1.0'), (m['isup_2'], '2.0'), (m['isup_3'], '3.0'), (m['isup_4'], '4.0'), (m['isup_5'], '5.0'), ('Not recorded', 'missing_not_recorded')):
        row(lbl, _npct(t[f'isup_one_{gk}'], t[f'isup_one_{gk}_pct']), _npct(t[f'isup_two_or_more_{gk}'], t[f'isup_two_or_more_{gk}_pct']))

    sec('Pathological stage, n (%)')
    row('pT2', _npct(t['pstage_one_pT2'], t['pstage_one_pT2_pct']), _npct(t['pstage_two_or_more_pT2'], t['pstage_two_or_more_pT2_pct']))
    row(cat('pT3', DASH, m['stage_max']), _npct(t['pstage_one_pT3-4'], t['pstage_one_pT3-4_pct']), _npct(t['pstage_two_or_more_pT3-4'], t['pstage_two_or_more_pT3-4_pct']))

    sec('Pathological ISUP grade group, n (%)')
    for lbl, gk in ((cat(m['isup_1'], DASH, m['isup_2']), '1-2'), (cat(m['isup_3'], DASH, m['isup_5']), '3-5'), ('Not recorded', 'missing')):
        row(lbl, _npct(t[f'fisup_one_{gk}'], t[f'fisup_one_{gk}_pct']), _npct(t[f'fisup_two_or_more_{gk}'], t[f'fisup_two_or_more_{gk}_pct']))

    sec('Nerve sparing, n (%)')
    for lbl, gk in (('Performed', 'performed'), ('Not performed', 'not_performed'), ('Not stated in the record', 'not_assessed')):
        row(lbl, _npct(t[f'nerve_one_{gk}'], t[f'nerve_one_{gk}_pct']), _npct(t[f'nerve_two_or_more_{gk}'], t[f'nerve_two_or_more_{gk}_pct']))

    row('Three-month assessment, postoperative day, median (IQR)', _mediqr(t, 'early_day_one'), _mediqr(t, 'early_day_two_or_more'))
    row('One-year assessment, postoperative day, median (IQR)', _mediqr(t, 'year_day_one'), _mediqr(t, 'year_day_two_or_more'))

    sec('Source of the pad count, n (%)')
    for lbl, gk in (('Clinical note', 'free_text'), ('EPIC questionnaire', 'EPIC')):
        row(lbl, _npct(t[f'instr_one_{gk}'], t[f'instr_one_{gk}_pct']), _npct(t[f'instr_two_or_more_{gk}'], t[f'instr_two_or_more_{gk}_pct']))

    sec('Continence assessment method, n (%)')
    for lbl, gk in (('Clinic visit', 'visit'), ('Questionnaire', 'questionnaire'), ('Telephone', 'phone')):
        row(lbl, _npct(t[f'method_one_{gk}'], t[f'method_one_{gk}_pct']), _npct(t[f'method_two_or_more_{gk}'], t[f'method_two_or_more_{gk}_pct']))

    sec('Postoperative cancer treatment, n (%)')
    for lbl, gk in (('Recorded as given', 'True'), ('Recorded as not given', 'False'), ('Not established from the record', 'missing_not_recorded')):
        row(lbl, _npct(t[f'tx_one_{gk}'], t[f'tx_one_{gk}_pct']), _npct(t[f'tx_two_or_more_{gk}'], t[f'tx_two_or_more_{gk}_pct']))

    row('Cancer treatment started between the two assessments, n (%)', _npct(t['interim_one'], t['interim_one_pct']), _npct(t['interim_two_or_more'], t['interim_two_or_more_pct']))

    for ck, day_b in (('any_complication_30d', m['comp_30']), ('any_complication_90d', m['comp_90'])):
        row(
            cat('Any complication within ', day_b, ' days, n/N (%)'),
            _frac(t[f'{ck}_one_true'], t[f'{ck}_one_denom'], t[f'{ck}_one_pct']),
            _frac(t[f'{ck}_two_or_more_true'], t[f'{ck}_two_or_more_denom'], t[f'{ck}_two_or_more_pct']),
        )
        row('\u2003Not recorded, n', t[f'{ck}_one_missing'], t[f'{ck}_two_or_more_missing'])

    notes = [
        'IQR = interquartile range; ISUP = International Society of Urological Pathology; PSA = prostate-specific antigen; EPIC = Expanded Prostate Cancer Index Composite.',
        'Percentages use the column total, except complication percentages, which use men with a recorded complication status (n/N). "Not stated in the record" and "Not established from the record" mean that the record was read but did not settle the item. "Not recorded" means the field was empty.',
        'The source of the pad count and the assessment method are recorded once per patient and do not distinguish the three-month and one-year assessments.',
        cat('Year of surgery is grouped as ', m['yr_2017'], DASH, m['yr_2024'], ' and ', m['yr_2025'], ' because the aggregate source summary does not separate ', m['yr_2017'], DASH, m['yr_2022'], ', ', m['yr_2023'], ', and ', m['yr_2024'], DASH, m['yr_2025'], '.'),
        cat('Prostate volume was recorded for ', t['pv_us_recorded'], ' of ', t['us_compared'], ' men treated in the United States and ', t['pv_pl_recorded'], ' of ', t['pl_compared'], ' treated in Poland.'),
        'Postoperative cancer treatment refers to radiotherapy or androgen deprivation therapy recorded in the database. Treatment started between the two assessments is counted when the dated first treatment fell after the selected three-month day and on or before the selected one-year day.',
        cat('One-year outcomes for the ', t['unclass_total'], ' men whose three-month pad count could not be classified are shown in Supplementary Table S2.'),
    ]
    return bound_table_products('Table1', title, header, rows, notes)


def _table2(refs: dict, mode: str = DEFAULT_MODE):
    m = refs['meta']
    t = refs['t2']
    centre_a = centre_label('Bełchatów', mode)
    centre_b = centre_label('Salve Medica', mode)
    centre_c = centre_label("Brigham and Women's Hospital", mode)

    title = cat('Table ', m['tbl_2'], '. Availability of a one-year pad-status record among men using pads about three months after robot-assisted radical prostatectomy')
    header = ['Characteristic', 'With a one-year record/total (%)']
    rows: list[tuple[str, list[Bound | str]]] = []

    def sec(lbl: Bound | str):
        rows.append(('section', [lbl, '']))

    def row(lbl: Bound | str, val_b: Bound):
        rows.append(('row', [lbl, val_b]))

    row('All men using pads', _frac(t['overall_with'], t['overall_tot'], t['overall_pct']))
    sec('Pad count at three months')
    for lbl, ak in (('One pad per day', 'group_one'), ('Two or more pads per day', 'group_two_or_more'), ('Count unclear', 'group_nonconflicting_quantity_uncertain'), ('Count conflicting or invalid', 'group_unresolved_quantity_evidence')):
        row(lbl, _frac(t[f'{ak}_with'], t[f'{ak}_tot'], t[f'{ak}_pct']))
    sec('Centre')
    for disp, ak in ((centre_a, 'centre_Bełchatów'), (centre_b, 'centre_Salve Medica'), (centre_c, "centre_Brigham and Women's Hospital")):
        row(disp, _frac(t[f'{ak}_with'], t[f'{ak}_tot'], t[f'{ak}_pct']))
    sec('Year of surgery')
    for lbl, ak in (
        (cat(m['yr_2017'], DASH, m['yr_2022']), 'period_2017-2022'),
        (m['yr_2023'], 'period_2023'),
        (m['yr_2024'], 'period_2024'),
        (m['yr_2025'], 'period_2025-2026'),
    ):
        row(lbl, _frac(t[f'{ak}_with'], t[f'{ak}_tot'], t[f'{ak}_pct']))
    sec('Age at surgery')
    for lbl, ak in (
        (cat('<', m['age_lt60'], ' yr'), 'age_lt60'),
        (cat(m['age_60'], DASH, m['age_69'], ' yr'), 'age_60_69'),
        (cat('≥', m['age_ge70'], ' yr'), 'age_ge70'),
    ):
        row(lbl, _frac(t[f'{ak}_with'], t[f'{ak}_tot'], t[f'{ak}_pct']))
    sec('With vs without a one-year record, median (IQR)')
    row('Age, yr', cat(_mediqr(t, 'age_with_year'), ' vs ', _mediqr(t, 'age_without_year')))
    row('Three-month assessment, postoperative day', cat(_mediqr(t, 'early_day_with_year'), ' vs ', _mediqr(t, 'early_day_without_year')))

    notes = [
        'IQR = interquartile range.',
        cat('A one-year record was a usable pad-status record between postoperative days ', m['year_0'], DASH, m['year_1'], '. Every man in the study cohort had postoperative day ', m['close_day'], ' before ', m['extract_day'], ' April ', m['extract_year'], '.'),
        'Men without a one-year record were not counted as pad-free or as pad users.',
    ]
    return bound_table_products('Table2', title, header, rows, notes)


def _captions(refs: dict, mode: str = DEFAULT_MODE) -> dict[str, Bound]:
    m = refs['meta']
    t1 = refs['t1']
    t2 = refs['t2']
    u = refs['unsep']
    centre_a = centre_label('Bełchatów', mode)
    centre_b = centre_label('Salve Medica', mode)
    centre_c = centre_label("Brigham and Women's Hospital", mode)

    windows = cat(
        'Three-month and one-year assessments used postoperative days ',
        m['early_0'], DASH, m['early_1'], ' and ', m['year_0'], DASH, m['year_1'],
        ', nearest days ', m['early_target'], ' and ', m['year_target'], ', respectively.',
    )

    cap_fig1 = cat(
        'Documented pad use and pad freedom at one year by pad use at about three months after robot-assisted radical prostatectomy in Poland and the United States. ',
        windows, ' ',
        'A shows patient selection as a flow diagram from the database through robotic prostatectomy and follow-up eligibility to the ',
        refs['fig1_189'], ' men compared, with exclusions at each step. ',
        'The ', refs['fig1_189'], ' men contributing to the ordered comparison are shaded. ',
        'B shows the percentages in each one-year pad category by three-month pad count, with pad-free percentages and Wilson score ', m['confidence'], '% confidence intervals alongside. ',
        'The ', u['N'], ' men using two or more pads whose count could not be separated into two or three or more are not drawn. ',
        'One-year categories were ', u['pad_free'], ' "Pad-free", ', u['one'], ' "Using pads, at most one per day", ',
        u['two_or_more'], ' "More than one pad per day", and ', u['not_classifiable'], ' "Pads, count not recorded". ',
        'C shows documented pad freedom at one year within Poland and within the United States, with each country overall row first. ',
        'D shows one-pad-minus-two-or-more differences within each population. ',
        'Differences were estimated separately within each country. ',
        'No between-country contrast or interaction was estimated. ',
        'CI indicates confidence interval, and n/N lists documented pad freedom at one year over men with a one-year record. ',
        'Differences have whole-patient percentile bootstrap ', m['confidence'], '% confidence intervals from ', m['draws'], ' draws. ',
        'Differences were computed from unrounded proportions, so they can differ by one point from the difference of the displayed percentages.\n',
    )

    cap_fig2 = cat(
        'Sensitivity analyses of the one-pad-minus-two-or-more difference in documented one-year pad freedom after robot-assisted radical prostatectomy in Poland and the United States. ',
        windows, ' ',
        'Narrower assessment windows used postoperative days ',
        m['narrow_early_0'], DASH, m['narrow_early_1'], ' and ', m['narrow_year_0'], DASH, m['narrow_year_1'], '. ',
        'A shows the difference under alternative observation rules, measurement restrictions, follow-up selections, and covariate adjustments, with group counts or adjusted percentages alongside each difference. ',
        'Differences have whole-patient percentile bootstrap ', m['confidence'], '% confidence intervals from ', m['draws'], ' draws. ',
        'The least favourable split of unclassifiable counts has a Newcombe hybrid score interval. ',
        'Differences were computed from unrounded proportions, so they can differ by one point from the difference of the displayed percentages. ',
        'B shows the completed-population difference across assumed pad-free proportions among unobserved men in both groups, with the dashed path to the tipping point. ',
        'CI indicates confidence interval, RT radiotherapy, and ADT androgen deprivation therapy.\n',
    )

    cap_figS1 = cat(
        'Assessment windows and pad-count classification rules after robot-assisted radical prostatectomy. ',
        'Surgery is postoperative day ', m['zero_day'], '. ',
        'Blue bands show the main three-month window (days ', m['early_0'], DASH, m['early_1'], ', nearest day ', m['early_target'], ') and one-year window (days ', m['year_0'], DASH, m['year_1'], ', nearest day ', m['year_target'], '). ',
        'Grey bands show the supplementary six-month window (days ', m['six_0'], DASH, m['six_1'], ', nearest day ', m['six_target'], ') and two-year window (days ', m['two_year_0'], DASH, m['two_year_1'], ', nearest day ', m['two_year_target'], '). ',
        'One pad required every record with a count on the selected three-month day to show one ordinary pad per day, and two or more required at least two. ',
        'Missing counts and ranges spanning one and two pads were classified as unclear, and incompatible or invalid records as conflicting. ',
        'The one-year outcome was an explicit record of no pad use. ',
        'This schematic shows study definitions only and plots no patient counts or results.\n',
    )

    cap_t1 = cat(
        'Clinical characteristics by three-month pad group among ', t1['n_total'], ' men with classifiable counts and a one-year record after robot-assisted radical prostatectomy in Poland and the United States. ',
        windows, ' ',
        'Values are patient counts with percentages or medians with interquartile range (IQR). ',
        'Medians and interquartile ranges were rounded half up to whole years or days, while body mass index and prostate-specific antigen keep one decimal. ',
        'Centres are masked as ', centre_a, ', ', centre_b, ', and ', centre_c, ', ISUP indicates International Society of Urological Pathology, PSA prostate-specific antigen, and EPIC Expanded Prostate Cancer Index Composite. ',
        'The ', t1['unclass_total'], ' men with unclassifiable three-month quantity are described with record availability and supplementary outcomes, not in this table.\n',
    )

    cap_t2 = cat(
        'Availability of a one-year pad-status record among ', t2['overall_tot'], ' men using pads about three months after robot-assisted radical prostatectomy in Poland and the United States. ',
        windows, ' ',
        'Values show men with a one-year record over total early pad users with percentages, followed by median and interquartile range (IQR) by availability status. ',
        'Every man included in the cohort had postoperative day ', m['close_day'], ' before ', m['extract_day'], ' April ', m['extract_year'], '. ',
        'Centres are masked as ', centre_a, ', ', centre_b, ', and ', centre_c, '. ',
        'Of ', t2['without_total'], ' men without a one-year record, ', t2['no_valid_obs'], ' had no valid one-year observation and ', t2['conflicting_only'], ' had conflicting-only evidence. ',
        'Neither group was counted as pad-free or as using pads at one year.\n',
    )

    return {
        'captions/Figure1.txt': cap_fig1,
        'captions/Figure2.txt': cap_fig2,
        'captions/FigureS1.txt': cap_figS1,
        'captions/Table1.txt': cap_t1,
        'captions/Table2.txt': cap_t2,
    }


def bound_products(refs: dict, mode: str = DEFAULT_MODE) -> tuple[dict[str, Bound], list[dict]]:
    p1, d1 = _table1(refs, mode)
    p2, d2 = _table2(refs, mode)
    caps = _captions(refs, mode)
    out = {}
    out.update(p1)
    out.update(p2)
    out.update(caps)
    d1['widths'] = (Mm(70), Mm(50), Mm(50))
    d2['widths'] = (Mm(95), Mm(75))
    return out, [d1, d2]


def write_docx(spec: dict) -> None:
    OUT_TABLES.mkdir(exist_ok=True)
    document = docx.Document()
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(20)
    section.top_margin = section.bottom_margin = Mm(20)
    style = document.styles['Normal']
    style.font.name = 'Arial'
    style.font.size = Pt(9)
    p = document.add_paragraph()
    run = p.add_run(spec['title'])
    run.bold = True
    header = spec['header']
    table = document.add_table(rows=1, cols=len(header))
    table.style = 'Table Grid'
    for i, h in enumerate(header):
        cell = table.rows[0].cells[i]
        cell.text = ''
        r = cell.paragraphs[0].add_run(h)
        r.bold = True
        if i > 0:
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for kind, cells in spec['rows']:
        tr = table.add_row().cells
        for i, val in enumerate(cells):
            tr[i].text = ''
            r = tr[i].paragraphs[0].add_run(val)
            if kind == 'section' and i == 0:
                r.bold = True
            if i > 0:
                tr[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    widths = spec['widths']
    for row_cells in table.rows:
        for i, wdt in enumerate(widths[:len(header)]):
            row_cells.cells[i].width = wdt
    for note in spec['notes']:
        document.add_paragraph(note)
    document.core_properties.author = ''
    document.core_properties.title = spec['title'].split('. ')[0]
    document.save(OUT_TABLES / f"{spec['stem']}.docx")


def main():
    _, _, _, refs = build_all()
    bmap, docx_specs = bound_products(refs, DEFAULT_MODE)
    OUT_TABLES.mkdir(exist_ok=True)
    OUT_CAPTIONS.mkdir(exist_ok=True)
    for rel_path, bound in bmap.items():
        (TASK / rel_path).write_text(bound.text, encoding='utf8', newline='')
    for spec in docx_specs:
        write_docx(spec)
    print(f'Generated Table1 & Table2 (CSV, MD, DOCX) and {len([k for k in bmap if k.startswith("captions/")])} standalone captions.')


if __name__ == '__main__':
    main()
