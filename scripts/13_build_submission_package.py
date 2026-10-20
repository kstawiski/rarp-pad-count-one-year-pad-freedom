"""Build the manuscript1 submission package from the promoted sources.

Run after promotion (manuscript/manuscript.md, supplement/supplementary-material.md,
submission/reporting-checklist.md, display files in the displays v6 workspace).
Writes submission/package/ (numbered deliverables only), submission/upload/ (the same portal
files without prefixes), submission/review_copies/ (PDF review copies), and the README and
manifest beside the package. Existing output directories must already be backed up.
"""
import csv
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import docx
from docx.enum.section import WD_ORIENT

M1 = Path('/umed-projekty/PROSTATA_JOBCZYK2026_v2/manuscript1')
DISP = Path('/umed-projekty/PROSTATA_JOBCZYK2026_v2/delegated_tasks/manuscript1_displays_v6')
PKG = M1 / 'submission/package'
UPLOAD = M1 / 'submission/upload'
REVIEW = M1 / 'submission/review_copies'
GITHUB = 'https://github.com/kstawiski/rarp-pad-count-one-year-pad-freedom'
GITHUB_TAG = 'v1.1.0'
WORK = M1 / 'submission/build'
REF = M1 / 'submission/reference-style.docx'
PANDOC = '/home/konrad/.local/bin/pandoc'

FILES = [
    ('01_Main_manuscript.docx', 'Main_manuscript.docx', 'Manuscript (title page, abstract, text, legends, declarations, references)'),
    ('02_Supplementary_material.docx', 'Supplementary_material.docx', 'Supplementary material (Methods S1, Figure S1, Tables S1-S9), single file'),
    ('03_Table1.docx', 'Table1.docx', 'Table 1, editable'),
    ('04_Table2.docx', 'Table2.docx', 'Table 2, editable'),
    ('05_Figure1.tiff', 'Figure1.tiff', 'Figure 1, 190 mm wide, 1000 dpi, LZW'),
    ('06_Figure2.tiff', 'Figure2.tiff', 'Figure 2, 190 mm wide, 1000 dpi, LZW'),
    ('07_Reporting_checklist_STROBE_RECORD.docx', 'Reporting_checklist_STROBE_RECORD.docx', 'STROBE and RECORD checklist with locations'),
    ('08_Code_and_aggregate_outputs.zip', 'Code_and_aggregate_outputs.zip', 'Analysis code and aggregate outputs for editors and reviewers (no patient-level data)'),
    ('09_EUROS_authorship_form.docx', 'EUROS_authorship_form.docx', 'EU Open Science Authorship Responsibility, Financial Disclosure and Acknowledgment form (corresponding author)'),
    ('10_ICMJE_disclosure_1_Jobczyk.docx', 'ICMJE_disclosure_1_Jobczyk.docx', 'ICMJE disclosure form, M. Jobczyk'),
    ('10_ICMJE_disclosure_2_Clinton.docx', 'ICMJE_disclosure_2_Clinton.docx', 'ICMJE disclosure form, T.N. Clinton'),
    ('10_ICMJE_disclosure_3_Carvalho.docx', 'ICMJE_disclosure_3_Carvalho.docx', 'ICMJE disclosure form, F.L. De Carvalho'),
    ('10_ICMJE_disclosure_4_Ciechanowski.docx', 'ICMJE_disclosure_4_Ciechanowski.docx', 'ICMJE disclosure form, P. Ciechanowski'),
    ('10_ICMJE_disclosure_5_Piaszczynska.docx', 'ICMJE_disclosure_5_Piaszczynska.docx', 'ICMJE disclosure form, M. Piaszczyńska'),
    ('10_ICMJE_disclosure_6_Mouw.docx', 'ICMJE_disclosure_6_Mouw.docx', 'ICMJE disclosure form, K.W. Mouw'),
    ('10_ICMJE_disclosure_7_Fendler.docx', 'ICMJE_disclosure_7_Fendler.docx', 'ICMJE disclosure form, W. Fendler'),
    ('10_ICMJE_disclosure_8_Stawiski.docx', 'ICMJE_disclosure_8_Stawiski.docx', 'ICMJE disclosure form, K. Stawiski'),
    ('11_Cover_letter.docx', 'Cover_letter.docx', 'Cover letter (optional for the journal; may also be pasted into the submission comments)'),
]
# Form files in submission/forms keep their earlier numbering (11_ authorship form, 12_ ICMJE forms).
FORM_SOURCES = {name: ('11_' if name.startswith('09_') else '12_') + name.split('_', 1)[1]
                for name, _, _ in FILES if name.startswith(('09_', '10_'))}


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def pandoc(src, dst, reference):
    run([PANDOC, str(src), '-f', 'markdown+superscript-auto_identifiers', '-t', 'docx',
         '--reference-doc', str(reference), '-o', str(dst)], cwd=src.parent)


