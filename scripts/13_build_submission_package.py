"""Build the manuscript1 submission package from the promoted sources.

Run after promotion (manuscript/manuscript.md, supplement/supplementary-material.md,
submission/reporting-checklist.md, display files in the displays v6 workspace).
Writes submission/package/ (numbered files, review PDFs, README, manifest) and
submission/upload/ (portal files only). Existing directories must already be backed up.
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
    ('10_Code_and_aggregate_outputs.zip', 'Code_and_aggregate_outputs.zip', 'Analysis code and aggregate outputs for editors and reviewers (no patient-level data)'),
]


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
        for m in re.finditer(r'\[PLACEHOLDER:[^\]]*\]', text):
            line = text.count('\n', 0, m.start()) + 1
            found.append((p.relative_to(M1), line, m.group(0)))
    return found


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for d in (PKG, UPLOAD):
        if d.exists() and any(d.iterdir()):
            sys.exit(f'{d} is not empty; back it up first')
    for d in (PKG, UPLOAD, WORK):
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
    shutil.copy2(DISP / 'figures/Figure1.tiff', PKG / '05_Figure1.tiff')
    shutil.copy2(DISP / 'figures/Figure2.tiff', PKG / '06_Figure2.tiff')
    shutil.copy2(WORK / 'manuscript1_code_and_aggregate_outputs.zip', PKG / '10_Code_and_aggregate_outputs.zip')
    for name in ('01_Main_manuscript.docx', '02_Supplementary_material.docx', '03_Table1.docx', '04_Table2.docx',
                 '07_Reporting_checklist_STROBE_RECORD.docx'):
        scrub_metadata(PKG / name)
    add_line_and_page_numbers(PKG / '01_Main_manuscript.docx')
    protect_table_rows(PKG / '02_Supplementary_material.docx')
    for name in ('01_Main_manuscript.docx', '02_Supplementary_material.docx'):
        to_pdf(PKG / name, PKG)
    for pkg_name, up_name, _ in FILES:
        shutil.copy2(PKG / pkg_name, UPLOAD / up_name)

    marks = placeholders([ms, supp])
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
        '  01_Main_manuscript.pdf                           Review copy generated from the DOCX (the DOCX is authoritative)',
        '  02_Supplementary_material.pdf                    Review copy generated from the DOCX',
        '  08_Revision_notes.md                             Point-by-point record of the final review (not for upload)',
        '  09_MANIFEST.csv                                  SHA-256 of every file in this folder',
        '',
        'The same portal files, without numeric prefixes, are in submission/upload/ in the workspace.',
        '',
        f'PLACEHOLDERS TO COMPLETE BEFORE SUBMISSION ({len(marks)})',
    ]
    for rel, line, text in marks:
        readme.append(f'  {rel}:{line}  {text}')
    readme += [
        '',
        'HUMAN STEPS BEFORE UPLOAD',
        '  1. Every author approves the final text and the placeholder entries.',
        '  2. Deposit 10_Code_and_aggregate_outputs.zip in a public repository (for example Zenodo) and insert the DOI.',
        '  3. Complete the EU Open Science authorship form and ICMJE disclosure forms.',
        '  4. Write and sign the cover letter.',
        '  5. Rebuild the DOCX files after filling placeholders and recheck word counts',
        '     (abstract at most 250 words, text at most 2500 words).',
    ]
    (PKG / '00_README.txt').write_text('\n'.join(readme) + '\n')
    notes = M1 / 'review/final-review-revision-notes.md'
    if notes.exists():
        shutil.copy2(notes, PKG / '08_Revision_notes.md')
    rows = [(p.name, p.stat().st_size, sha256(p)) for p in sorted(PKG.iterdir()) if p.name != '09_MANIFEST.csv']
    with (PKG / '09_MANIFEST.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['file', 'bytes', 'sha256'])
        w.writerows(rows)
    with (M1 / 'submission/upload-manifest.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['file', 'bytes', 'sha256'])
        w.writerows((p.name, p.stat().st_size, sha256(p)) for p in sorted(UPLOAD.iterdir()))
    print(f'package built with {len(rows) + 1} files; {len(marks)} placeholders')


if __name__ == '__main__':
    main()
