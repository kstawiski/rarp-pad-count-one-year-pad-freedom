"""Source-to-display verifier covering figures, main tables, captions, and S1-S9."""
from pathlib import Path
import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import docx

from centre_labels import DEFAULT_MODE
from extract_display_values import (
    GROUPS,
    NUM,
    OY_CATEGORY_LABELS,
    RENDER_SPEC_REL,
    ROOT,
    RULE_DEFS,
    SOURCES,
    TASK,
    build_all,
    format_value,
    resolve,
)
from occurrence_map import all_text_products, expand

INTERNAL = re.compile(
    r'\bP[0-5]\b|two_or_more|nonconflicting_quantity_uncertain|unresolved_quantity_evidence|M1-OBS|policies\.|payload\.'
)
HISTORY_WORDS = re.compile(
    r'post[\s-]?hoc|prespecified|reference rule|previous|re-?based|completed[\s_-]window|\bv[1-9]\b|Jobczyk|Stawiski|github',
    re.I,
)
BAD_EARLIER = re.compile(r'(?<!vs )\bearlier\b', re.I)
UNMASKED_CENTRES = re.compile(r"Bełchatów|Salve ?Medica|SalveMedica|Łódź|Brigham|Women's", re.I)


def normalize(text: str) -> str:
    return ' '.join(text.split())


def svg_text(path: Path) -> list[str]:
    tree = ET.parse(path)
    return [normalize(''.join(e.itertext())) for e in tree.iter() if e.tag.split('}')[-1] == 'text']


def _docx_text(path: Path) -> str:
    document = docx.Document(path)
    paras = [p.text for p in document.paragraphs if p.text]
    table_chunks = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    # write_docx order: title paragraph (paras[0]), table rows, then notes (paras[1:]).
    chunks = paras[:1] + table_chunks + paras[1:]
    return '\n'.join(chunks)


def _check_clean_prose(path: str, text: str, issues: list[str], allow_completed_window_flow: bool = False):
    if INTERNAL.search(text):
        issues.append(f'{path}: internal code detected: {INTERNAL.search(text).group(0)}')
    # "completed one-year window" in Figure 1 Panel A box & "completed window" cohort rule in flow is distinct from "completed window cohort label"; forbid completed_window / completed-window / post hoc etc.
    cleaned = text.replace('Men with a completed one-year window', '') if allow_completed_window_flow else text
    if HISTORY_WORDS.search(cleaned):
        issues.append(f'{path}: history/author term detected: {HISTORY_WORDS.search(cleaned).group(0)}')
    if BAD_EARLIER.search(cleaned):
        issues.append(f'{path}: forbidden word "earlier" outside "vs earlier"')
    if DEFAULT_MODE == 'masked' and UNMASKED_CENTRES.search(text):
        issues.append(f'{path}: unmasked centre name detected: {UNMASKED_CENTRES.search(text).group(0)}')