def to_pdf(src, outdir):
    run(['soffice', '-env:UserInstallation=file:///tmp/lo_m1_profile', '--headless', '--convert-to', 'pdf',
         '--outdir', str(outdir), str(src)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def page_reference(name, landscape):
    """The pandoc reference file carries no page size, so A4 and margins are set explicitly."""
    from docx.shared import Mm
    out = WORK / name
    d = docx.Document(REF)
    for s in d.sections:
        s.orientation = WD_ORIENT.LANDSCAPE if landscape else WD_ORIENT.PORTRAIT
        s.page_width, s.page_height = (Mm(297), Mm(210)) if landscape else (Mm(210), Mm(297))
        s.left_margin = s.right_margin = Mm(20 if landscape else 25)
        s.top_margin = s.bottom_margin = Mm(20 if landscape else 25)
    d.save(out)
    return out


def add_line_and_page_numbers(path):
    """Continuous line numbers and a centred page number footer for peer review."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    d = docx.Document(path)
    for s in d.sections:
        sect = s._sectPr
        for old in sect.findall(qn('w:lnNumType')):
            sect.remove(old)
        ln = OxmlElement('w:lnNumType')
        ln.set(qn('w:countBy'), '1')
        ln.set(qn('w:restart'), 'continuous')
        anchor = sect.find(qn('w:pgMar'))
        if anchor is not None:
            anchor.addnext(ln)
        else:
            sect.append(ln)
        para = s.footer.paragraphs[0] if s.footer.paragraphs else s.footer.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fld = OxmlElement('w:fldSimple')
        fld.set(qn('w:instr'), 'PAGE')
        r = OxmlElement('w:r')
        t = OxmlElement('w:t')
        t.text = '1'
        r.append(t)
        fld.append(r)
        para._p.append(fld)
    d.save(path)


def protect_table_rows(path):
    """Stop table rows splitting across pages and repeat header rows on each page."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    d = docx.Document(path)
    for table in d.tables:
        for i, row in enumerate(table.rows):
            tr_pr = row._tr.get_or_add_trPr()
            if tr_pr.find(qn('w:cantSplit')) is None:
                tr_pr.append(OxmlElement('w:cantSplit'))
            if i == 0 and tr_pr.find(qn('w:tblHeader')) is None:
                tr_pr.append(OxmlElement('w:tblHeader'))
    d.save(path)


def scrub_metadata(path):
    d = docx.Document(path)
    cp = d.core_properties
    cp.author = ''
    cp.last_modified_by = ''
    cp.comments = ''
    d.save(path)


def placeholders(paths):
    found = []
    for p in paths:
        text = p.read_text()
        for m in re.finditer(r'\[(?:PLACEHOLDER|AUTHORS?|TODO)\b[^\]]*\]', text):
            line = text.count('\n', 0, m.start()) + 1
            found.append((p.relative_to(M1), line, m.group(0)))
    return found


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for d in (PKG, UPLOAD, REVIEW):
        if d.exists() and any(d.iterdir()):
            sys.exit(f'{d} is not empty; back it up first')
    for d in (PKG, UPLOAD, REVIEW, WORK):
        d.mkdir(parents=True, exist_ok=True)
    if not (WORK / 'manuscript1_code_and_aggregate_outputs.zip').exists():
        sys.exit('code archive missing; build submission/build/manuscript1_code_and_aggregate_outputs.zip first')
    ms = M1 / 'manuscript/manuscript.md'
    supp = M1 / 'supplement/supplementary-material.md'
    checklist = M1 / 'submission/reporting-checklist.md'
    land = page_reference('reference-landscape.docx', True)
    portrait = page_reference('reference-portrait.docx', False)
    pandoc(ms, PKG / '01_Main_manuscript.docx', portrait)
    pandoc(supp, PKG / '02_Supplementary_material.docx', land)
    pandoc(checklist, PKG / '07_Reporting_checklist_STROBE_RECORD.docx', land)
    shutil.copy2(DISP / 'tables/Table1.docx', PKG / '03_Table1.docx')
    shutil.copy2(DISP / 'tables/Table2.docx', PKG / '04_Table2.docx')
    FORMS = M1 / 'submission/forms'
    for name, _, _ in FILES:
        if name.startswith(('09_', '10_')):
            shutil.copy2(FORMS / FORM_SOURCES[name], PKG / name)
    pandoc(M1 / 'submission/cover-letter.md', PKG / '11_Cover_letter.docx', portrait)
    shutil.copy2(DISP / 'figures/Figure1.tiff', PKG / '05_Figure1.tiff')
    shutil.copy2(DISP / 'figures/Figure2.tiff', PKG / '06_Figure2.tiff')
    shutil.copy2(WORK / 'manuscript1_code_and_aggregate_outputs.zip', PKG / '08_Code_and_aggregate_outputs.zip')
    for name in ('01_Main_manuscript.docx', '02_Supplementary_material.docx', '03_Table1.docx', '04_Table2.docx',
                 '07_Reporting_checklist_STROBE_RECORD.docx'):
        scrub_metadata(PKG / name)
    add_line_and_page_numbers(PKG / '01_Main_manuscript.docx')
    protect_table_rows(PKG / '02_Supplementary_material.docx')
    for name in ('01_Main_manuscript.docx', '02_Supplementary_material.docx'):
        to_pdf(PKG / name, REVIEW)
    for pkg_name, up_name, _ in FILES:
        shutil.copy2(PKG / pkg_name, UPLOAD / up_name)

    marks = placeholders([ms, supp, checklist, M1 / 'submission/cover-letter.md'])
    readme = [
        'MANUSCRIPT 1 SUBMISSION PACKAGE',
        'Daily pad count three months after robot-assisted radical prostatectomy predicts pad freedom at one year: a two-country cohort study',
        'Target journal: European Urology Open Science, Original Article',
        '',
        'FILES AND PORTAL MAPPING',
    ]
    for pkg_name, _, role in FILES:
        readme.append(f'  {pkg_name:48s} {role}')
    readme += [
        '',
        'The same portal files, without numeric prefixes, are in submission/upload/.',
        'PDF review copies generated from the DOCX files are in submission/review_copies/; the DOCX files are authoritative.',
        'package_MANIFEST.csv, beside this README, gives the SHA-256 of every file in the package.',
        '',
        f'PLACEHOLDERS TO COMPLETE BEFORE SUBMISSION ({len(marks)})',
    ]
    for rel, line, text in marks:
        readme.append(f'  {rel}:{line}  {text}')
    readme += [
        '',
        'HUMAN STEPS BEFORE UPLOAD',
        '  1. Every author approves the final text, including Maja Piaszczynska, who joined the author list on 20 October 2026.',
        f'  2. The code archive is deposited at {GITHUB} (tag {GITHUB_TAG}); re-tag it if the archive changes.',
        '  3. Check the EU Open Science authorship form (09) and the ICMJE disclosure forms (10); each author confirms their own ICMJE form.',
        '  4. Check and sign the cover letter (11), and confirm on the day of submission the status of the related manuscripts it lists.',
        '  5. Rebuild the DOCX files after any text change and recheck word counts',
        '     (abstract at most 250 words, text at most 2500 words, Take Home Message at most 40 words).',
    ]
    (M1 / 'submission/package_README.txt').write_text('\n'.join(readme) + '\n')
    rows = [(p.name, p.stat().st_size, sha256(p)) for p in sorted(PKG.iterdir())]
    with (M1 / 'submission/package_MANIFEST.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['file', 'bytes', 'sha256'])
        w.writerows(rows)
    with (M1 / 'submission/upload-manifest.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['file', 'bytes', 'sha256'])
        w.writerows((p.name, p.stat().st_size, sha256(p)) for p in sorted(UPLOAD.iterdir()))
    print(f'package built with {len(rows)} files; {len(marks)} placeholders')


if __name__ == '__main__':
    main()
