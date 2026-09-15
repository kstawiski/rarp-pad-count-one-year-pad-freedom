"""Main Tables 1 and 2 for manuscript1 (v6, final external review).

Reads only frozen aggregate evidence records and writes CSV, Markdown and DOCX files
under tables/. Percentages use two significant figures rounded half up (decision D-P1).
Medians of integer-valued measurements are whole numbers rounded half up (D-P2). Body
mass index and PSA keep one decimal. Every categorical block is checked to sum to its
group size before anything is written.
"""
import csv
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Mm

TASK = Path(__file__).resolve().parents[1]
EV = Path('/umed-projekty/PROSTATA_JOBCZYK2026_v2/manuscript1/evidence')
OUT = TASK / 'tables'
PH = json.loads((EV / 'POSTHOC_TWOGROUP.json').read_text())
SEL = json.loads((EV / 'SELECTION_FOLLOWUP_SENSITIVITY.json').read_text())
CLIN = json.loads((EV / 'CLINICAL_ADJUSTMENT.json').read_text())
DASH = '–'


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
    return str(int(r)) if q >= 1 else format(r, 'f')


def whole(v):
    return str(int(Decimal(repr(float(v))).quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def one_dec(v):
    return format(Decimal(repr(float(v))).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP), 'f')


def npct(n, d):
    return f'{n} ({sig2(100 * n / d)}%)' if n else '0'


def frac(n, d):
    return f'{n}/{d} ({sig2(100 * n / d)}%)'


def mediqr(m, fmt=whole):
    return f"{fmt(m['median'])} ({fmt(m['q1'])}{DASH}{fmt(m['q3'])})"


def check_sum(block, n, name):
    total = sum(block.values())
    if total != n:
        raise SystemExit(f'{name}: categories sum to {total}, expected {n}')


def table1():
    g = PH['table1_by_group_201']
    groups = ('one', 'two_or_more')
    n = {k: g['n'][k] for k in groups}
    rows = []

    def sec(label):
        rows.append(('section', label, '', ''))

    def row(label, a, b):
        rows.append(('row', label, a, b))

    row('Age, yr, median (IQR)', mediqr(g['age']['one']), mediqr(g['age']['two_or_more']))
    for key, name in (('country', 'Country'), ('centre', 'Centre'), ('operative_period', 'Year of surgery'),
                      ('isup_grade_preop', 'Biopsy ISUP grade group'), ('nerve_sparing_state', 'Nerve sparing'),
                      ('pad_count_instrument_src', 'Source of the pad count'),
                      ('continence_assessment_method_src', 'Continence assessment method'),
                      ('postoperative_treatment_any_documented', 'Postoperative cancer treatment'),
                      ('any_complication_30d', 'complication30'), ('any_complication_90d', 'complication90')):
        for k in groups:
            check_sum(g[key][k], n[k], f'{key}/{k}')
    sec('Country, n (%)')
    for label, val in (('Poland', 'Poland'), ('United States', 'United States')):
        row(label, npct(g['country']['one'].get(val, 0), n['one']), npct(g['country']['two_or_more'].get(val, 0), n['two_or_more']))
    sec('Centre, n (%)')
    for label, val in (('Bełchatów Hospital, Poland', 'Bełchatów'), ('SalveMedica, Łódź, Poland', 'Salve Medica'),
                       ("Brigham and Women's Hospital, USA", "Brigham and Women's Hospital")):
        row(label, npct(g['centre']['one'].get(val, 0), n['one']), npct(g['centre']['two_or_more'].get(val, 0), n['two_or_more']))
    sec('Year of surgery, n (%)')
    for label, val in (('2017' + DASH + '2024', '2017-2024'), ('2025' + DASH + '2026', '2025-2026')):
        row(label, npct(g['operative_period']['one'].get(val, 0), n['one']),
            npct(g['operative_period']['two_or_more'].get(val, 0), n['two_or_more']))
    row('Body mass index, kg/m², median (IQR)', mediqr(g['bmi']['one'], one_dec), mediqr(g['bmi']['two_or_more'], one_dec))
    row(' Not recorded, n', str(g['bmi']['one']['missing']), str(g['bmi']['two_or_more']['missing']))
    row('Preoperative PSA, ng/ml, median (IQR)', mediqr(g['psa_preop']['one'], one_dec), mediqr(g['psa_preop']['two_or_more'], one_dec))
    row(' Not recorded, n', str(g['psa_preop']['one']['missing']), str(g['psa_preop']['two_or_more']['missing']))
    cg = CLIN['by_group_201']
    pv = cg['prostate_volume_cc']
    if pv['one']['n'] + pv['one']['missing'] != n['one'] or pv['two_or_more']['n'] + pv['two_or_more']['missing'] != n['two_or_more']:
        raise SystemExit('prostate volume denominators')
    row('Prostate volume, ml, median (IQR)', mediqr(pv['one']), mediqr(pv['two_or_more']))
    row(' Not recorded, n', str(pv['one']['missing']), str(pv['two_or_more']['missing']))
    sec('Biopsy ISUP grade group, n (%)')
    for label, val in (('1', '1.0'), ('2', '2.0'), ('3', '3.0'), ('4', '4.0'), ('5', '5.0'), ('Not recorded', 'missing_not_recorded')):
        row(label, npct(g['isup_grade_preop']['one'].get(val, 0), n['one']),
            npct(g['isup_grade_preop']['two_or_more'].get(val, 0), n['two_or_more']))
    for key in ('pathological_stage', 'final_isup_grade_group'):
        for k in groups:
            check_sum(cg[key][k], n[k], f'{key}/{k}')
    sec('Pathological stage, n (%)')
    for label, val in (('pT2', 'pT2'), ('pT3' + DASH + '4', 'pT3-4')):
        row(label, npct(cg['pathological_stage']['one'].get(val, 0), n['one']),
            npct(cg['pathological_stage']['two_or_more'].get(val, 0), n['two_or_more']))
    sec('Pathological ISUP grade group, n (%)')
    for label, val in (('1' + DASH + '2', '1-2'), ('3' + DASH + '5', '3-5'), ('Not recorded', 'missing')):
        row(label, npct(cg['final_isup_grade_group']['one'].get(val, 0), n['one']),
            npct(cg['final_isup_grade_group']['two_or_more'].get(val, 0), n['two_or_more']))
    sec('Nerve sparing, n (%)')
    for label, val in (('Performed', 'performed'), ('Not performed', 'not_performed'), ('Not stated in the record', 'not_assessed')):
        row(label, npct(g['nerve_sparing_state']['one'].get(val, 0), n['one']),
            npct(g['nerve_sparing_state']['two_or_more'].get(val, 0), n['two_or_more']))
    row('Three-month assessment, postoperative day, median (IQR)', mediqr(g['early_day']['one']), mediqr(g['early_day']['two_or_more']))
    row('One-year assessment, postoperative day, median (IQR)', mediqr(g['year_day']['one']), mediqr(g['year_day']['two_or_more']))
    sec('Source of the pad count, n (%)')
    for label, val in (('Clinical note', 'free_text'), ('EPIC questionnaire', 'EPIC')):
        row(label, npct(g['pad_count_instrument_src']['one'].get(val, 0), n['one']),
            npct(g['pad_count_instrument_src']['two_or_more'].get(val, 0), n['two_or_more']))
    sec('Continence assessment method, n (%)')
    for label, val in (('Clinic visit', 'visit'), ('Questionnaire', 'questionnaire'), ('Telephone', 'phone')):
        row(label, npct(g['continence_assessment_method_src']['one'].get(val, 0), n['one']),
            npct(g['continence_assessment_method_src']['two_or_more'].get(val, 0), n['two_or_more']))
    sec('Postoperative cancer treatment, n (%)')
    tr = g['postoperative_treatment_any_documented']
    for label, val in (('Recorded as given', 'True'), ('Recorded as not given', 'False'), ('Not established from the record', 'missing_not_recorded')):
        row(label, npct(tr['one'].get(val, 0), n['one']), npct(tr['two_or_more'].get(val, 0), n['two_or_more']))
    tt = PH['table1_extension_226']['treatment_timing']['first_treatment_starting_between_assessments_by_burden']
    if tt['one']['n'] != n['one'] or tt['two_or_more']['n'] != n['two_or_more']:
        raise SystemExit('treatment timing denominators')
    row('Cancer treatment started between the two assessments, n (%)', npct(tt['one']['treatment_starting_between_assessments'], n['one']),
        npct(tt['two_or_more']['treatment_starting_between_assessments'], n['two_or_more']))
    for key, label in (('any_complication_30d', 'Any complication within 30 days'), ('any_complication_90d', 'Any complication within 90 days')):
        a, b = g[key]['one'], g[key]['two_or_more']
        row(label + ', n/N (%)', frac(a['True'], a['True'] + a['False']), frac(b['True'], b['True'] + b['False']))
        row(' Not recorded, n', str(a['missing_not_recorded']), str(b['missing_not_recorded']))
    header = ('Characteristic', f"One pad per day (n = {n['one']})", f"Two or more pads per day (n = {n['two_or_more']})")
    title = ('Table 1. Characteristics of men using one ordinary pad or two or more pads per day about three months after '
             'robot-assisted radical prostatectomy, among 201 men with a one-year pad-status record')
    notes = [
        'IQR = interquartile range; ISUP = International Society of Urological Pathology; PSA = prostate-specific antigen; '
        'EPIC = Expanded Prostate Cancer Index Composite.',
        'Percentages use the column total, except complication percentages, which use men with a recorded complication status (n/N). '
        '"Not stated in the record" and "Not established from the record" mean that the record was read but did not settle the item. '
        '"Not recorded" means the field was empty.',
        'The source of the pad count and the assessment method are recorded once per patient and do not distinguish the three-month and one-year assessments.',
        (f"Prostate volume was recorded for {cg['prostate_volume_recorded_by_country']['United States']} of "
         f"{g['country']['one'].get('United States', 0) + g['country']['two_or_more'].get('United States', 0)} men treated in the United States "
         f"and {cg['prostate_volume_recorded_by_country']['Poland']} of "
         f"{g['country']['one'].get('Poland', 0) + g['country']['two_or_more'].get('Poland', 0)} treated in Poland."),
        'Postoperative cancer treatment refers to radiotherapy or androgen deprivation therapy recorded in the database. Treatment started between the two assessments is counted when the dated first treatment fell after the selected three-month day and on or before the selected one-year day.',
        'One-year outcomes for the 25 men whose three-month pad count could not be classified are shown in Supplementary Table S3.',
    ]
    return title, header, rows, notes


def table2():
    a = SEL['availability']['all_early_users']
    w = SEL['availability']['window_closed_before_common_extract']
    rows = []

    def sec(label):
        rows.append(('section', label, '', ''))

    def row(label, key):
        rows.append(('row', label, frac(a[key]['with_year'], a[key]['early_users']), frac(w[key]['with_year'], w[key]['early_users'])))

    rows.append(('row', 'All men using pads', frac(a['with_year'], a['early_users']), frac(w['with_year'], w['early_users'])))
    sec('Pad count at three months')
    for label, key in (('One pad per day', 'group_one'), ('Two or more pads per day', 'group_two_or_more'),
                       ('Count unclear', 'group_nonconflicting_quantity_uncertain'),
                       ('Count conflicting or invalid', 'group_unresolved_quantity_evidence')):
        row(label, key)
    sec('Centre')
    for label, key in (('Bełchatów Hospital, Poland', 'centre_Bełchatów'), ('SalveMedica, Łódź, Poland', 'centre_Salve Medica'),
                       ("Brigham and Women's Hospital, USA", "centre_Brigham and Women's Hospital")):
        row(label, key)
    sec('Year of surgery')
    for label, key in (('2017' + DASH + '2022', 'period_2017-2022'), ('2023', 'period_2023'), ('2024', 'period_2024'),
                       ('2025' + DASH + '2026', 'period_2025-2026')):
        row(label, key)
    sec('Age at surgery')
    for label, key in (('<60 yr', 'age_lt60'), ('60' + DASH + '69 yr', 'age_60_69'), ('≥70 yr', 'age_ge70')):
        row(label, key)
    for pop in (a, w):
        for prefix in ('group_', 'centre_', 'period_', 'age_'):
            keys = [k for k in pop if k.startswith(prefix) and isinstance(pop[k], dict) and 'early_users' in pop[k]]
            if sum(pop[k]['early_users'] for k in keys) != pop['early_users']:
                raise SystemExit(f'availability partition {prefix}')
    sec('With vs without a one-year record, median (IQR)')
    rows.append(('row', 'Age, yr', f"{mediqr(a['age_with_year'])} vs {mediqr(a['age_without_year'])}",
                 f"{mediqr(w['age_with_year'])} vs {mediqr(w['age_without_year'])}"))
    rows.append(('row', 'Three-month assessment, postoperative day', f"{mediqr(a['early_day_with_year'])} vs {mediqr(a['early_day_without_year'])}",
                 f"{mediqr(w['early_day_with_year'])} vs {mediqr(w['early_day_without_year'])}"))
    header = ('Characteristic', 'All men using pads at three months, with a one-year record/total (%)',
              'One-year window closed before extraction, with a one-year record/total (%)')
    title = ('Table 2. Availability of a one-year pad-status record among men using pads about three months after '
             'robot-assisted radical prostatectomy')
    notes = [
        'IQR = interquartile range.',
        'A one-year record was a usable pad-status record between postoperative days 305 and 425. '
        'The one-year window was considered closed when postoperative day 425 fell before 1 April 2026, the first day of the month in which source records were extracted.',
        'Men without a one-year record were not counted as pad-free or as pad users.',
    ]
    return title, header, rows, notes


def write_all(stem, title, header, rows, notes):
    OUT.mkdir(exist_ok=True)
    with (OUT / f'{stem}.csv').open('w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(header)
        for kind, *cells in rows:
            wr.writerow(cells)
    md = [f'**{title}**', '', '| ' + ' | '.join(header) + ' |', '| ' + ' | '.join('---' for _ in header) + ' |']
    for kind, *cells in rows:
        cells = [f'**{cells[0]}**', '', ''] if kind == 'section' else cells
        md.append('| ' + ' | '.join(cells) + ' |')
    md += [''] + notes
    (OUT / f'{stem}.md').write_text('\n'.join(md) + '\n')
    document = docx.Document()
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(20)
    section.top_margin = section.bottom_margin = Mm(20)
    style = document.styles['Normal']
    style.font.name = 'Arial'
    style.font.size = Pt(9)
    p = document.add_paragraph()
    run = p.add_run(title)
    run.bold = True
    table = document.add_table(rows=1, cols=len(header))
    table.style = 'Table Grid'
    for i, h in enumerate(header):
        cell = table.rows[0].cells[i]
        cell.text = ''
        r = cell.paragraphs[0].add_run(h)
        r.bold = True
    for kind, *cells in rows:
        tr = table.add_row().cells
        for i, value in enumerate(cells):
            tr[i].text = ''
            r = tr[i].paragraphs[0].add_run(value)
            if kind == 'section' and i == 0:
                r.bold = True
            if i > 0:
                tr[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    widths = (Mm(70), Mm(50), Mm(50))
    for row_cells in table.rows:
        for i, wdt in enumerate(widths[:len(header)]):
            row_cells.cells[i].width = wdt
    for note in notes:
        document.add_paragraph(note)
    document.core_properties.author = ''
    document.core_properties.title = title.split('. ')[0]
    document.save(OUT / f'{stem}.docx')


if __name__ == '__main__':
    write_all('Table1', *table1())
    write_all('Table2', *table2())
    print('Tables 1 and 2 written')