def verify(task=TASK, ledger_rows=None, text_overrides=None, svg_overrides=None):
    task = Path(task)
    issues: list[str] = []
    text_overrides = text_overrides or {}
    svg_overrides = svg_overrides or {}

    slots, p, hashes, refs = build_all()
    wanted = expand(slots, p, refs=refs, mode=DEFAULT_MODE)
    expected = [{k: str(v) for k, v in r.items()} for r in wanted]

    if ledger_rows is None:
        with (task / 'data/display_values.csv').open(encoding='utf8') as fh:
            ledger_rows = list(csv.DictReader(fh))

    if ledger_rows != expected:
        issues.append('ledger differs from fresh source-bound extraction')

    # Independent re-verification from raw permitted JSONs & render_spec.json
    source_cache = {}
    hash_cache = {}
    permitted = set(SOURCES) | {RENDER_SPEC_REL}
    for i, row in enumerate(ledger_rows):
        try:
            src = row['source_path']
            if src not in permitted:
                raise ValueError(f'non-permitted source {src}')
            src_file = (task / src) if src == RENDER_SPEC_REL else (ROOT / src)
            if src not in source_cache:
                b = src_file.read_bytes()
                hash_cache[src] = hashlib.sha256(b).hexdigest()
                source_cache[src] = json.loads(b.decode('utf8'))
            if row['source_sha256'] != hash_cache[src]:
                raise ValueError('stale source hash')
            obj = source_cache[src]
            paths = json.loads(row['json_key_path'])
            op = row['operation']
            raw = json.loads(row['raw_source_value'])
            vals = [resolve(obj, path) for path in paths]
            if op in ('sum', 'ratio_pct2', 'ratio_sum_pct2', 'complication_pct', 'difference', 'diff_half', 'ratio_half_pct2', 'two_dec_diff', 'missing_tip_d0'):
                actual = vals
            elif op == 'category_key':
                if raw not in vals[0]:
                    raise ValueError('category key missing')
                actual = raw
            elif op == 'key_token':
                if raw[0] not in vals[0] or raw[1] not in str(raw[0]):
                    raise ValueError('key_token invalid')
                actual = raw
            elif op == 'key_pct':
                if raw[0] not in vals[0] or str(int(round(float(raw[0]) * 100))) != str(raw[1]):
                    raise ValueError('key_pct invalid')
                actual = raw
            elif op == 'sparse_zero':
                if raw[0] != vals[0] or raw[1] in vals[0]:
                    raise ValueError('sparse_zero key unexpectedly present')
                actual = raw
            else:
                actual = vals[0]
            if actual != raw:
                raise ValueError('raw source mismatch')
            digits = None if row['digits'] == '' else int(row['digits'])
            shown = str(raw) if op == 'category_key' else format_value(raw, op, digits)
            if shown != row['value_as_displayed']:
                raise ValueError(f'display rounding mismatch: {shown!r} != {row["value_as_displayed"]!r}')
        except Exception as exc:
            issues.append(f'ledger row {i}: {exc}')

    values = {r['value_as_displayed'] for r in ledger_rows}
    occurrences = []

    def audit_text(path: str, text: str, allow_completed_window_flow: bool = False):
        _check_clean_prose(path, text, issues, allow_completed_window_flow=allow_completed_window_flow)
        actual_tokens = NUM.findall(text)
        bound_tokens = [r['value_as_displayed'] for r in ledger_rows if r['artifact_path'] == path]
        if actual_tokens != bound_tokens:
            issues.append(f'{path}: occurrence-to-source mapping mismatch ({len(actual_tokens)} vs {len(bound_tokens)})')
        for ordinal, m in enumerate(NUM.finditer(text)):
            tok = m.group()
            if tok not in values:
                issues.append(f'{path}: unbound numeric token {tok}')
            occurrences.append({'path': path, 'ordinal': ordinal, 'token': tok})

    # Verify all 27 text products (Table1, Table2, S1..S9, Captions)
    products_map, _ = all_text_products(refs=refs, mode=DEFAULT_MODE)
    for path, want in products_map.items():
        text = text_overrides.get(path, (task / path).read_text(encoding='utf8'))
        audit_text(path, text, allow_completed_window_flow=False)
        if text.replace('\r\n', '\n') != want.replace('\r\n', '\n'):
            issues.append(f'{path}: source-generated product mismatch')

        if path.startswith('captions/'):
            if any(c in text for c in ';—:'):
                issues.append(f'{path}: forbidden caption punctuation (; — :)')
            sentences = re.split(r'(?<=[.!?])\s+', text.strip())
            if any(len(s.split()) > 40 for s in sentences):
                issues.append(f'{path}: caption sentence exceeds 40 words')
            if not text.rstrip().endswith(('.', '?', '!')):
                issues.append(f'{path}: missing terminal punctuation')
            if path in ('captions/Figure1.txt', 'captions/Figure2.txt', 'captions/FigureS1.txt', 'captions/Table1.txt', 'captions/Table2.txt'):
                for tok in ('60–120', '305–425', '90', '365'):
                    if tok not in text:
                        issues.append(f'{path}: missing window item {tok}')
            if path == 'captions/Figure1.txt':
                for req in ('189', '11', 'Wilson score', 'bootstrap', 'unrounded proportions',
                            'Differences were estimated separately within each country.',
                            'No between-country contrast or interaction was estimated.'):
                    if req not in text:
                        issues.append(f'{path}: missing required caption element {req!r}')
            elif path == 'captions/Figure2.txt':
                for req in ('75–105', '335–395', 'bootstrap', 'The least favourable split of unclassifiable counts has a Newcombe hybrid score interval.', 'unrounded proportions', 'tipping point'):
                    if req not in text:
                        issues.append(f'{path}: missing required caption element {req!r}')
            elif path == 'captions/FigureS1.txt':
                for req in ('day 0', '150–210', '670–790', '180', '730'):
                    if req not in text:
                        issues.append(f'{path}: missing required caption element {req!r}')
            elif path == 'captions/Table1.txt':
                for req in ('189', 'interquartile range', 'rounded half up', '24'):
                    if req not in text:
                        issues.append(f'{path}: missing required caption element {req!r}')
            elif path == 'captions/Table2.txt':
                for req in ('364', '151', '150', '1', '425', 'April 2026'):
                    if req not in text:
                        issues.append(f'{path}: missing required caption element {req!r}')

    # Verify DOCX numeric parity & centre masking
    if not text_overrides:
        for stem in ('Table1', 'Table2'):
            docx_p = task / f'tables/{stem}.docx'
            if not docx_p.is_file():
                issues.append(f'tables/{stem}.docx missing')
            else:
                dtxt = _docx_text(docx_p)
                _check_clean_prose(f'tables/{stem}.docx', dtxt, issues)
                md_nums = NUM.findall((task / f'tables/{stem}.md').read_text(encoding='utf8'))
                dx_nums = NUM.findall(dtxt)
                if dx_nums != md_nums:
                    issues.append(f'tables/{stem}.docx: numeric parity mismatch with Markdown ({len(dx_nums)} vs {len(md_nums)})')

    # Verify SVG figures (Figure1, Figure2, FigureS1)
    for name in ('Figure1', 'Figure2', 'FigureS1'):
        path = f'figures/{name}.svg'
        svg_file = task / path
        texts = svg_overrides.get(name, svg_text(svg_file))
        joined = '\n'.join(texts)
        audit_text(path, joined, allow_completed_window_flow=(name == 'Figure1'))
        flat = normalize(joined)

        if name == 'Figure1':
            wanted_labels = [
                'Patients in the database', 'Non-robotic procedures',
                'Robot-assisted radical prostatectomy', 'One-year window not ended before data extraction',
                'Men with a completed one-year window', 'No three-month assessment',
                'Pad status recorded at about three months', 'Pad-free at three months',
                'Using pads at about three months', 'No one-year record',
                'Pad status recorded at about one year', 'Unclear or conflicting count',
                'One pad vs two or more',
                'No pads', 'One pad', 'Two pads', 'Three or more pads',
                OY_CATEGORY_LABELS['pad_free'], OY_CATEGORY_LABELS['one'],
                OY_CATEGORY_LABELS['two_or_more'], OY_CATEGORY_LABELS['not_classifiable'],
                'Pad-free, n/N % (95% CI)',
                'C Documented pad freedom at one year within each country',
                'D Difference within each population, one pad minus two or more pads',
            ]
            for lbl in wanted_labels:
                if lbl not in flat:
                    issues.append(f'{path}: missing label {lbl!r}')
            if 'Pad-free, n/N % (95% CI)' not in texts:
                issues.append(f'{path}: Panel B missing Pad-free right-column header')
            if texts.count('n/N % (95% CI)') != 1:
                issues.append(f'{path}: expected exactly one bare "n/N % (95% CI)" header (Panel C only), found {texts.count("n/N % (95% CI)")}')
            if '−20' not in flat:
                issues.append(f'{path}: signed difference axis missing −20 tick')
            if any('%' in t for t in texts if '1497' in t or '1397' in t or '1022' in t or '364' in t):
                issues.append(f'{path}: Panel A must not carry percentage annotations')

            # Panel B header and Panel C geometry check (Poland & US 3 rows below respective subheadings, strictly between Panel C and Panel D titles)
            if name not in svg_overrides:
                root = ET.parse(svg_file).getroot()
                all_el = [
                    (normalize(''.join(e.itertext())), float(e.get('x')), float(e.get('y')))
                    for e in root.iter() if e.tag.split('}')[-1] == 'text'
                ]
                y_b = next((y for t, _, y in all_el if t.startswith('B Pad use at one year')), None)
                y_c = next((y for t, _, y in all_el if t.startswith('C Documented pad freedom')), None)
                y_d = next((y for t, _, y in all_el if t.startswith('D Difference within each population')), None)
                if y_b is None or y_c is None or y_d is None:
                    issues.append(f'{path}: Panel B/C/D titles missing')
                else:
                    panel_b_texts = [t for t, _, y in all_el if y_b < y < y_c]
                    panel_c_texts = [t for t, _, y in all_el if y_c < y < y_d]
                    if 'Pad-free, n/N % (95% CI)' not in panel_b_texts:
                        issues.append(f'{path}: Panel B missing header "Pad-free, n/N % (95% CI)"')
                    if 'n/N % (95% CI)' in panel_b_texts:
                        issues.append(f'{path}: stale header "n/N % (95% CI)" present in Panel B')
                    if 'n/N % (95% CI)' not in panel_c_texts:
                        issues.append(f'{path}: Panel C missing header "n/N % (95% CI)"')
                    left_rows, subs = [], {}
                    for t, x, y in all_el:
                        if not (y_c < y < y_d) or x >= 150.0:
                            continue
                        if t in ('Poland', 'United States'):
                            subs.setdefault(t, []).append(y)
                        elif t in ('Overall', 'One pad', 'Two or more pads'):
                            left_rows.append((t, y))
                    if 'Poland' in subs and 'United States' in subs:
                        y_pl, y_us = min(subs['Poland']), min(subs['United States'])
                        pl_rows = [y for _, y in left_rows if y_pl < y < y_us]
                        us_rows = [y for _, y in left_rows if y > y_us]
                        if len(pl_rows) != 3 or len(us_rows) != 3:
                            issues.append(f'{path}: Panel C rows not grouped 3 below Poland and 3 below US ({len(pl_rows)}, {len(us_rows)})')
                    else:
                        issues.append(f'{path}: Panel C country subheadings missing')

        elif name == 'Figure2':
            for lbl in [
                'Assessment selection', 'Pad-count measurement', 'Follow-up and missing records', 'Adjustment',
                'Main analysis', 'Conflicting windows excluded', 'First usable assessment',
                'Narrower assessment windows', 'Uncertain assessment dates excluded',
                'Exact counts only', 'EPIC questionnaire counts excluded',
                'Unclassifiable counts as one pad', 'Unclassifiable counts as two or more',
                'Unclassifiable counts, least favourable split', '54/124 vs 28/89 12 (−1.2 to 24)',
                'Later operations included', 'One-year window extended to day 545', 'Weighted for record availability',
                'Clinical, no documented interim RT or ADT',
                'B Missing one-year outcomes', 'Equal pad freedom in both unobserved groups',
                'Unobserved men resemble observed men', 'Tipping point',
            ]:
                if lbl not in flat:
                    issues.append(f'{path}: missing label {lbl!r}')
            if 'Operated 2017–2024' not in flat and p.get('include_era_2017_2024'):
                issues.append(f'{path}: missing Operated 2017–2024 sensitivity row')
            if 'Reference rule' in flat:
                issues.append(f'{path}: stale label "Reference rule" present')
            if 'Clinical, no interim RT or ADT' in flat:
                issues.append(f'{path}: stale label "Clinical, no interim RT or ADT" present')

        elif name == 'FigureS1':
            for lbl in ['Surgery (day 0)', 'Nearest day 90', 'Nearest day 365', 'Nearest day 180', 'Nearest day 730']:
                if lbl not in flat:
                    issues.append(f'{path}: missing label {lbl!r}')

        geo = json.loads((task / f'figures/{name}.geometry.json').read_text(encoding='utf8'))
        if geo['render_sha256'] != hashlib.sha256((task / f'figures/{name}.png').read_bytes()).hexdigest():
            issues.append(f'{name}: stale raster geometry binding')
        expected_panels = {'Figure1': 4, 'Figure2': 2, 'FigureS1': 2}[name]
        if len(geo['panels']) != expected_panels:
            issues.append(f'{name}: expected {expected_panels} child panels, got {len(geo["panels"])}')
        if geo.get('width_mm') != 180:
            issues.append(f'{name}: width_mm {geo.get("width_mm")} != 180')

    # Precision check: no fixed two-decimal contrast labels and no fractional whole-year medians in Table 1 age/day or Table 2
    for c in p['contrasts'] + [r for sec in p['figure2_sections'] for r in sec['rows']]:
        nums = NUM.findall(c['text'])
        if any(re.fullmatch(r'−?\d+\.\d{2}', n) for n in nums):
            issues.append(f'fixed two-decimal label in {c["label"]}: {c["text"]}')

    # Check Table 2 block sums in Table2.csv
    with (task / 'tables/Table2.csv').open(encoding='utf8') as fh:
        t2_rows = list(csv.reader(fh))
    t2_map = {r[0]: r[1] for r in t2_rows if len(r) == 2}
    if text_overrides.get('tables/Table2.md'):
        # Parse overridden Table2.md fractions directly if mutated in tests
        for m_all in re.findall(r'\|\s*([^|]+?)\s*\|\s*(\d+/\d+\s*\([^)]+\))\s*\|', text_overrides['tables/Table2.md']):
            t2_map[m_all[0].strip()] = m_all[1].strip()
    m_ov = re.match(r'^(\d+)/(\d+)', t2_map.get('All men using pads', ''))
    if m_ov:
        ov_w, ov_t = int(m_ov.group(1)), int(m_ov.group(2))
        for group_name, keys in [
            ('pad_count', ('One pad per day', 'Two or more pads per day', 'Count unclear', 'Count conflicting or invalid')),
            ('year', ('2017–2022', '2023', '2024', '2025')),
            ('age', ('<60 yr', '60–69 yr', '≥70 yr')),
        ]:
            sw, st = 0, 0
            for k in keys:
                mm = re.match(r'^(\d+)/(\d+)', t2_map.get(k, ''))
                if mm:
                    sw += int(mm.group(1)); st += int(mm.group(2))
            if (sw, st) != (ov_w, ov_t):
                issues.append(f'Table2 {group_name} partition sums {(sw, st)} != {(ov_w, ov_t)}')

    return {
        'verification_passed': not issues,
        'errors': issues,
        'numeric_slots': len(slots),
        'numeric_occurrences': len(ledger_rows),
        'occurrences': occurrences,
        'acceptance_status': 'PASS' if not issues else 'FAIL',
        'unresolved': p['unresolved'],
    }


def main():
    result = verify()
    occ = result.pop('occurrences')
    with (TASK / 'data/number_occurrences.csv').open('w', newline='', encoding='utf8') as fh:
        w = csv.DictWriter(fh, fieldnames=['path', 'ordinal', 'token'])
        w.writeheader()
        w.writerows(occ)
    (TASK / 'logs/VERIFY.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result, indent=2))
    return 0 if result['verification_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
