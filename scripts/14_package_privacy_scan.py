"""Privacy scan of the submission package; reports counts only.

Extracts text from every DOCX (python-docx, including tables and core properties), PDF
(pdftotext) and text file in submission/package, and checks it against the released
pseudonymous patient identifiers loaded inside this process. Identifiers are never
printed or written. It also counts ISO and European calendar dates so that every exact
date in the package can be reviewed against its intended meaning (approval, extraction
or database lock). Raster figures carry only aggregate labels, which were reviewed
visually. OCR is not installed, and the review record says so.
"""
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import docx
import pandas as pd

M1 = Path('/umed-projekty/PROSTATA_JOBCZYK2026_v2/manuscript1')
PKG = M1 / 'submission/package'
RELEASE = Path('/umed-projekty/PROSTATA_JOBCZYK2026_v2/data/prostatectomy_analysis_database_v1.1_2026-09-04')
OUT = M1 / 'review/binary-privacy-review.json'
DATE_PATTERNS = {
    'iso_date': re.compile(r'\b(19|20)\d{2}-\d{2}-\d{2}\b'),
    'european_date': re.compile(r'\b\d{1,2}[./]\d{1,2}[./](19|20)\d{2}\b'),
    'written_date': re.compile(r'\b\d{1,2} (January|February|March|April|May|June|July|August|September|October|November|December) (19|20)\d{2}\b'),
}


def docx_text(path):
    d = docx.Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    cp = d.core_properties
    meta = {k: getattr(cp, k) for k in ('author', 'last_modified_by', 'title', 'subject', 'comments', 'keywords')}
    return '\n'.join(parts), {k: (str(v) if v else '') for k, v in meta.items()}


def main():
    ids = pd.read_csv(RELEASE / 'tables/patient_wide.csv', dtype=str, keep_default_na=False,
                      usecols=['master_patient_id'])['master_patient_id']
    ids = {i.strip() for i in ids if len(i.strip()) > 3}
    records = []
    for path in sorted(PKG.iterdir()):
        entry = {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if path.suffix == '.docx':
            text, meta = docx_text(path)
            entry['method'] = 'python-docx paragraphs, tables and core properties'
            entry['core_properties'] = meta
        elif path.suffix == '.pdf':
            text = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True, check=True).stdout
            entry['method'] = 'pdftotext text layer'
        elif path.suffix in ('.txt', '.md', '.csv'):
            text = path.read_text()
            entry['method'] = 'plain text'
        elif path.suffix in ('.tiff', '.tif', '.png'):
            entry['method'] = 'visual review of rendered aggregate figure; no OCR available'
            entry['identifier_matches'] = 'not machine-checkable'
            records.append(entry)
            continue
        else:
            entry['method'] = 'unsupported'
            records.append(entry)
            continue
        entry['identifier_matches'] = sum(1 for i in ids if i in text)
        entry['date_counts'] = {k: len(p.findall(text)) for k, p in DATE_PATTERNS.items()}
        entry['written_dates'] = sorted({m.group(0) for m in DATE_PATTERNS['written_date'].finditer(text)})
        records.append(entry)
    result = {
        'scanned_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'package': str(PKG),
        'identifier_set_size': len(ids),
        'records': records,
        'total_identifier_matches': sum(r['identifier_matches'] for r in records if isinstance(r.get('identifier_matches'), int)),
        'limitations': ['TIFF figures were reviewed visually, not by OCR, because Tesseract is not installed.',
                        'Exact written dates are listed so their meaning can be checked; they are administrative dates, not patient dates.'],
    }
    OUT.write_text(json.dumps(result, indent=2))
    print(json.dumps({'total_identifier_matches': result['total_identifier_matches'],
                      'written_dates': sorted({d for r in records for d in r.get('written_dates', [])}),
                      'author_metadata': sorted({r['core_properties']['author'] for r in records if 'core_properties' in r})}))
    return 1 if result['total_identifier_matches'] else 0


if __name__ == '__main__':
    sys.exit(main())
