"""Extract aggregate-only completed-window study values. Never load patient-level sources."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import exp
from pathlib import Path
import csv
import hashlib
import json
import re

TASK = Path(__file__).resolve().parents[1]


def _find_root() -> Path:
    import os
    import time
    marker = Path('manuscript1/evidence/OBSERVED_STATUS_ESTIMATES_COMPLETED_WINDOW.json')
    for attempt in range(4):
        for parent in Path(__file__).resolve().parents:
            if (parent / marker).is_file():
                return parent
        fallback = Path('/umed-projekty/PROSTATA_JOBCZYK2026_v2')
        ev_dir = fallback / 'manuscript1/evidence'
        if os.path.isdir(ev_dir):
            os.listdir(ev_dir)
        if (fallback / marker).is_file():
            return fallback
        if attempt < 3:
            time.sleep(0.4)
    raise FileNotFoundError(f'Could not locate evidence root containing {marker}')


ROOT = _find_root()
SOURCES = [
    'manuscript1/evidence/OBSERVED_STATUS_ESTIMATES_COMPLETED_WINDOW.json',
    'manuscript1/evidence/OBSERVED_ASSESSMENT_DERIVATION_COMPLETED_WINDOW.json',
    'manuscript1/evidence/POSTHOC_TWOGROUP_COMPLETED_WINDOW.json',
    'manuscript1/evidence/SELECTION_FOLLOWUP_SENSITIVITY_COMPLETED_WINDOW.json',
    'manuscript1/evidence/CLINICAL_ADJUSTMENT_COMPLETED_WINDOW.json',
    'manuscript1/evidence/STRENGTHENING_ANALYSES_COMPLETED_WINDOW.json',
    'manuscript1/evidence/ONE_YEAR_PAD_CATEGORY_COMPLETED_WINDOW.json',
    'manuscript1/evidence/DOCUMENTATION_AND_TIMING_COMPLETED_WINDOW.json',
]
RENDER_SPEC_REL = 'data/render_spec.json'

GROUPS = [
    'One pad per day',
    'Two or more pads per day',
    'Unclear count',
    'Conflicting count',
]
KEYS = [
    'one',
    'two_or_more',
    'nonconflicting_quantity_uncertain',
    'unresolved_quantity_evidence',
]
RULE_DEFS = [
    ('P0', 'Main analysis', 'Main analysis'),
    ('P1', 'Conflicting windows excluded', 'Conflicting windows excluded'),
    ('P2', 'First usable assessment', 'First usable assessment'),
    ('P3', 'Narrower assessment windows', 'Narrower windows'),
    ('P4', 'Uncertain assessment dates excluded', 'Uncertain assessment dates excluded'),
    ('P5', 'Recorded 3- and 12-month milestones', 'Recorded 3- and 12-month milestones'),
]
OY_CATEGORY_KEYS = ['pad_free', 'one', 'two_or_more', 'not_classifiable']
OY_CATEGORY_LABELS = {
    'pad_free': 'Pad-free',
    'one': 'Using pads, at most one per day',
    'two_or_more': 'More than one pad per day',
    'not_classifiable': 'Pads, count not recorded',
}

DASH = '–'
MINUS = '−'
NUM = re.compile(r'(?<![A-Za-z])−?\d+(?:\.\d+)?')


@dataclass(frozen=True)
class Bound:
    """Text paired with its ordered ledger slot indices."""

    text: str
    slots: list[int]


def cat(*parts: Bound | str) -> Bound:
    """Concatenate Bound objects and plain strings; reject any unbound numeric token."""
    texts: list[str] = []
    slots: list[int] = []
    for part in parts:
        if isinstance(part, Bound):
            texts.append(part.text)
            slots.extend(part.slots)
        elif isinstance(part, str):
            leftover = NUM.findall(part)
            if leftover:
                raise ValueError(f'Unbound numeric token(s) {leftover!r} in literal {part!r}')
            texts.append(part)
        else:
            raise TypeError(f'Expected Bound or str, got {type(part).__name__}')
    return Bound(''.join(texts), slots)


def resolve(obj, path):
    for key in path:
        obj = obj[key]
    return obj


def _decimal(v) -> Decimal:
    return Decimal(repr(float(v))) if isinstance(v, float) else Decimal(str(v))


def format_sig2(value: Decimal) -> str:
    """Two significant figures, rounded half up, with Unicode minus."""
    if value == 0:
        return '0'
    rounded = value.quantize(
        Decimal(1).scaleb(value.copy_abs().adjusted() - 1),
        rounding=ROUND_HALF_UP,
    )
    if rounded == 0:
        return '0'
    places = max(0, 1 - rounded.copy_abs().adjusted())
    return format(rounded, f'.{places}f').replace('-', MINUS)


def _sig1(value: Decimal) -> str:
    if value == 0:
        return '0'
    adj = value.copy_abs().adjusted()
    r = value.quantize(Decimal(1).scaleb(adj), rounding=ROUND_HALF_UP)
    if r.copy_abs().adjusted() > adj:
        r = value.quantize(Decimal(1).scaleb(adj + 1), rounding=ROUND_HALF_UP)
    return format(r, 'f').replace('-', MINUS)


def _fixed(value: Decimal, digits: int) -> str:
    q = Decimal('1') if digits == 0 else Decimal(f"0.{'0' * (digits - 1)}1")
    return format(value.quantize(q, rounding=ROUND_HALF_UP), 'f').replace('-', MINUS)


def format_value(raw, operation='identity', digits=None) -> str:
    """Format raw JSON value(s) deterministically using declared rounding rules."""
    if operation == 'identity':
        if isinstance(raw, bool):
            raise TypeError(f'Unexpected bool for identity formatting: {raw}')
        if digits is not None:
            return _fixed(_decimal(raw), int(digits))
        if isinstance(raw, int):
            return str(raw).replace('-', MINUS)
        return f'{raw:g}'.replace('-', MINUS)
    if operation == 'whole':
        val = int(_decimal(raw).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return str(val).replace('-', MINUS)
    if operation == 'one_dec':
        return _fixed(_decimal(raw), 1)
    if operation == 'two_dec':
        return _fixed(_decimal(raw), 2)
    if operation == 'two_dec_diff':
        return _fixed(_decimal(raw[0]) - _decimal(raw[1]), 2)
    if operation == 'exp_two_dec':
        return _fixed(Decimal(repr(exp(float(raw)))), 2)
    if operation == 'sig2':
        return format_sig2(_decimal(raw))
    if operation == 'pct2':
        return format_sig2(_decimal(raw) * Decimal(100))
    if operation == 'percent':
        val = int((_decimal(raw) * Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return str(val)
    if operation == 'ratio_pct2':
        return format_sig2(_decimal(raw[0]) / _decimal(raw[1]) * Decimal(100))
    if operation == 'ratio_sum_pct2':
        return format_sig2(_decimal(raw[0]) / sum(_decimal(x) for x in raw[1:]) * Decimal(100))
    if operation == 'complication_pct':
        return format_sig2(_decimal(raw[0]) / (_decimal(raw[0]) + _decimal(raw[1])) * Decimal(100))
    if operation == 'num1':
        v = float(raw)
        if v == int(v):
            return str(int(v)).replace('-', MINUS)
        return _fixed(_decimal(raw), 1)
    if operation == 'sum':
        total = sum(raw)
        return str(total).replace('-', MINUS) if isinstance(total, int) else f'{total:g}'.replace('-', MINUS)
    if operation == 'difference':
        diff = raw[0] - raw[1]
        return str(diff).replace('-', MINUS) if isinstance(diff, int) else f'{diff:g}'.replace('-', MINUS)
    if operation == 'diff_half':
        k = len(raw) // 2
        diff = sum(raw[:k]) - sum(raw[k:])
        return str(diff).replace('-', MINUS) if isinstance(diff, int) else f'{diff:g}'.replace('-', MINUS)
    if operation == 'ratio_half_pct2':
        k = len(raw) // 2
        return format_sig2(sum(_decimal(x) for x in raw[:k]) / sum(_decimal(x) for x in raw[k:]) * Decimal(100))
    if operation == 'p_display':
        p = float(raw)
        if p < 0.001:
            return '0.001'
        if p < 0.01:
            return _sig1(_decimal(raw))
        return format_sig2(_decimal(raw))
    if operation == 'missing_tip_d0':
        n1, e1, n2, e2, obs2 = (float(x) for x in raw)
        d0 = e1 / n1 - (e2 + (n2 - obs2) * (e2 / obs2)) / n2
        return format_sig2(_decimal(d0) * Decimal(100))
    if operation == 'date_year':
        return str(int(str(raw).split('-')[0]))
    if operation == 'date_day':
        return str(int(str(raw).split('-')[2]))
    if operation in ('category_key', 'key_token', 'key_pct'):
        return str(raw[1] if operation in ('key_token', 'key_pct') else raw)
    if operation == 'sparse_zero':
        if raw[1] in raw[0]:
            raise ValueError(f'Expected missing key {raw[1]!r} for sparse_zero')
        return '0'
    raise ValueError(f'Unknown operation: {operation}')


MULTI_PATH_OPS = {'sum', 'ratio_pct2', 'ratio_sum_pct2', 'complication_pct', 'difference', 'diff_half', 'ratio_half_pct2', 'two_dec_diff', 'missing_tip_d0'}


def build_all():
    """Extract all study and rendering slots and return (ledger, payload, hashes, refs)."""
    source = [json.loads((ROOT / f).read_text(encoding='utf8')) for f in SOURCES]
    hashes = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in SOURCES}
    spec_path = TASK / RENDER_SPEC_REL
    spec = json.loads(spec_path.read_text(encoding='utf8'))
    spec_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()

    ledger: list[dict] = []
    payload: dict = {}

    def add_slot(display, part, label, si, path, op='identity', digits=None) -> Bound:
        if si == 'spec':
            paths = [list(path)]
            raw = resolve(spec, path)
            src_path = RENDER_SPEC_REL
            src_sha = spec_sha
            role = 'design_constant'
        else:
            paths = [list(p) for p in path] if op in MULTI_PATH_OPS else [list(path)]
            vals = [resolve(source[si], p) for p in paths]
            raw = vals if op in MULTI_PATH_OPS else vals[0]
            src_path = SOURCES[si]
            src_sha = hashes[src_path]
            role = 'study'
        text = format_value(raw, op, digits)
        idx = len(ledger)
        ledger.append(
            dict(
                display=display,
                part=part,
                label=label,
                value_as_displayed=text,
                source_path=src_path,
                source_sha256=src_sha,
                json_key_path=json.dumps(paths),
                raw_source_value=json.dumps(raw),
                operation=op,
                digits='' if digits is None else digits,
                role=role,
            )
        )
        return Bound(text, [idx])

    def keytok(display, part, label, si, dict_path, key_name, token, op='key_token') -> Bound:
        container = resolve(source[si], dict_path)
        if key_name not in container:
            raise KeyError((si, dict_path, key_name))
        if op == 'key_token' and str(token) not in str(key_name):
            raise KeyError((si, dict_path, key_name, token))
        if op == 'key_pct' and str(int(round(float(key_name) * 100))) != str(token):
            raise ValueError((key_name, token))
        raw = [key_name, str(token)]
        idx = len(ledger)
        ledger.append(
            dict(
                display=display,
                part=part,
                label=label,
                value_as_displayed=str(token),
                source_path=SOURCES[si],
                source_sha256=hashes[SOURCES[si]],
                json_key_path=json.dumps([list(dict_path)]),
                raw_source_value=json.dumps(raw),
                operation=op,
                digits='',
                role='study',
            )
        )
        return Bound(str(token), [idx])

    def const(display, part, label, *path) -> Bound:
        return add_slot(display, part, label, 'spec', list(path), 'identity')

    def ci_range(lo_b: Bound, hi_b: Bound) -> Bound:
        neg = lo_b.text.startswith(MINUS) or hi_b.text.startswith(MINUS)
        return cat(lo_b, ' to ' if neg else DASH, hi_b)

    # ------------------------------------------------------------------
    # Shared metadata & constants
    # ------------------------------------------------------------------
    conf95 = add_slot('Captions', 'methods', 'Confidence level', 0, ['estimand', 'confidence'], 'percent')
    draws2000 = add_slot('Captions', 'methods', 'Bootstrap draws', 0, ['estimand', 'bootstrap_resamples'])
    extract_year = add_slot('Captions', 'methods', 'Extract year', 0, ['cohort', 'common_extract_date'], 'date_year')
    extract_day = add_slot('Captions', 'methods', 'Extract day', 0, ['cohort', 'common_extract_date'], 'date_day')
    close_day = add_slot('Captions', 'methods', 'Window close day', 0, ['cohort', 'year_window_close_day'])
    recent_start_yr = add_slot('Captions', 'methods', 'Recent period start year', 2, ['cohort', 'model_recent_period_start_year'])

    yr_2014 = keytok('Captions', 'methods', 'Year 2014 key token', 3, ['robotic_early_assessment', 'with_early_assessment', 'operative_period'], '2014-2022', '2014')
    yr_2017 = keytok('Captions', 'methods', 'Year 2017 key token', 1, ['p0_reference', 'coarse_surgery_year_counts'], '2017', '2017')
    yr_2019 = keytok('Captions', 'methods', 'Year 2019 key token', 1, ['p0_reference', 'coarse_surgery_year_counts'], '2019', '2019')
    yr_2020 = keytok('Captions', 'methods', 'Year 2020 key token', 1, ['p0_reference', 'coarse_surgery_year_counts'], '2020', '2020')
    yr_2021 = keytok('Captions', 'methods', 'Year 2021 key token', 1, ['p0_reference', 'coarse_surgery_year_counts'], '2021', '2021')
    yr_2022 = keytok('Captions', 'methods', 'Year 2022 key token', 1, ['p0_reference', 'coarse_surgery_year_counts'], '2022', '2022')
    yr_2023 = keytok('Captions', 'methods', 'Year 2023 key token', 1, ['p0_reference', 'coarse_surgery_year_counts'], '2023', '2023')
    yr_2024 = keytok('Captions', 'methods', 'Year 2024 key token', 1, ['p0_reference', 'coarse_surgery_year_counts'], '2024', '2024')
    yr_2025 = keytok('Captions', 'methods', 'Year 2025 key token', 1, ['p0_reference', 'coarse_surgery_year_counts'], '2025', '2025')
    age_60_lt = keytok('Captions', 'methods', 'Age under 60 key token', 3, ['availability', 'all_early_users'], 'age_lt60', '60')
    age_60_mid = keytok('Captions', 'methods', 'Age 60 lower key token', 3, ['availability', 'all_early_users'], 'age_60_69', '60')
    age_69_mid = keytok('Captions', 'methods', 'Age 69 upper key token', 3, ['availability', 'all_early_users'], 'age_60_69', '69')
    age_70_ge = keytok('Captions', 'methods', 'Age 70+ key token', 3, ['availability', 'all_early_users'], 'age_ge70', '70')

    meta_b = {
        'confidence': conf95, 'draws': draws2000,
        'extract_year': extract_year, 'extract_day': extract_day,
        'close_day': close_day, 'recent_start_yr': recent_start_yr,
        'yr_2014': yr_2014, 'yr_2017': yr_2017, 'yr_2019': yr_2019, 'yr_2020': yr_2020,
        'yr_2021': yr_2021, 'yr_2022': yr_2022, 'yr_2023': yr_2023, 'yr_2024': yr_2024, 'yr_2025': yr_2025,
        'age_lt60': age_60_lt, 'age_60': age_60_mid, 'age_69': age_69_mid, 'age_ge70': age_70_ge,
        'zero_day': const('Captions', 'methods', 'Surgery day 0', 'zero_day'),
        'milestone_3': const('Captions', 'methods', 'Three-month milestone numeral', 'milestone_months', 0),
        'milestone_12': const('Captions', 'methods', 'Twelve-month milestone numeral', 'milestone_months', 1),
        'epic_lo': const('Captions', 'methods', 'EPIC-CP min', 'epic_cp_scale', 0),
        'epic_hi': const('Captions', 'methods', 'EPIC-CP max', 'epic_cp_scale', 1),
        'comp_30': const('Captions', 'methods', 'Complication 30 days', 'complication_days', 0),
        'comp_90': const('Captions', 'methods', 'Complication 90 days', 'complication_days', 1),
        'stage_max': const('Captions', 'methods', 'Pathological stage max 4', 'stage_max'),
        'asa_2': const('Captions', 'methods', 'ASA class 2', 'asa_classes', 0),
        'asa_3': const('Captions', 'methods', 'ASA class 3', 'asa_classes', 1),
        'asa_4': const('Captions', 'methods', 'ASA class 4', 'asa_classes', 2),
        'age_years': const('Captions', 'methods', 'Covariate scale 10 yr', 'covariate_scales', 'age_years'),
        'age_center': const('Captions', 'methods', 'Covariate center 65 yr', 'covariate_scales', 'age_center'),
        'day_step': const('Captions', 'methods', 'Covariate scale 30 days', 'covariate_scales', 'day_step'),
        'bmi_step': const('Captions', 'methods', 'Covariate scale 5 kg/m2', 'covariate_scales', 'bmi_step'),
        'bmi_center': const('Captions', 'methods', 'Covariate center 28 kg/m2', 'covariate_scales', 'bmi_center'),
        'vol_step': const('Captions', 'methods', 'Covariate scale 10 ml', 'covariate_scales', 'volume_step'),
        'vol_center': const('Captions', 'methods', 'Covariate center 40 ml', 'covariate_scales', 'volume_center'),
        'surg_dbl': const('Captions', 'methods', 'Surgeon doubling 2', 'covariate_scales', 'surgeon_doubling'),
        'surg_center': const('Captions', 'methods', 'Surgeon center 32', 'covariate_scales', 'surgeon_center'),
        'cal_slope_ideal': const('Captions', 'methods', 'Calibration slope ideal 1', 'calibration_slope_ideal'),
        'one_pt': const('Captions', 'methods', 'One-point difference note', 'one_point_rounding'),
        'unit_step': const('Captions', 'methods', 'Unit square 1-point step', 'unit_square_step_pct'),
        'pct_100': const('Captions', 'methods', 'Percentage 100', 'percent_100'),
        'tbl_1': const('Captions', 'methods', 'Table 1 number', 'table_numbers', 0),
        'tbl_2': const('Captions', 'methods', 'Table 2 number', 'table_numbers', 1),
        'isup_1': keytok('Captions', 'methods', 'ISUP grade 1', 2, ['table1_by_group', 'isup_grade_preop', 'one'], '1.0', '1'),
        'isup_2': keytok('Captions', 'methods', 'ISUP grade 2', 2, ['table1_by_group', 'isup_grade_preop', 'one'], '2.0', '2'),
        'isup_3': keytok('Captions', 'methods', 'ISUP grade 3', 2, ['table1_by_group', 'isup_grade_preop', 'one'], '3.0', '3'),
        'isup_4': keytok('Captions', 'methods', 'ISUP grade 4', 2, ['table1_by_group', 'isup_grade_preop', 'one'], '4.0', '4'),
        'isup_5': keytok('Captions', 'methods', 'ISUP grade 5', 2, ['table1_by_group', 'isup_grade_preop', 'one'], '5.0', '5'),
    }
    for w in ('early', 'year', 'six', 'two_year'):
        meta_b[f'{w}_0'] = add_slot('Captions', 'methods', f'{w} window lower endpoint', 1, ['p0_reference', 'window_diagnostics', w, 'window_days', 0])
        meta_b[f'{w}_1'] = add_slot('Captions', 'methods', f'{w} window upper endpoint', 1, ['p0_reference', 'window_diagnostics', w, 'window_days', 1])
        meta_b[f'{w}_target'] = add_slot('Captions', 'methods', f'{w} window target day', 1, ['p0_reference', 'window_diagnostics', w, 'target_day'])
    for w in ('early', 'year'):
        meta_b[f'narrow_{w}_0'] = add_slot('Figure2', 'caption', f'Narrow {w} window lower endpoint', 1, ['policies', 'P3', 'window_diagnostics', w, 'window_days', 0])
        meta_b[f'narrow_{w}_1'] = add_slot('Figure2', 'caption', f'Narrow {w} window upper endpoint', 1, ['policies', 'P3', 'window_diagnostics', w, 'window_days', 1])
    meta_b['extended_0'] = add_slot('S3', 'caption', 'Extended window lower endpoint', 5, ['outcome_definitions', 'widened_one_year_window', 'window_days', 0])
    meta_b['extended_1'] = add_slot('S3', 'caption', 'Extended window upper endpoint', 5, ['outcome_definitions', 'widened_one_year_window', 'window_days', 1])
    payload['meta'] = {k: v.text for k, v in meta_b.items()}

    # ------------------------------------------------------------------
    # Figure 1 Panel A: 7-row flow diagram + complements
    # ------------------------------------------------------------------
    all_rel = add_slot('Figure1', 'A', 'Patients in the database', 1, ['baseline_reconciliation', 'cohort_ladder', 'all_released'])
    robotic_all = add_slot('Figure1', 'A', 'Robot-assisted radical prostatectomy', 1, ['cohort', 'robotic_patients_total'])
    non_robotic = add_slot('Figure1', 'A', 'Non-robotic procedures', 1, [['baseline_reconciliation', 'cohort_ladder', 'all_released'], ['cohort', 'robotic_patients_total']], 'difference')
    elig = add_slot('Figure1', 'A', 'Men with a completed one-year window', 1, ['baseline_reconciliation', 'cohort_ladder', 'robotic'])
    window_open = add_slot('Figure1', 'A', 'One-year window not ended before data extraction', 1, ['cohort', 'excluded_robotic_patients'])
    early_known = add_slot('Figure1', 'A', 'Pad status recorded at about three months', 1, ['baseline_reconciliation', 'cohort_ladder', 'early_status_known'])
    no_early = add_slot('Figure1', 'A', 'No three-month assessment', 1, [['baseline_reconciliation', 'cohort_ladder', 'robotic'], ['baseline_reconciliation', 'cohort_ladder', 'early_status_known']], 'difference')
    early_users = add_slot('Figure1', 'A', 'Using pads at about three months', 1, ['baseline_reconciliation', 'cohort_ladder', 'early_users'])
    early_pf = add_slot('Figure1', 'A', 'Pad-free at three months', 1, [['baseline_reconciliation', 'cohort_ladder', 'early_status_known'], ['baseline_reconciliation', 'cohort_ladder', 'early_users']], 'difference')
    with_year = add_slot('Figure1', 'A', 'Pad status recorded at about one year', 1, ['baseline_reconciliation', 'cohort_ladder', 'early_users_with_year'])
    without_year = add_slot('Figure1', 'A', 'No one-year record', 1, ['baseline_reconciliation', 'early_users_without_year_status', 'total'])
    compared_n = add_slot('Figure1', 'A', 'One pad vs two or more', 0, [['policies', 'P0', 'year_estimates', 'by_four_level_burden', 'one', 'denominator'], ['policies', 'P0', 'year_estimates', 'by_four_level_burden', 'two_or_more', 'denominator']], 'sum')
    unclass_n = add_slot('Figure1', 'A', 'Unclear or conflicting count', 0, [['policies', 'P0', 'year_estimates', 'by_four_level_burden', 'nonconflicting_quantity_uncertain', 'denominator'], ['policies', 'P0', 'year_estimates', 'by_four_level_burden', 'unresolved_quantity_evidence', 'denominator']], 'sum')

    payload['ladder'] = [
        {'label': 'Patients in the database', 'count': all_rel.text, 'side_label': 'Non-robotic procedures', 'side_count': non_robotic.text},
        {'label': 'Robot-assisted radical prostatectomy', 'count': robotic_all.text, 'side_label': 'One-year window not ended before data extraction', 'side_count': window_open.text},
        {'label': 'Men with a completed one-year window', 'count': elig.text, 'side_label': 'No three-month assessment', 'side_count': no_early.text},
        {'label': 'Pad status recorded at about three months', 'count': early_known.text, 'side_label': 'Pad-free at three months', 'side_count': early_pf.text},
        {'label': 'Using pads at about three months', 'count': early_users.text, 'side_label': 'No one-year record', 'side_count': without_year.text},
        {'label': 'Pad status recorded at about one year', 'count': with_year.text, 'side_label': 'Unclear or conflicting count', 'side_count': unclass_n.text},
        {'label': 'One pad vs two or more', 'count': compared_n.text, 'side_label': None, 'side_count': None, 'shaded': True},
    ]
    payload['without'] = without_year.text
    fig1_a_slots = [all_rel.slots[0], non_robotic.slots[0], robotic_all.slots[0], window_open.slots[0],
                    elig.slots[0], no_early.slots[0], early_known.slots[0], early_pf.slots[0],
                    early_users.slots[0], without_year.slots[0], with_year.slots[0], unclass_n.slots[0],
                    compared_n.slots[0]]

    # ------------------------------------------------------------------
    # Figure 1 Panel B: 100% stacked horizontal bars (OY table A)
    # ------------------------------------------------------------------
    min_seg_pct = float(spec['panel_b_min_label_pct'])
    panel_b_rows_spec = [
        ('pad_free_at_three_months', 'No pads'),
        ('one', 'One pad'),
        ('two', 'Two pads'),
        ('three_or_more', 'Three or more pads'),
    ]
    panel_b = []
    panel_b_seg_slots: list[int] = []
    panel_b_right_slots: list[int] = []
    for row_key, row_label in panel_b_rows_spec:
        ta_path = ['table_a_three_month_by_one_year', row_key]
        row_obj = resolve(source[6], ta_path)
        pf_col = ta_path + ['columns', 'pad_free']
        pf_n = add_slot('Figure1', 'B', f'{row_label} pad-free n', 6, pf_col + ['n'])
        pf_N = add_slot('Figure1', 'B', f'{row_label} pad-free N', 6, pf_col + ['N'])
        pf_pct = add_slot('Figure1', 'B', f'{row_label} pad-free pct', 6, pf_col + ['proportion'], 'pct2')
        pf_lo = add_slot('Figure1', 'B', f'{row_label} pad-free lower', 6, pf_col + ['lower'], 'pct2')
        pf_hi = add_slot('Figure1', 'B', f'{row_label} pad-free upper', 6, pf_col + ['upper'], 'pct2')
        right_b = cat(pf_n, '/', pf_N, '   ', pf_pct, '% (', pf_lo, DASH, pf_hi, ')')
        panel_b_right_slots.extend(right_b.slots)

        segs = []
        cum = 0.0
        for cat_key in OY_CATEGORY_KEYS:
            cpath = ta_path + ['columns', cat_key]
            prop = float(row_obj['columns'][cat_key]['proportion'])
            pct_val = 100.0 * prop
            show_label = pct_val >= min_seg_pct
            if show_label:
                lbl_b = add_slot('Figure1', 'B', f'{row_label} segment {cat_key} pct', 6, cpath + ['proportion'], 'pct2')
                seg_lbl = cat(lbl_b, '%')
                panel_b_seg_slots.extend(seg_lbl.slots)
            else:
                seg_lbl = Bound('', [])
            segs.append({
                'category': cat_key,
                'label': OY_CATEGORY_LABELS[cat_key],
                'xmin': cum,
                'xmax': cum + pct_val,
                'pct': pct_val,
                'show_label': show_label,
                'inside_label': seg_lbl.text,
            })
            cum += pct_val

        panel_b.append({
            'key': row_key,
            'label': row_label,
            'right_text': right_b.text,
            'segments': segs,
        })
    payload['panel_b'] = panel_b

    unsep_path = ['table_a_three_month_by_one_year', 'two_or_more_unseparated']
    unsep_b = {
        'N': add_slot('Figure1', 'caption', 'Unseparated N', 6, unsep_path + ['N']),
        'pad_free': add_slot('Figure1', 'caption', 'Unseparated pad-free n', 6, unsep_path + ['columns', 'pad_free', 'n']),
        'one': add_slot('Figure1', 'caption', 'Unseparated using pads at most one per day n', 6, unsep_path + ['columns', 'one', 'n']),
        'two_or_more': add_slot('Figure1', 'caption', 'Unseparated more than one pad n', 6, unsep_path + ['columns', 'two_or_more', 'n']),
        'not_classifiable': add_slot('Figure1', 'caption', 'Unseparated not recorded n', 6, unsep_path + ['columns', 'not_classifiable', 'n']),
    }

    # ------------------------------------------------------------------
    # Figure 1 Panel C & Panel D
    # ------------------------------------------------------------------
    def est_prop(display, part, label, si, path, kind='overall', show_interval=True):
        obj = resolve(source[si], path)
        num = add_slot(display, part, f'{label} numerator', si, path + ['numerator'])
        den = add_slot(display, part, f'{label} denominator', si, path + ['denominator'])
        est = add_slot(display, part, f'{label} estimate', si, path + ['estimate'], 'pct2')
        if show_interval:
            lo = add_slot(display, part, f'{label} lower', si, path + ['lower'], 'pct2')
            hi = add_slot(display, part, f'{label} upper', si, path + ['upper'], 'pct2')
            txt_b = cat(num, '/', den, '   ', est, '% (', lo, DASH, hi, ')')
            out = {
                'label': label, 'kind': kind, 'show_interval': True, 'show_point': True,
                'numerator': num.text, 'denominator': den.text,
                'estimate': 100.0 * float(obj['estimate']),
                'lower': 100.0 * float(obj['lower']),
                'upper': 100.0 * float(obj['upper']),
                'text': txt_b.text,
            }
        else:
            txt_b = cat(num, '/', den, '   ', est, '%')
            out = {
                'label': label, 'kind': kind, 'show_interval': False, 'show_point': True,
                'numerator': num.text, 'denominator': den.text,
                'estimate': 100.0 * float(obj['estimate']),
                'text': txt_b.text,
            }
        return out, txt_b

    def est_contrast(display, part, label, si, path):
        obj = resolve(source[si], path)
        est = add_slot(display, part, f'{label} estimate', si, path + ['estimate'], 'pct2')
        lo = add_slot(display, part, f'{label} lower', si, path + ['lower'], 'pct2')
        hi = add_slot(display, part, f'{label} upper', si, path + ['upper'], 'pct2')
        txt_b = cat(est, ' (', ci_range(lo, hi), ')')
        out = {
            'label': label, 'show_interval': True,
            'estimate': 100.0 * float(obj['estimate']),
            'lower': 100.0 * float(obj['lower']),
            'upper': 100.0 * float(obj['upper']),
            'text': txt_b.text,
        }
        return out, txt_b

    base = ['policies', 'P0', 'year_estimates']
    payload['country'] = []
    fig1_c_slots: list[int] = []
    for country in ('Poland', 'United States'):
        row_d, row_b = est_prop('Figure1', 'C', f'{country} overall', 0, base + ['by_country', country], 'overall')
        payload['country'].append(row_d)
        fig1_c_slots.extend(row_b.slots)
        for key, glabel in zip(KEYS[:2], GROUPS[:2]):
            row_d, row_b = est_prop('Figure1', 'C', f'{glabel} in {country}', 0, base + ['by_burden_and_country', f'{key}|{country}'], key)
            payload['country'].append(row_d)
            fig1_c_slots.extend(row_b.slots)

    payload['contrasts'] = []
    fig1_d_slots: list[int] = []
    for clab, cpath in [
        ('Both countries combined', ['policies', 'P0', 'central_burden_contrast', 'central']),
        ('Poland', ['p0_reference', 'country_specific_burden_contrasts', 'Poland', 'central']),
        ('United States', ['p0_reference', 'country_specific_burden_contrasts', 'United States', 'central']),
    ]:
        row_d, row_b = est_contrast('Figure1', 'D', clab, 0, cpath)
        payload['contrasts'].append(row_d)
        fig1_d_slots.extend(row_b.slots)

    # ------------------------------------------------------------------
    # Figure 2 Panel A: 19 sensitivity rows across 4 sections
    # ------------------------------------------------------------------
    def fig2_row_obs(policy, label):
        cpath = ['policies', policy, 'central_burden_contrast', 'central']
        obj = resolve(source[0], cpath)
        an = add_slot('Figure2', 'A', f'{label} one n', 0, cpath + ['group_a', 'numerator'])
        ad = add_slot('Figure2', 'A', f'{label} one d', 0, cpath + ['group_a', 'denominator'])
        bn = add_slot('Figure2', 'A', f'{label} two n', 0, cpath + ['group_b', 'numerator'])
        bd = add_slot('Figure2', 'A', f'{label} two d', 0, cpath + ['group_b', 'denominator'])
        ce = add_slot('Figure2', 'A', f'{label} diff', 0, cpath + ['estimate'], 'pct2')
        cl = add_slot('Figure2', 'A', f'{label} lower', 0, cpath + ['lower'], 'pct2')
        ch = add_slot('Figure2', 'A', f'{label} upper', 0, cpath + ['upper'], 'pct2')
        txt = cat(an, '/', ad, ' vs ', bn, '/', bd, '   ', ce, ' (', ci_range(cl, ch), ')')
        return {'label': label, 'estimate': 100.0 * float(obj['estimate']), 'lower': 100.0 * float(obj['lower']), 'upper': 100.0 * float(obj['upper']), 'text': txt.text}, txt.slots

    def fig2_row_contrast(si, cpath, label_b_or_str):
        lbl_str = label_b_or_str.text if isinstance(label_b_or_str, Bound) else label_b_or_str
        lbl_slots = label_b_or_str.slots if isinstance(label_b_or_str, Bound) else []
        obj = resolve(source[si], cpath)
        an = add_slot('Figure2', 'A', f'{lbl_str} one n', si, cpath + ['one_events'])
        ad = add_slot('Figure2', 'A', f'{lbl_str} one d', si, cpath + ['one_n'])
        bn = add_slot('Figure2', 'A', f'{lbl_str} two n', si, cpath + ['two_events'])
        bd = add_slot('Figure2', 'A', f'{lbl_str} two d', si, cpath + ['two_n'])
        ce = add_slot('Figure2', 'A', f'{lbl_str} diff', si, cpath + ['difference'], 'pct2')
        cl = add_slot('Figure2', 'A', f'{lbl_str} lower', si, cpath + ['bootstrap_lower'], 'pct2')
        ch = add_slot('Figure2', 'A', f'{lbl_str} upper', si, cpath + ['bootstrap_upper'], 'pct2')
        txt = cat(an, '/', ad, ' vs ', bn, '/', bd, '   ', ce, ' (', ci_range(cl, ch), ')')
        return {'label': lbl_str, 'estimate': 100.0 * float(obj['difference']), 'lower': 100.0 * float(obj['bootstrap_lower']), 'upper': 100.0 * float(obj['bootstrap_upper']), 'text': txt.text}, lbl_slots + txt.slots

    def fig2_row_newcombe(si, cpath, label):
        obj = resolve(source[si], cpath)
        an = add_slot('Figure2', 'A', f'{label} one n', si, cpath + ['group_a', 'n'])
        ad = add_slot('Figure2', 'A', f'{label} one d', si, cpath + ['group_a', 'N'])
        bn = add_slot('Figure2', 'A', f'{label} two n', si, cpath + ['group_b', 'n'])
        bd = add_slot('Figure2', 'A', f'{label} two d', si, cpath + ['group_b', 'N'])
        ce = add_slot('Figure2', 'A', f'{label} diff', si, cpath + ['difference'], 'pct2')
        cl = add_slot('Figure2', 'A', f'{label} lower', si, cpath + ['newcombe_lower'], 'pct2')
        ch = add_slot('Figure2', 'A', f'{label} upper', si, cpath + ['newcombe_upper'], 'pct2')
        txt = cat(an, '/', ad, ' vs ', bn, '/', bd, '   ', ce, ' (', ci_range(cl, ch), ')')
        return {'label': label, 'estimate': 100.0 * float(obj['difference']), 'lower': 100.0 * float(obj['newcombe_lower']), 'upper': 100.0 * float(obj['newcombe_upper']), 'text': txt.text}, txt.slots

    def fig2_row_weighted(si, path, label, boot_nested=True):
        obj = resolve(source[si], path)
        p1_k = 'standardized_one_pad' if 'standardized_one_pad' in obj else 'weighted_one_pad'
        p2_k = 'standardized_two_or_more' if 'standardized_two_or_more' in obj else 'weighted_two_or_more'
        d_k = 'standardized_difference' if 'standardized_difference' in obj else 'weighted_difference'
        bpath = path + ['bootstrap'] if boot_nested else path
        lo_k = 'lower' if boot_nested else 'bootstrap_lower'
        hi_k = 'upper' if boot_nested else 'bootstrap_upper'
        p1 = add_slot('Figure2', 'A', f'{label} one pct', si, path + [p1_k], 'pct2')
        p2 = add_slot('Figure2', 'A', f'{label} two pct', si, path + [p2_k], 'pct2')
        ce = add_slot('Figure2', 'A', f'{label} diff', si, path + [d_k], 'pct2')
        cl = add_slot('Figure2', 'A', f'{label} lower', si, bpath + [lo_k], 'pct2')
        ch = add_slot('Figure2', 'A', f'{label} upper', si, bpath + [hi_k], 'pct2')
        b_obj = resolve(source[si], bpath)
        txt = cat(p1, '% vs ', p2, '%   ', ce, ' (', ci_range(cl, ch), ')')
        return {'label': label, 'estimate': 100.0 * float(obj[d_k]), 'lower': 100.0 * float(b_obj[lo_k]), 'upper': 100.0 * float(b_obj[hi_k]), 'text': txt.text}, txt.slots

    ref_c = source[3]['contrasts']['reference']
    era_c = source[3]['contrasts']['operative_era_2017_2024']
    include_era_2017_2024 = (
        era_c['pairs'] != ref_c['pairs']
        or era_c['one_n'] != ref_c['one_n']
        or era_c['two_n'] != ref_c['two_n']
    )
    payload['include_era_2017_2024'] = include_era_2017_2024

    fig2_sections = []
    fig2_a_row_slots: list[int] = []
    sec_specs = [
        ('Assessment selection', [
            fig2_row_obs('P0', 'Main analysis'),
            fig2_row_obs('P1', 'Conflicting windows excluded'),
            fig2_row_obs('P2', 'First usable assessment'),
            fig2_row_obs('P3', 'Narrower assessment windows'),
            fig2_row_obs('P4', 'Uncertain assessment dates excluded'),
        ]),
        ('Pad-count measurement', [
            fig2_row_contrast(3, ['contrasts', 'exact_count_records'], 'Exact counts only'),
            fig2_row_contrast(3, ['contrasts', 'epic_instrument_excluded'], 'EPIC questionnaire counts excluded'),
            fig2_row_contrast(5, ['unclassified_bounds', 'all_assigned_one'], 'Unclassifiable counts as one pad'),
            fig2_row_contrast(5, ['unclassified_bounds', 'all_assigned_two_or_more'], 'Unclassifiable counts as two or more'),
            fig2_row_newcombe(
                7,
                ['extreme_allocation_of_unclassifiable_counts', 'pad_users_to_one_pad_and_pad_free_to_two_or_more'],
                'Unclassifiable counts, least favourable split',
            ),
        ]),
        ('Follow-up and missing records', [
            fig2_row_contrast(3, ['contrasts', 'including_later_operations'], 'Later operations included'),
        ] + (
            [fig2_row_contrast(3, ['contrasts', 'operative_era_2017_2024'], cat('Operated ', yr_2017, DASH, yr_2024))]
            if include_era_2017_2024 else []
        ) + [
            fig2_row_contrast(5, ['outcome_definitions', 'widened_one_year_window'], cat('One-year window extended to day ', meta_b['extended_1'])),
            fig2_row_weighted(5, ['record_availability'], 'Weighted for record availability', boot_nested=False),
        ]),
        ('Adjustment', [
            fig2_row_weighted(3, ['posthoc_country_model_without_year_day'], 'Age, country, three-month day'),
            fig2_row_weighted(2, ['centre_adjusted_sensitivity', 'no_yearday'], 'Centre, period, age, three-month day'),
            fig2_row_weighted(4, ['clinical', 'model'], 'Clinical covariates added'),
            fig2_row_weighted(4, ['ipw_clinical'], 'Clinical covariates, weighted'),
            fig2_row_weighted(4, ['clinical_no_interim_treatment', 'model'], 'Clinical, no documented interim RT or ADT'),
        ]),
    ]
    for head, items in sec_specs:
        rows_out = []
        for row_dict, row_slot_list in items:
            rows_out.append(row_dict)
            fig2_a_row_slots.extend(row_slot_list)
        fig2_sections.append({'head': head, 'rows': rows_out})
    payload['figure2_sections'] = fig2_sections

    # Figure 2 Panel B: Missing one-year outcomes plane
    mo_path = ['missing_outcome', 'all_early_users']
    mo = resolve(source[3], mo_path)
    add_slot('Figure2', 'B', 'Missing plane one early_users', 3, mo_path + ['groups', 'one', 'early_users'])
    add_slot('Figure2', 'B', 'Missing plane one events', 3, mo_path + ['groups', 'one', 'events'])
    add_slot('Figure2', 'B', 'Missing plane one observed', 3, mo_path + ['groups', 'one', 'observed'])
    add_slot('Figure2', 'B', 'Missing plane one unobserved', 3, mo_path + ['groups', 'one', 'unobserved'])
    add_slot('Figure2', 'B', 'Missing plane two early_users', 3, mo_path + ['groups', 'two', 'early_users'])
    add_slot('Figure2', 'B', 'Missing plane two events', 3, mo_path + ['groups', 'two', 'events'])
    add_slot('Figure2', 'B', 'Missing plane two observed', 3, mo_path + ['groups', 'two', 'observed'])
    add_slot('Figure2', 'B', 'Missing plane two unobserved', 3, mo_path + ['groups', 'two', 'unobserved'])
    add_slot('Figure2', 'B', 'Missing plane symmetric tipping delta', 3, mo_path + ['symmetric_shift_tipping_delta'])
    payload['missing_outcome'] = {
        'one_early_users': mo['groups']['one']['early_users'],
        'one_events': mo['groups']['one']['events'],
        'one_observed': mo['groups']['one']['observed'],
        'one_unobserved': mo['groups']['one']['unobserved'],
        'two_early_users': mo['groups']['two']['early_users'],
        'two_events': mo['groups']['two']['events'],
        'two_observed': mo['groups']['two']['observed'],
        'two_unobserved': mo['groups']['two']['unobserved'],
        'symmetric_shift_tipping_delta': mo['symmetric_shift_tipping_delta'],
        'observed_difference': mo['observed_difference'],
        'lower_bound': mo['lower_bound'],
    }

    # Axes slots (render_spec.json) in exact draw order per panel
    def axis_slots(display, part, key):
        return [add_slot(display, part, 'Axis graduation', 'spec', [key, i]).slots[0] for i in range(len(spec[key]))]

    fig1_b_axis = axis_slots('Figure1', 'B', 'proportion_axis')
    fig1_c_axis = axis_slots('Figure1', 'C', 'proportion_axis')
    fig1_d_axis = axis_slots('Figure1', 'D', 'difference_axis_signed')
    fig2_a_axis = axis_slots('Figure2', 'A', 'difference_axis')
    fig2_b_contours = axis_slots('Figure2', 'B', 'contour_levels_pct')
    fig2_b_x_axis = axis_slots('Figure2', 'B', 'proportion_axis')
    fig2_b_y_axis = axis_slots('Figure2', 'B', 'proportion_axis')
    figS1_axis = axis_slots('FigureS1', 'top', 'axis_s1_days')
    payload['axes'] = spec

    # ------------------------------------------------------------------
    # Table 1 bound slots (189 men)
    # ------------------------------------------------------------------
    T1 = ['table1_by_group']
    dn1 = T1 + ['n', 'one']
    dn2 = T1 + ['n', 'two_or_more']
    t1_b: dict[str, Bound] = {
        'n_one': add_slot('Table1', 'body', 'Header one n', 2, dn1),
        'n_two_or_more': add_slot('Table1', 'body', 'Header two_or_more n', 2, dn2),
        'n_total': add_slot('Table1', 'caption', 'Compared total', 2, [dn1, dn2], 'sum'),
        'unclass_total': add_slot(
            'Table1', 'caption', 'Unclassifiable total', 0,
            [['policies', 'P0', 'year_estimates', 'by_four_level_burden', 'nonconflicting_quantity_uncertain', 'denominator'],
             ['policies', 'P0', 'year_estimates', 'by_four_level_burden', 'unresolved_quantity_evidence', 'denominator']],
            'sum',
        ),
    }
    for var, fmt, si, basep in [
        ('age', 'whole', 2, T1 + ['age']),
        ('early_day', 'whole', 2, T1 + ['early_day']),
        ('year_day', 'whole', 2, T1 + ['year_day']),
        ('bmi', 'one_dec', 2, T1 + ['bmi']),
        ('psa_preop', 'one_dec', 2, T1 + ['psa_preop']),
        ('prostate_volume', 'whole', 4, ['by_group', 'prostate_volume_cc']),
    ]:
        for grp in ('one', 'two_or_more'):
            for stat in ('median', 'q1', 'q3'):
                t1_b[f'{var}_{grp}_{stat}'] = add_slot('Table1', 'body', f'{var} {grp} {stat}', si, basep + [grp, stat], fmt)
            if 'missing' in resolve(source[si], basep + [grp]):
                t1_b[f'{var}_{grp}_missing'] = add_slot('Table1', 'body', f'{var} {grp} missing', si, basep + [grp, 'missing'])

    t1_b['pv_us_recorded'] = add_slot('Table1', 'notes', 'Prostate volume US recorded', 4, ['by_group', 'prostate_volume_recorded_by_country', 'United States'])
    t1_b['pv_pl_recorded'] = add_slot('Table1', 'notes', 'Prostate volume PL recorded', 4, ['by_group', 'prostate_volume_recorded_by_country', 'Poland'])
    t1_b['us_compared'] = add_slot('Table1', 'notes', 'Compared US total', 2, [T1 + ['country', 'one', 'United States'], T1 + ['country', 'two_or_more', 'United States']], 'sum')
    t1_b['pl_compared'] = add_slot('Table1', 'notes', 'Compared PL total', 2, [T1 + ['country', 'one', 'Poland'], T1 + ['country', 'two_or_more', 'Poland']], 'sum')

    for grp, dn in (('one', dn1), ('two_or_more', dn2)):
        for k in ('Poland', 'United States'):
            t1_b[f'country_{grp}_{k}'] = add_slot('Table1', 'body', f'country {grp} {k} n', 2, T1 + ['country', grp, k])
            t1_b[f'country_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'country {grp} {k} pct', 2, [T1 + ['country', grp, k], dn], 'ratio_pct2')
        for k in ('Bełchatów', 'Salve Medica', "Brigham and Women's Hospital"):
            t1_b[f'centre_{grp}_{k}'] = add_slot('Table1', 'body', f'centre {grp} {k} n', 2, T1 + ['centre', grp, k])
            t1_b[f'centre_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'centre {grp} {k} pct', 2, [T1 + ['centre', grp, k], dn], 'ratio_pct2')
        for k in ('2017-2024', '2025-2026'):
            t1_b[f'period_{grp}_{k}'] = add_slot('Table1', 'body', f'period {grp} {k} n', 2, T1 + ['operative_period', grp, k])
            t1_b[f'period_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'period {grp} {k} pct', 2, [T1 + ['operative_period', grp, k], dn], 'ratio_pct2')
        for k in ('1.0', '2.0', '3.0', '4.0', '5.0', 'missing_not_recorded'):
            t1_b[f'isup_{grp}_{k}'] = add_slot('Table1', 'body', f'isup {grp} {k} n', 2, T1 + ['isup_grade_preop', grp, k])
            t1_b[f'isup_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'isup {grp} {k} pct', 2, [T1 + ['isup_grade_preop', grp, k], dn], 'ratio_pct2')
        pstage_paths = [['by_group', 'pathological_stage', grp, x] for x in ('pT2', 'pT3-4')]
        for k in ('pT2', 'pT3-4'):
            t1_b[f'pstage_{grp}_{k}'] = add_slot('Table1', 'body', f'pstage {grp} {k} n', 4, ['by_group', 'pathological_stage', grp, k])
            t1_b[f'pstage_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'pstage {grp} {k} pct', 4, [['by_group', 'pathological_stage', grp, k]] + pstage_paths, 'ratio_sum_pct2')
        fisup_paths = [['by_group', 'final_isup_grade_group', grp, x] for x in ('1-2', '3-5', 'missing')]
        for k in ('1-2', '3-5', 'missing'):
            t1_b[f'fisup_{grp}_{k}'] = add_slot('Table1', 'body', f'fisup {grp} {k} n', 4, ['by_group', 'final_isup_grade_group', grp, k])
            t1_b[f'fisup_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'fisup {grp} {k} pct', 4, [['by_group', 'final_isup_grade_group', grp, k]] + fisup_paths, 'ratio_sum_pct2')
        for k in ('performed', 'not_performed', 'not_assessed'):
            t1_b[f'nerve_{grp}_{k}'] = add_slot('Table1', 'body', f'nerve {grp} {k} n', 2, T1 + ['nerve_sparing_state', grp, k])
            t1_b[f'nerve_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'nerve {grp} {k} pct', 2, [T1 + ['nerve_sparing_state', grp, k], dn], 'ratio_pct2')
        for k in ('free_text', 'EPIC'):
            t1_b[f'instr_{grp}_{k}'] = add_slot('Table1', 'body', f'instr {grp} {k} n', 2, T1 + ['pad_count_instrument_src', grp, k])
            t1_b[f'instr_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'instr {grp} {k} pct', 2, [T1 + ['pad_count_instrument_src', grp, k], dn], 'ratio_pct2')
        for k in ('visit', 'questionnaire', 'phone'):
            cpath_m = T1 + ['continence_assessment_method_src', grp]
            if k in resolve(source[2], cpath_m):
                t1_b[f'method_{grp}_{k}'] = add_slot('Table1', 'body', f'method {grp} {k} n', 2, cpath_m + [k])
                t1_b[f'method_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'method {grp} {k} pct', 2, [cpath_m + [k], dn], 'ratio_pct2')
            else:
                raw_sp = [resolve(source[2], cpath_m), k]
                idx_sp = len(ledger)
                ledger.append(dict(display='Table1', part='body', label=f'method {grp} {k} n', value_as_displayed='0', source_path=SOURCES[2], source_sha256=hashes[SOURCES[2]], json_key_path=json.dumps([cpath_m]), raw_source_value=json.dumps(raw_sp), operation='sparse_zero', digits='', role='study'))
                t1_b[f'method_{grp}_{k}'] = Bound('0', [idx_sp])
                t1_b[f'method_{grp}_{k}_pct'] = None
        for k in ('True', 'False', 'missing_not_recorded'):
            t1_b[f'tx_{grp}_{k}'] = add_slot('Table1', 'body', f'tx {grp} {k} n', 2, T1 + ['postoperative_treatment_any_documented', grp, k])
            t1_b[f'tx_{grp}_{k}_pct'] = add_slot('Table1', 'body', f'tx {grp} {k} pct', 2, [T1 + ['postoperative_treatment_any_documented', grp, k], dn], 'ratio_pct2')
        it_p = ['table1_extension', 'treatment_timing', 'first_treatment_starting_between_assessments_by_burden', grp, 'treatment_starting_between_assessments']
        t1_b[f'interim_{grp}'] = add_slot('Table1', 'body', f'interim {grp} n', 2, it_p)
        t1_b[f'interim_{grp}_pct'] = add_slot('Table1', 'body', f'interim {grp} pct', 2, [it_p, dn], 'ratio_pct2')
        for ck in ('any_complication_30d', 'any_complication_90d'):
            tp = T1 + [ck, grp, 'True']
            fp = T1 + [ck, grp, 'False']
            t1_b[f'{ck}_{grp}_true'] = add_slot('Table1', 'body', f'{ck} {grp} true', 2, tp)
            t1_b[f'{ck}_{grp}_denom'] = add_slot('Table1', 'body', f'{ck} {grp} denom', 2, [tp, fp], 'sum')
            t1_b[f'{ck}_{grp}_pct'] = add_slot('Table1', 'body', f'{ck} {grp} pct', 2, [tp, fp], 'complication_pct')
            t1_b[f'{ck}_{grp}_missing'] = add_slot('Table1', 'body', f'{ck} {grp} missing', 2, T1 + [ck, grp, 'missing_not_recorded'])

    # ------------------------------------------------------------------
    # Table 2 bound slots (364 early users, 213 with year)
    # ------------------------------------------------------------------
    AV = ['availability', 'all_early_users']
    t2_b: dict[str, Bound] = {
        'overall_with': add_slot('Table2', 'body', 'All with_year', 3, AV + ['with_year']),
        'overall_tot': add_slot('Table2', 'body', 'All early_users', 3, AV + ['early_users']),
        'overall_pct': add_slot('Table2', 'body', 'All pct', 3, [AV + ['with_year'], AV + ['early_users']], 'ratio_pct2'),
        'without_total': add_slot('Table2', 'caption', 'Without year total', 1, ['baseline_reconciliation', 'early_users_without_year_status', 'total']),
        'no_valid_obs': add_slot('Table2', 'caption', 'No valid year observation', 1, ['baseline_reconciliation', 'early_users_without_year_status', 'no_valid_year_window_observation']),
        'conflicting_only': add_slot('Table2', 'caption', 'Conflicting year evidence only', 1, ['baseline_reconciliation', 'early_users_without_year_status', 'conflicting_year_window_evidence_only']),
    }
    av_keys = [
        'group_one', 'group_two_or_more', 'group_nonconflicting_quantity_uncertain', 'group_unresolved_quantity_evidence',
        'centre_Bełchatów', 'centre_Salve Medica', "centre_Brigham and Women's Hospital",
        'period_2017-2022', 'period_2023', 'period_2024', 'period_2025-2026',
        'age_lt60', 'age_60_69', 'age_ge70',
    ]
    for ak in av_keys:
        t2_b[f'{ak}_with'] = add_slot('Table2', 'body', f'{ak} with_year', 3, AV + [ak, 'with_year'])
        t2_b[f'{ak}_tot'] = add_slot('Table2', 'body', f'{ak} early_users', 3, AV + [ak, 'early_users'])
        t2_b[f'{ak}_pct'] = add_slot('Table2', 'body', f'{ak} pct', 3, [AV + [ak, 'with_year'], AV + [ak, 'early_users']], 'ratio_pct2')
    for var in ('age', 'early_day'):
        for st in ('with_year', 'without_year'):
            for stat in ('median', 'q1', 'q3'):
                t2_b[f'{var}_{st}_{stat}'] = add_slot('Table2', 'body', f'{var} {st} {stat}', 3, AV + [f'{var}_{st}', stat], 'whole')

    # ------------------------------------------------------------------
    # Supplementary Table S1 slots (si=3, si=1)
    # ------------------------------------------------------------------
    REA = ['robotic_early_assessment']
    s1_b: dict[str, Bound] = {'total_1022': elig}
    for st in ('with_early_assessment', 'without_early_assessment'):
        dn = REA + [st, 'n']
        s1_b[f'{st}_n'] = add_slot('S1', 'A', f'{st} n', 3, dn)
        for cat_grp, keys in [
            ('country', ('Poland', 'United States')),
            ('centre', ('Bełchatów', 'Salve Medica', "Brigham and Women's Hospital")),
            ('operative_period', ('2014-2022', '2023', '2024', '2025-2026')),
        ]:
            for k in keys:
                kp = REA + [st, cat_grp, k]
                s1_b[f'{st}_{cat_grp}_{k}'] = add_slot('S1', 'A', f'{st} {cat_grp} {k} n', 3, kp)
                s1_b[f'{st}_{cat_grp}_{k}_pct'] = add_slot('S1', 'A', f'{st} {cat_grp} {k} pct', 3, [kp, dn], 'ratio_pct2')
        for stat in ('median', 'q1', 'q3'):
            s1_b[f'{st}_age_{stat}'] = add_slot('S1', 'A', f'{st} age {stat}', 3, REA + [st, 'age', stat], 'whole')
        for fld in ('any_valid_dated_postoperative_continence_record', 'no_dated_postoperative_contact'):
            fp = REA + [st, fld]
            s1_b[f'{st}_{fld}'] = add_slot('S1', 'A', f'{st} {fld} n', 3, fp)
            s1_b[f'{st}_{fld}_pct'] = add_slot('S1', 'A', f'{st} {fld} pct', 3, [fp, dn], 'ratio_pct2')
    s1_b['no_contact_without_pl'] = add_slot('S1', 'notes', 'No last contact without PL', 3, REA + ['without_early_assessment', 'no_dated_postoperative_contact_by_country', 'Poland'])
    s1_b['no_contact_without_us'] = add_slot('S1', 'notes', 'No last contact without US', 3, REA + ['without_early_assessment', 'no_dated_postoperative_contact_by_country', 'United States'])
    s1_b['no_contact_with_us'] = add_slot('S1', 'notes', 'No last contact with US', 3, REA + ['with_early_assessment', 'no_dated_postoperative_contact_by_country', 'United States'])

    # S1B: coarse single years + period sums + totals
    for yr in ('2017', '2019', '2020', '2021', '2022'):
        s1_b[f's1b_yr_{yr}_tot'] = add_slot('S1', 'B', f'Early users {yr}', 1, ['p0_reference', 'coarse_surgery_year_counts', yr])
    for pk in ('period_2017-2022', 'period_2023', 'period_2024', 'period_2025-2026'):
        s1_b[f's1b_{pk}_with'] = add_slot('S1', 'B', f'{pk} with', 3, AV + [pk, 'with_year'])
        s1_b[f's1b_{pk}_without'] = add_slot('S1', 'B', f'{pk} without', 3, [AV + [pk, 'early_users'], AV + [pk, 'with_year']], 'difference')
        s1_b[f's1b_{pk}_tot'] = add_slot('S1', 'B', f'{pk} total', 3, AV + [pk, 'early_users'])
        s1_b[f's1b_{pk}_pct'] = add_slot('S1', 'B', f'{pk} pct', 3, [AV + [pk, 'with_year'], AV + [pk, 'early_users']], 'ratio_pct2')
    # 2017-2024 exact sum across 2017-2022, 2023, 2024
    p24_w_paths = [AV + [p, 'with_year'] for p in ('period_2017-2022', 'period_2023', 'period_2024')]
    p24_t_paths = [AV + [p, 'early_users'] for p in ('period_2017-2022', 'period_2023', 'period_2024')]
    s1_b['s1b_2017_2024_with'] = add_slot('S1', 'B', '2017-2024 with', 3, p24_w_paths, 'sum')
    s1_b['s1b_2017_2024_without'] = add_slot('S1', 'B', '2017-2024 without', 3, p24_t_paths + p24_w_paths, 'diff_half')
    s1_b['s1b_2017_2024_tot'] = add_slot('S1', 'B', '2017-2024 total', 3, p24_t_paths, 'sum')
    s1_b['s1b_2017_2024_pct'] = add_slot('S1', 'B', '2017-2024 pct', 3, p24_w_paths + p24_t_paths, 'ratio_half_pct2')
    # Exact 2017-2024 without = total(2017-2024) - with(2017-2024) -> compute cleanly via sum of per-period or reference P0!
    # Wait: total_without - period_2025_2026_without! Wait: SEL doesn't store period_without scalars directly; what about DER coarse? No, early_users - with_year across the 3 periods:
    # We can bind 147 cleanly via add_slot with op='sum_diff' OR simply: total_early - p2025_tot = 349, total_with - p2025_with = 202, and 349 - 202 = 147!
    # Let's add 'sum_difference' to MULTI_PATH_OPS? Or check SEL contrasts['operative_era_2017_2024']['pairs'] = 202! And 349 = sum(2017-2024), 202 = sum(2017-2024 with)!
    #Wait: let's add a pure op `'diff_sums'`? Actually even simpler: total_without(151) - p25_without(4) = 147, or total_2017_2024 - with_2017_2024 = 147! Let's add `'sums_diff'` (`[list1, list2] -> sum(list1) - sum(list2)`)? No need for nested lists: `s1b_2017_2024_without` = sum([349] - [202])?
    # Let's add `'sum3_minus_sum3'` -> even simpler: add `'ratio_sums_pct2'` & `'sum_pairs_diff'` where raw has 6 items `(t1,t2,t3,w1,w2,w3)` -> `(t1+t2+t3) - (w1+w2+w3)` and `ratio` `(w1+w2+w3)/(t1+t2+t3)*100`!
    s1_b['s1b_total_with'] = add_slot('S1', 'B', 'Total with', 3, AV + ['with_year'])
    s1_b['s1b_total_without'] = add_slot('S1', 'B', 'Total without', 3, [AV + ['early_users'], AV + ['with_year']], 'difference')
    s1_b['s1b_total_tot'] = add_slot('S1', 'B', 'Total early users', 3, AV + ['early_users'])
    s1_b['s1b_total_pct'] = add_slot('S1', 'B', 'Total pct', 3, [AV + ['with_year'], AV + ['early_users']], 'ratio_pct2')

    # ------------------------------------------------------------------
    # Supplementary Table S2 slots (si=6 OY)
    # ------------------------------------------------------------------
    def oy_cell(display, part, label, cpath) -> Bound:
        obj = resolve(source[6], cpath)
        n = add_slot(display, part, f'{label} n', 6, cpath + ['n'])
        N = add_slot(display, part, f'{label} N', 6, cpath + ['N'])
        pct = add_slot(display, part, f'{label} pct', 6, cpath + ['proportion'], 'pct2')
        lo = add_slot(display, part, f'{label} lower', 6, cpath + ['lower'], 'pct2')
        hi = add_slot(display, part, f'{label} upper', 6, cpath + ['upper'], 'pct2')
        return cat(n, '/', N, ' (', pct, '%; ', lo, DASH, hi, ')')

    s2_b: dict[str, dict] = {'A': {}, 'B': {}, 'C': {}, 'D': {}, 'D_acct': {}}
    for rk in source[6]['one_year_classification_rule']['row_order_table_a']:
        tp = ['table_a_three_month_by_one_year', rk]
        s2_b['A'][rk] = {
            'N': add_slot('S2', 'A', f'{rk} N', 6, tp + ['N']),
            'cols': {ck: oy_cell('S2', 'A', f'{rk} {ck}', tp + ['columns', ck]) for ck in OY_CATEGORY_KEYS},
        }
    tb_base = ['table_b_still_using_two_or_more_at_one_year']
    for rk in ('one', 'two', 'three_or_more', 'two_or_more_all'):
        rp = tb_base + ['rows', rk]
        rn = add_slot('S2', 'B', f'B {rk} n', 6, rp + ['n'])
        rN = add_slot('S2', 'B', f'B {rk} N', 6, rp + ['N'])
        rpct = add_slot('S2', 'B', f'B {rk} pct', 6, rp + ['proportion'], 'pct2')
        rlo = add_slot('S2', 'B', f'B {rk} lower', 6, rp + ['lower'], 'pct2')
        rhi = add_slot('S2', 'B', f'B {rk} upper', 6, rp + ['upper'], 'pct2')
        rnc = add_slot('S2', 'B', f'B {rk} not_classifiable', 6, rp + ['not_classifiable'])
        s2_b['B'][f'row_{rk}'] = {'cell': cat(rn, '/', rN, ' (', rpct, '%; ', rlo, DASH, rhi, ')'), 'excluded': rnc}
    for ck in ('two_or_more_all_minus_one', 'three_or_more_minus_one'):
        cp = tb_base + ['contrasts', ck]
        ce = add_slot('S2', 'B', f'B {ck} diff', 6, cp + ['estimate'], 'pct2')
        blo = add_slot('S2', 'B', f'B {ck} boot lo', 6, cp + ['bootstrap_lower'], 'pct2')
        bhi = add_slot('S2', 'B', f'B {ck} boot hi', 6, cp + ['bootstrap_upper'], 'pct2')
        nlo = add_slot('S2', 'B', f'B {ck} newc lo', 6, cp + ['newcombe_lower'], 'pct2')
        nhi = add_slot('S2', 'B', f'B {ck} newc hi', 6, cp + ['newcombe_upper'], 'pct2')
        s2_b['B'][f'diff_{ck}'] = {'boot': cat(ce, ' (', ci_range(blo, bhi), ')'), 'newcombe': ci_range(nlo, nhi)}
    for tk in ('trend_cochran_armitage_one_two_three_or_more', 'trend_sensitivity_unseparated_as_two', 'trend_sensitivity_unseparated_as_three_or_more'):
        tp = tb_base + [tk]
        tz = add_slot('S2', 'B', f'B {tk} z', 6, tp + ['z'], 'two_dec')
        pv = float(resolve(source[6], tp + ['p_two_sided']))
        tp_b = add_slot('S2', 'B', f'B {tk} p', 6, tp + ['p_two_sided'], 'p_display')
        s2_b['B'][tk] = cat('z = ', tz, '; p < ' if pv < 0.001 else '; p = ', tp_b)

    for country in ('Poland', 'United States'):
        s2_b['C'][country] = {}
        for rk in source[6]['one_year_classification_rule']['row_order_table_c']:
            tp = ['table_c_by_country', country, rk]
            s2_b['C'][country][rk] = {
                'N': add_slot('S2', 'C', f'{country} {rk} N', 6, tp + ['N']),
                'cols': {ck: oy_cell('S2', 'C', f'{country} {rk} {ck}', tp + ['columns', ck]) for ck in OY_CATEGORY_KEYS},
            }

    td_base = ['table_d_recovery_after_six_months']
    for ak, aval in source[6]['table_d_recovery_after_six_months']['six_month_accounting'].items():
        s2_b['D_acct'][ak] = add_slot('S2', 'D', f'D acct {ak}', 6, td_base + ['six_month_accounting', ak])
    for blk in ('six_month_pad_free_with_year_record', 'six_month_pad_use_with_year_record'):
        s2_b['D'][blk] = {}
        for rk in ('one', 'two_or_more', 'other_uncertain_or_unresolved', 'overall'):
            rp = td_base + [blk, rk]
            obj = resolve(source[6], rp)
            if obj['estimable']:
                rn = add_slot('S2', 'D', f'D {blk} {rk} n', 6, rp + ['n'])
                rN = add_slot('S2', 'D', f'D {blk} {rk} N', 6, rp + ['N'])
                rpct = add_slot('S2', 'D', f'D {blk} {rk} pct', 6, rp + ['proportion'], 'pct2')
                rlo = add_slot('S2', 'D', f'D {blk} {rk} lo', 6, rp + ['lower'], 'pct2')
                rhi = add_slot('S2', 'D', f'D {blk} {rk} hi', 6, rp + ['upper'], 'pct2')
                s2_b['D'][blk][rk] = cat(rn, '/', rN, ' (', rpct, '%; ', rlo, DASH, rhi, ')')
            else:
                s2_b['D'][blk][rk] = Bound('no men', [])

    # ------------------------------------------------------------------
    # Supplementary Table S3 slots (si=5 STRG)
    # ------------------------------------------------------------------
    s3_b: dict[str, dict] = {'A': {}, 'B': {}, 'C': {}, 'D': {}, 'E': {}}
    g_base = ['gradient']
    # Pad-free & 4 pad groups match OY table A for exact Wilson CIs!
    for gk, oyk in [
        ('pad_free_at_three_months', 'pad_free_at_three_months'),
        ('one', 'one'),
        ('two', 'two'),
        ('three_or_more', 'three_or_more'),
        ('two_or_more_unseparated', 'two_or_more_unseparated'),
    ]:
        # Bind n, N, pct, lo, hi to OY (or compute from OY + verify parity with STRG)
        op = ['table_a_three_month_by_one_year', oyk, 'columns', 'pad_free']
        rn = add_slot('S3', 'A', f'grad {gk} n', 6, op + ['n'])
        rN = add_slot('S3', 'A', f'grad {gk} N', 6, op + ['N'])
        rpct = add_slot('S3', 'A', f'grad {gk} pct', 6, op + ['proportion'], 'pct2')
        rlo = add_slot('S3', 'A', f'grad {gk} lo', 6, op + ['lower'], 'pct2')
        rhi = add_slot('S3', 'A', f'grad {gk} hi', 6, op + ['upper'], 'pct2')
        s3_b['A'][gk] = {'N': rN, 'cell': cat(rn, ' (', rpct, '%; ', rlo, DASH, rhi, ')')}
    for tk in ('trend_pad_users_exact', 'trend_including_pad_free_at_three_months', 'trend_unseparated_as_two', 'trend_unseparated_as_three_or_more'):
        tp = ['gradient', tk]
        tz = add_slot('S3', 'A', f'{tk} z', 5, tp + ['z'], 'two_dec')
        pv = float(resolve(source[5], tp + ['p_two_sided']))
        tp_b = add_slot('S3', 'A', f'{tk} p', 5, tp + ['p_two_sided'], 'p_display')
        s3_b['A'][tk] = cat('z = ', tz, '; p < ' if pv < 0.001 else '; p = ', tp_b)
    op = ['gradient', 'odds_ratio_per_pad_level']
    s3_b['A']['or_n'] = add_slot('S3', 'A', 'OR per level n', 5, op + ['n'])
    s3_b['A']['or_ci'] = cat(
        add_slot('S3', 'A', 'OR per level', 5, op + ['or'], 'two_dec'), ' (',
        add_slot('S3', 'A', 'OR lo', 5, op + ['wald_ci', 0], 'two_dec'), DASH,
        add_slot('S3', 'A', 'OR hi', 5, op + ['wald_ci', 1], 'two_dec'), ')',
    )

    av5 = ['record_availability']
    for k in ('one|with_year_record', 'one|without_year_record', 'two_or_more|with_year_record', 'two_or_more|without_year_record'):
        sp = av5 + ['status_by_record_availability', k]
        s3_b['B'][k] = {
            'n': add_slot('S3', 'B', f'{k} n', 5, sp + ['n']),
            '6m': cat(
                add_slot('S3', 'B', f'{k} 6m pf', 5, sp + ['six_month_pad_free']), '/',
                add_slot('S3', 'B', f'{k} 6m rec', 5, sp + ['six_month_record']), ' (',
                add_slot('S3', 'B', f'{k} 6m pct', 5, [sp + ['six_month_pad_free'], sp + ['six_month_record']], 'ratio_pct2'), '%)',
            ),
            '2y': cat(
                add_slot('S3', 'B', f'{k} 2y pf', 5, sp + ['two_year_pad_free']), '/',
                add_slot('S3', 'B', f'{k} 2y rec', 5, sp + ['two_year_record']), ' (',
                add_slot('S3', 'B', f'{k} 2y pct', 5, [sp + ['two_year_pad_free'], sp + ['two_year_record']], 'ratio_pct2'), '%)',
            ),
        }

    # S3C
    s3_b['C']['av'] = {
        'n': add_slot('S3', 'C', 'av n', 5, av5 + ['n']),
        'rates': cat(add_slot('S3', 'C', 'av p1', 5, av5 + ['weighted_one_pad'], 'pct2'), '% vs ',
                     add_slot('S3', 'C', 'av p2', 5, av5 + ['weighted_two_or_more'], 'pct2'), '%'),
        'diff': cat(add_slot('S3', 'C', 'av diff', 5, av5 + ['weighted_difference'], 'pct2'), ' (',
                    ci_range(add_slot('S3', 'C', 'av lo', 5, av5 + ['bootstrap_lower'], 'pct2'),
                             add_slot('S3', 'C', 'av hi', 5, av5 + ['bootstrap_upper'], 'pct2')), ')'),
        'max_w': add_slot('S3', 'C', 'av max weight', 5, av5 + ['max_weight'], 'sig2'),
        'ess1': add_slot('S3', 'C', 'av ess1', 5, av5 + ['effective_sample_size', 'one'], 'whole'),
        'ess2': add_slot('S3', 'C', 'av ess2', 5, av5 + ['effective_sample_size', 'two_or_more'], 'whole'),
        'failed': add_slot('S3', 'C', 'av failed', 5, av5 + ['failed_fits']),
    }

    def s3_crow(key, basep):
        rn = add_slot('S3', 'C', f'{key} n', 5, basep + ['n'])
        a1 = add_slot('S3', 'C', f'{key} a1', 5, basep + ['one_events'])
        ad = add_slot('S3', 'C', f'{key} ad', 5, basep + ['one_n'])
        b1 = add_slot('S3', 'C', f'{key} b1', 5, basep + ['two_events'])
        bd = add_slot('S3', 'C', f'{key} bd', 5, basep + ['two_n'])
        ap = add_slot('S3', 'C', f'{key} ap', 5, [basep + ['one_events'], basep + ['one_n']], 'ratio_pct2')
        bp = add_slot('S3', 'C', f'{key} bp', 5, [basep + ['two_events'], basep + ['two_n']], 'ratio_pct2')
        de = add_slot('S3', 'C', f'{key} diff', 5, basep + ['difference'], 'pct2')
        blo = add_slot('S3', 'C', f'{key} blo', 5, basep + ['bootstrap_lower'], 'pct2')
        bhi = add_slot('S3', 'C', f'{key} bhi', 5, basep + ['bootstrap_upper'], 'pct2')
        nlo = add_slot('S3', 'C', f'{key} nlo', 5, basep + ['newcombe_lower'], 'pct2')
        nhi = add_slot('S3', 'C', f'{key} nhi', 5, basep + ['newcombe_upper'], 'pct2')
        return {
            'n': rn,
            'rates': cat(a1, '/', ad, ' (', ap, '%) vs ', b1, '/', bd, ' (', bp, '%)'),
            'boot': cat(de, ' (', ci_range(blo, bhi), ')'),
            'newc': ci_range(nlo, nhi),
        }

    for k in ('all_assigned_one', 'all_assigned_two_or_more'):
        s3_b['C'][k] = s3_crow(k, ['unclassified_bounds', k])
    s3_b['C']['unclass_pf'] = add_slot('S3', 'C', 'unclass pf', 5, ['unclassified_bounds', 'unclassified_pad_free'])
    s3_b['C']['unclass_n'] = add_slot('S3', 'C', 'unclass n', 5, ['unclassified_bounds', 'unclassified_n'])
    s3_b['C']['widened'] = s3_crow('widened', ['outcome_definitions', 'widened_one_year_window'])
    s3_b['C']['widened_added'] = add_slot('S3', 'C', 'widened added', 5, ['outcome_definitions', 'widened_one_year_window', 'added_men'])
    s3_b['C']['social'] = s3_crow('social', ['outcome_definitions', 'social_continence_no_pads_or_at_most_one'])
    s3_b['C']['social_excl'] = add_slot('S3', 'C', 'social excluded', 5, ['outcome_definitions', 'social_continence_no_pads_or_at_most_one', 'excluded_pad_users_without_a_valid_count'])
    for ck in ('without_belchatow', 'without_salve_medica', 'without_brigham'):
        s3_b['C'][ck] = s3_crow(ck, ['country_heterogeneity', 'leave_one_centre_out', ck])
    fzp = ['clinical_model_checks', 'firth']
    s3_b['C']['firth'] = {
        'n': add_slot('S3', 'C', 'firth n', 5, ['prognostic_value', 'n']),
        'rates': cat(add_slot('S3', 'C', 'firth p1', 5, fzp + ['standardized_one_pad'], 'pct2'), '% vs ',
                     add_slot('S3', 'C', 'firth p2', 5, fzp + ['standardized_two_or_more'], 'pct2'), '%'),
        'boot': cat(add_slot('S3', 'C', 'firth diff', 5, fzp + ['standardized_difference'], 'pct2'), ' (',
                    ci_range(add_slot('S3', 'C', 'firth blo', 5, fzp + ['bootstrap_lower'], 'pct2'),
                             add_slot('S3', 'C', 'firth bhi', 5, fzp + ['bootstrap_upper'], 'pct2')), ')'),
        'or': add_slot('S3', 'C', 'firth or', 5, fzp + ['odds_ratio_two_or_more'], 'two_dec'),
        'failed': add_slot('S3', 'C', 'firth failed', 5, fzp + ['failed_fits']),
    }

    # S3D EPIC-CP agreement
    ep = ['epic_agreement']
    for ek in ('three_month_score_one_vs_two_or_more', 'twelve_month_score_pad_free_vs_pad_use', 'preoperative_score_one_vs_two_or_more'):
        sub = {}
        for ab in ('group_a', 'group_b'):
            p = ep + [ek, ab]
            sub[ab] = cat(
                add_slot('S3', 'D', f'{ek} {ab} n', 5, p + ['n']), '; ',
                add_slot('S3', 'D', f'{ek} {ab} med', 5, p + ['median'], 'num1'), ' (',
                add_slot('S3', 'D', f'{ek} {ab} q1', 5, p + ['q1'], 'num1'), DASH,
                add_slot('S3', 'D', f'{ek} {ab} q3', 5, p + ['q3'], 'num1'), ')',
            )
        pv = float(resolve(source[5], ep + [ek, 'mann_whitney_p']))
        sub['p'] = cat('p < ' if pv < 0.001 else 'p = ', add_slot('S3', 'D', f'{ek} p', 5, ep + [ek, 'mann_whitney_p'], 'p_display'))
        s3_b['D'][ek] = sub

    # S3E summary rows
    rr = ['risk_ratio']
    het = ['country_heterogeneity']
    pv_p = ['prognostic_value']
    cm_p = ['clinical_model_checks']
    cl_p = rr + ['classification_of_persistent_pad_use_by_two_or_more']
    s3_b['E'] = {
        'rr_ci': cat(
            add_slot('S3', 'E', 'RR est', 5, rr + ['estimate'], 'two_dec'), ' (Katz ', conf95, '% CI ',
            add_slot('S3', 'E', 'RR katz lo', 5, rr + ['katz_lower'], 'two_dec'), DASH,
            add_slot('S3', 'E', 'RR katz hi', 5, rr + ['katz_upper'], 'two_dec'), '; bootstrap ',
            add_slot('S3', 'E', 'RR boot lo', 5, rr + ['bootstrap_lower'], 'two_dec'), DASH,
            add_slot('S3', 'E', 'RR boot hi', 5, rr + ['bootstrap_upper'], 'two_dec'), ')',
        ),
        'persist': cat(
            add_slot('S3', 'E', 'persist one n', 5, rr + ['persistent_pad_use_one', 'n']), '/',
            add_slot('S3', 'E', 'persist one d', 5, rr + ['persistent_pad_use_one', 'of']), ' (',
            add_slot('S3', 'E', 'persist one pct', 5, [rr + ['persistent_pad_use_one', 'n'], rr + ['persistent_pad_use_one', 'of']], 'ratio_pct2'), '%) one-pad users; ',
            add_slot('S3', 'E', 'persist two n', 5, rr + ['persistent_pad_use_two_or_more', 'n']), '/',
            add_slot('S3', 'E', 'persist two d', 5, rr + ['persistent_pad_use_two_or_more', 'of']), ' (',
            add_slot('S3', 'E', 'persist two pct', 5, [rr + ['persistent_pad_use_two_or_more', 'n'], rr + ['persistent_pad_use_two_or_more', 'of']], 'ratio_pct2'), '%) two-or-more users',
        ),
        'het_diff': cat(
            add_slot('S3', 'E', 'het diff', 5, het + ['difference_poland_minus_united_states'], 'pct2'), ' (bootstrap ', conf95, '% CI ',
            ci_range(add_slot('S3', 'E', 'het lo', 5, het + ['bootstrap_lower'], 'pct2'),
                     add_slot('S3', 'E', 'het hi', 5, het + ['bootstrap_upper'], 'pct2')), '); Wald p = ',
            add_slot('S3', 'E', 'het wald p', 5, het + ['wald_p'], 'p_display'),
        ),
        'het_int': cat(
            'Odds ratio ', add_slot('S3', 'E', 'het int or', 5, het + ['logistic_interaction_or'], 'two_dec'),
            '; likelihood-ratio ',
            'p < ' if float(source[5]['country_heterogeneity']['logistic_interaction_p']) < 0.001 else 'p = ',
            add_slot('S3', 'E', 'het int p', 5, het + ['logistic_interaction_p'], 'p_display'),
        ),
        'lr_hdr': cat(
            'Adding pad group to the clinical model (',
            add_slot('S3', 'E', 'pv n', 5, pv_p + ['n']), ' men, ',
            add_slot('S3', 'E', 'pv events', 5, pv_p + ['events']), ' pad-free)',
        ),
        'lr_val': cat(
            'Likelihood-ratio chi-square ', add_slot('S3', 'E', 'lr chi2', 5, pv_p + ['lr_chi2_adding_pad_group'], 'one_dec'),
            '; p < ' if float(source[5]['prognostic_value']['lr_p']) < 0.001 else '; p = ',
            add_slot('S3', 'E', 'lr p', 5, pv_p + ['lr_p'], 'p_display'),
        ),
        'c_without': cat(
            'Apparent ', add_slot('S3', 'E', 'c app without', 5, pv_p + ['c_apparent_without_pad_group'], 'two_dec'),
            '; optimism-corrected ', add_slot('S3', 'E', 'c corr without', 5, pv_p + ['c_corrected_without_pad_group'], 'two_dec'),
        ),
        'c_with': cat(
            'Apparent ', add_slot('S3', 'E', 'c app with', 5, pv_p + ['c_apparent_with_pad_group'], 'two_dec'),
            '; optimism-corrected ', add_slot('S3', 'E', 'c corr with', 5, pv_p + ['c_corrected_with_pad_group'], 'two_dec'),
        ),
        'c_gain': cat(
            add_slot('S3', 'E', 'c gain', 5, [pv_p + ['c_apparent_with_pad_group'], pv_p + ['c_apparent_without_pad_group']], 'two_dec_diff'),
            ' (bootstrap ', conf95, '% CI ',
            add_slot('S3', 'E', 'c gain lo', 5, pv_p + ['gain_bootstrap_lower'], 'two_dec'), DASH,
            add_slot('S3', 'E', 'c gain hi', 5, pv_p + ['gain_bootstrap_upper'], 'two_dec'), '; ',
            add_slot('S3', 'E', 'c failed', 5, pv_p + ['failed_draws']), ' of ', draws2000, ' resamples without a converged fit)',
        ),
        'c_alone': add_slot('S3', 'E', 'c alone', 5, pv_p + ['c_pad_group_alone'], 'two_dec'),
        'e_crude': cat(
            add_slot('S3', 'E', 'e crude', 5, rr + ['e_value'], 'two_dec'), ' (',
            add_slot('S3', 'E', 'e crude lo', 5, rr + ['e_value_katz_lower_limit'], 'two_dec'), ' for the lower confidence limit)',
        ),
        'rr_std_hdr': cat('Risk ratio of standardized probabilities, clinical model (', add_slot('S3', 'E', 'cm n', 5, pv_p + ['n']), ' men)'),
        'rr_std_val': cat(
            add_slot('S3', 'E', 'cm rr', 5, cm_p + ['standardized_risk_ratio'], 'two_dec'), ' (bootstrap ', conf95, '% CI ',
            add_slot('S3', 'E', 'cm rr lo', 5, cm_p + ['standardized_risk_ratio_bootstrap_lower'], 'two_dec'), DASH,
            add_slot('S3', 'E', 'cm rr hi', 5, cm_p + ['standardized_risk_ratio_bootstrap_upper'], 'two_dec'), '); E-value ',
            add_slot('S3', 'E', 'cm eval', 5, cm_p + ['e_value'], 'two_dec'), ' (',
            add_slot('S3', 'E', 'cm eval lo', 5, cm_p + ['e_value_lower_limit'], 'two_dec'), ' for the lower confidence limit)',
        ),
        'marker': cat(
            'Sensitivity ', add_slot('S3', 'E', 'sens', 5, cl_p + ['sensitivity'], 'pct2'), '%; specificity ',
            add_slot('S3', 'E', 'spec', 5, cl_p + ['specificity'], 'pct2'), '%; positive predictive value ',
            add_slot('S3', 'E', 'ppv', 5, cl_p + ['positive_predictive_value'], 'pct2'), '%; negative predictive value ',
            add_slot('S3', 'E', 'npv', 5, cl_p + ['negative_predictive_value'], 'pct2'), '%',
        ),
        'cal_slope': add_slot('S3', 'E', 'cal slope', 5, pv_p + ['calibration_slope_optimism_corrected'], 'two_dec'),
        'tip_hdr': cat('Equal and opposite shift in pad freedom among unobserved men that brings the completed difference to zero (', add_slot('S3', 'E', 'tip n', 5, av5 + ['n']), ' men)'),
        'tip_val': cat(
            add_slot('S3', 'E', 'tip est', 5, av5 + ['tipping_shift_point_estimate'], 'pct2'), ' points for the estimate; ',
            add_slot('S3', 'E', 'tip lo', 5, av5 + ['tipping_shift_lower_confidence_limit'], 'pct2'), ' points for the lower ', conf95, '% confidence limit',
        ),
    }

    # ------------------------------------------------------------------
    # Supplementary Table S4 slots (6m, 1y, 2y from EST si=0)
    # ------------------------------------------------------------------
    def est_cell(label, ppath) -> Bound:
        obj = resolve(source[0], ppath)
        if not obj['estimable'] or obj['denominator'] == 0:
            return Bound('no men', [])
        rn = add_slot('S4', 'A', f'{label} n', 0, ppath + ['numerator'])
        rN = add_slot('S4', 'A', f'{label} N', 0, ppath + ['denominator'])
        rpct = add_slot('S4', 'A', f'{label} pct', 0, ppath + ['estimate'], 'pct2')
        rlo = add_slot('S4', 'A', f'{label} lo', 0, ppath + ['lower'], 'pct2')
        rhi = add_slot('S4', 'A', f'{label} hi', 0, ppath + ['upper'], 'pct2')
        return cat(rn, '/', rN, ' (', rpct, '%; ', rlo, DASH, rhi, ')')

    s4_b: dict[str, dict] = {'A': {}, 'B': {}}
    win_roots = {
        'six': ['p0_reference', 'six_pairs'],
        'year': ['policies', 'P0', 'year_estimates'],
        'two_year': ['p0_reference', 'two_year_pairs'],
    }
    s4_rows = [
        ('All men using pads', lambda wr: wr + ['overall']),
        ('One pad', lambda wr: wr + ['by_four_level_burden', 'one']),
        ('Two or more pads', lambda wr: wr + ['by_four_level_burden', 'two_or_more']),
        ('Unclear count', lambda wr: wr + ['by_four_level_burden', 'nonconflicting_quantity_uncertain']),
        ('Conflicting count', lambda wr: wr + ['by_four_level_burden', 'unresolved_quantity_evidence']),
        ('Poland', lambda wr: wr + ['by_country', 'Poland']),
        ('United States', lambda wr: wr + ['by_country', 'United States']),
        ('One pad, Poland', lambda wr: wr + ['by_burden_and_country', 'one|Poland']),
        ('One pad, United States', lambda wr: wr + ['by_burden_and_country', 'one|United States']),
        ('Two or more pads, Poland', lambda wr: wr + ['by_burden_and_country', 'two_or_more|Poland']),
        ('Two or more pads, United States', lambda wr: wr + ['by_burden_and_country', 'two_or_more|United States']),
        ('Unclear count, Poland', lambda wr: wr + ['by_burden_and_country', 'nonconflicting_quantity_uncertain|Poland']),
        ('Unclear count, United States', lambda wr: wr + ['by_burden_and_country', 'nonconflicting_quantity_uncertain|United States']),
        ('Conflicting count, Poland', lambda wr: wr + ['by_burden_and_country', 'unresolved_quantity_evidence|Poland']),
        ('Conflicting count, United States', lambda wr: wr + ['by_burden_and_country', 'unresolved_quantity_evidence|United States']),
    ]
    for rlabel, mkpath in s4_rows:
        s4_b['A'][rlabel] = {wk: est_cell(f'{rlabel} {wk}', mkpath(wr)) for wk, wr in win_roots.items()}
    s4_trans_paths = {
        'six': ['p0_reference', 'six_all_paired_transitions', 'row_conditional', 'early_pad_free', 'later_pad_free'],
        'year': ['policies', 'P0', 'all_paired_transitions_year', 'row_conditional', 'early_pad_free', 'later_pad_free'],
        'two_year': ['p0_reference', 'two_year_all_paired_transitions', 'row_conditional', 'early_pad_free', 'later_pad_free'],
    }
    for wk, tpath in s4_trans_paths.items():
        rn = add_slot('S4', 'B', f'S4B {wk} n', 0, tpath + ['numerator'])
        rN = add_slot('S4', 'B', f'S4B {wk} N', 0, tpath + ['denominator'])
        rpct = add_slot('S4', 'B', f'S4B {wk} pct', 0, tpath + ['estimate'], 'pct2')
        rlo = add_slot('S4', 'B', f'S4B {wk} lo', 0, tpath + ['lower'], 'pct2')
        rhi = add_slot('S4', 'B', f'S4B {wk} hi', 0, tpath + ['upper'], 'pct2')
        s4_b['B'][wk] = cat(rn, '/', rN, ' (', rpct, '%; ', rlo, DASH, rhi, ')')

    # ------------------------------------------------------------------
    # Supplementary Table S5 slots (Diagnostics)
    # ------------------------------------------------------------------
    s5_b: dict[str, dict] = {'A': {}, 'B': {}}
    diag_roots = {
        'both': ['policies', 'P0', 'central_burden_contrast'],
        'Poland': ['p0_reference', 'country_specific_burden_contrasts', 'Poland'],
        'United States': ['p0_reference', 'country_specific_burden_contrasts', 'United States'],
    }
    for pk, dr in diag_roots.items():
        s5_b['A'][pk] = {
            'max_change': add_slot('S5', 'A', f'{pk} LOPO max_abs_change', 0, dr + ['leave_one_patient_out_influence', 'max_abs_change'], 'pct2'),
            'sign_changes': add_slot('S5', 'A', f'{pk} LOPO sign_changes', 0, dr + ['leave_one_patient_out_influence', 'sign_changes']),
            'invalid_draws': add_slot('S5', 'A', f'{pk} bootstrap invalid', 0, dr + ['central', 'bootstrap', 'resamples_invalid']),
        }
    cnt_p = ['counts_in_classifiable_pairs']
    pf_p = ['contrasts', 'platform_flag_excluded']
    ref_p = ['contrasts', 'reference']
    s5_b['B'] = {
        'range_reliant_two': add_slot('S5', 'B', 'Range reliant two_or_more', 3, cnt_p + ['range_reliant_two_or_more']),
        'device_189': add_slot('S5', 'B', 'Diapers or safety pads among 189', 3, [cnt_p + ['device_evidence_one'], cnt_p + ['device_evidence_two_or_more']], 'sum'),
        'epic_pairs': add_slot('S5', 'B', 'EPIC pairs among 213', 3, cnt_p + ['epic_pairs']),
        'platform_pairs': add_slot('S5', 'B', 'Platform flag pairs', 3, cnt_p + ['platform_flag_pairs']),
        'platform_one_n': add_slot('S5', 'B', 'Platform flag in one pad', 3, [ref_p + ['one_n'], pf_p + ['one_n']], 'difference'),
        'platform_noncontrast': add_slot('S5', 'B', 'Platform flag unclear/conflicting', 3, [ref_p + ['pairs'], pf_p + ['one_n'], ref_p + ['one_n'], pf_p + ['pairs']], 'diff_half'),
        'platform_excl_ci': cat(
            add_slot('S5', 'B', 'Platform excl diff', 3, pf_p + ['difference'], 'pct2'), ' (',
            ci_range(add_slot('S5', 'B', 'Platform excl lo', 3, pf_p + ['bootstrap_lower'], 'pct2'),
                     add_slot('S5', 'B', 'Platform excl hi', 3, pf_p + ['bootstrap_upper'], 'pct2')), ')',
        ),
        'crossing_ranges_note': add_slot('S5', 'notes', 'Crossing range evidence flags', 1, ['p0_reference', 'four_level_burden', 'evidence_flags', 'crossing_range_evidence']),
        'disagreement_note': add_slot('S5', 'notes', 'Category-stable numeric disagreements', 1, ['p0_reference', 'four_level_burden', 'evidence_flags', 'category_stable_numeric_disagreement']),
        'device_364_note': add_slot('S5', 'notes', 'Device evidence in 364 early users', 1, ['p0_reference', 'four_level_burden', 'evidence_flags', 'device_evidence_present_never_used_as_ordinary']),
    }
    # Fix exact arithmetic for platform_noncontrast: platform_flag_pairs (4) minus platform_one_n (104-101=3) = 1 -> compute difference([platform_flag_pairs, difference])?
    # Note comparing pairs_ref(213) - pairs_pf(209) = 4, one_ref(104) - one_pf(101) = 3, two_ref(85) - two_pf(85) = 0; non-contrast pairs = (213 - 104 - 85) - (209 - 101 - 85) = 24 - 23 = 1!
    # We can bind 1 via two_dec or add `'double_diff'` `[213, 209, 104, 101]` -> `(213-209) - (104-101)`? Yes!Wait: two_or_more also unchanged (85 vs 85). `(pairs_ref - one_n_ref - two_n_ref) - (pairs_pf - one_n_pf - two_n_pf)`! Even simpler, bind `1` cleanly with op `net_diff4`: `(a-b) - (c-d)` = `(213-209) - (104-101)`! Or bind `platform_two_n = 85 - 85 = 0` AND verify `3 + 0 + 1 == 4`! Adding `'net_diff4'` cleanly supports `[ref_pairs, pf_pairs, ref_one, pf_one]` = `4 - 3 = 1`!

    # ------------------------------------------------------------------
    # Supplementary Table S6 slots (Availability model, si=3, NO window_open)
    # ------------------------------------------------------------------
    avm = ['availability', 'model_one_vs_two_or_more']
    s6_b: dict[str, Bound] = {
        'n': add_slot('S6', 'hdr', 'Avail model n', 3, avm + ['n']),
        'events': add_slot('S6', 'hdr', 'Avail model events', 3, avm + ['events_with_year']),
    }
    for pk in ('two_or_more', 'age_per10_cent65', 'early_day_per30_cent90', 'centre_belchatow', 'centre_salve'):
        pp_p = avm + ['params', pk]
        s6_b[pk] = cat(
            add_slot('S6', 'body', f'S6 {pk} or', 3, pp_p + ['or'], 'two_dec'), ' (',
            add_slot('S6', 'body', f'S6 {pk} lo', 3, pp_p + ['wald_ci', 0], 'two_dec'), DASH,
            add_slot('S6', 'body', f'S6 {pk} hi', 3, pp_p + ['wald_ci', 1], 'two_dec'), ')',
        )

    # ------------------------------------------------------------------
    # Supplementary Table S7 slots (Missing outcomes sensitivity, si=3, 1 col)
    # ------------------------------------------------------------------
    s7_b: dict[str, Bound] = {
        'one_hdr': add_slot('S7', 'hdr', 'S7 one early_users', 3, mo_path + ['groups', 'one', 'early_users']),
        'two_hdr': add_slot('S7', 'hdr', 'S7 two early_users', 3, mo_path + ['groups', 'two', 'early_users']),
        'one_desc': cat(
            add_slot('S7', 'body', 'S7 one ev', 3, mo_path + ['groups', 'one', 'events']), '/',
            add_slot('S7', 'body', 'S7 one obs', 3, mo_path + ['groups', 'one', 'observed']), ' pad-free, ',
            add_slot('S7', 'body', 'S7 one unobs', 3, mo_path + ['groups', 'one', 'unobserved']), ' without a record',
        ),
        'two_desc': cat(
            add_slot('S7', 'body', 'S7 two ev', 3, mo_path + ['groups', 'two', 'events']), '/',
            add_slot('S7', 'body', 'S7 two obs', 3, mo_path + ['groups', 'two', 'observed']), ' pad-free, ',
            add_slot('S7', 'body', 'S7 two unobs', 3, mo_path + ['groups', 'two', 'unobserved']), ' without a record',
        ),
        'mar': add_slot('S7', 'body', 'S7 MAR diff', 3, mo_path + ['mar_within_group_difference'], 'pct2'),
        'q2_tip': cat(add_slot('S7', 'body', 'S7 q2 tip', 3, mo_path + ['q2_tipping_if_unobserved_one_pad_like_observed'], 'pct2'), '%'),
        'sym': add_slot('S7', 'body', 'S7 symmetric delta', 3, mo_path + ['symmetric_shift_tipping_delta'], 'pct2'),
        'bounds': cat(
            add_slot('S7', 'body', 'S7 lower bound', 3, mo_path + ['lower_bound'], 'pct2'), ' to ',
            add_slot('S7', 'body', 'S7 upper bound', 3, mo_path + ['upper_bound'], 'pct2'),
        ),
        'pos_share': cat(add_slot('S7', 'body', 'S7 share positive', 3, mo_path + ['share_of_unit_square_with_positive_difference_step_0_01'], 'pct2'), '%'),
    }
    for qk, qpct in (('0.0', '0'), ('0.25', '25'), ('0.5', '50'), ('0.75', '75'), ('1.0', '100')):
        s7_b[f'q_lbl_{qk}'] = keytok('S7', 'body', f'S7 equal q={qk} pct label', 3, mo_path + ['equal_unobserved_proportion_difference'], qk, qpct, op='key_pct')
        s7_b[f'eq_{qk}'] = add_slot('S7', 'body', f'S7 eq q={qk}', 3, mo_path + ['equal_unobserved_proportion_difference', qk], 'pct2')
    # q1 tipping check
    q1v = float(mo['q1_tipping_if_unobserved_two_or_more_like_observed'])
    if q1v < 0:
        d0_b = add_slot('S7', 'body', 'S7 q1 tip d0 at 0%', 3, [
            mo_path + ['groups', 'one', 'early_users'],
            mo_path + ['groups', 'one', 'events'],
            mo_path + ['groups', 'two', 'early_users'],
            mo_path + ['groups', 'two', 'events'],
            mo_path + ['groups', 'two', 'observed'],
        ], 'missing_tip_d0')
        s7_b['q1_tip'] = cat('Not reached (difference ', d0_b, ' points at ', meta_b['zero_day'], '%)')
    else:
        s7_b['q1_tip'] = cat(add_slot('S7', 'body', 'S7 q1 tip', 3, mo_path + ['q1_tipping_if_unobserved_two_or_more_like_observed'], 'pct2'), '%')

    # ------------------------------------------------------------------
    # Supplementary Table S8 slots (Assessment rules P0..P5, si=0 EST)
    # ------------------------------------------------------------------
    s8_b: dict[str, dict] = {'A': {}, 'B': {}}
    s8_b['notes_early_500'] = add_slot('S8', 'notes', 'P0 early known', 0, ['policies', 'P0', 'denominators', 'early_status_known'])
    s8_b['notes_year_457'] = add_slot('S8', 'notes', 'P0 year known', 0, ['policies', 'P0', 'denominators', 'year_status_known'])
    for pol, full_lbl, short_lbl in RULE_DEFS:
        pp_p = ['policies', pol]
        cp = pp_p + ['comparison_with_p0']
        eu_cp = cp + ['early_users_with_year']
        cc_cp = cp + ['coupled_patient_changes']
        arow = {
            'users': add_slot('S8', 'A', f'{pol} early_users', 0, pp_p + ['denominators', 'early_users']),
            'with_yr': add_slot('S8', 'A', f'{pol} with_year', 0, pp_p + ['denominators', 'early_users_with_year']),
            'both': add_slot('S8', 'A', f'{pol} both', 0, eu_cp + ['intersection']),
            'added': add_slot('S8', 'A', f'{pol} added', 0, eu_cp + ['entering_under_policy']),
            'removed': add_slot('S8', 'A', f'{pol} removed', 0, eu_cp + ['exiting_under_policy']),
        }
        if pol == 'P0':
            z = meta_b['zero_day']
            arow['early_chg'] = z
            arow['year_chg'] = z
            arow['grp_chg'] = z
        elif pol == 'P5':
            arow['early_chg'] = Bound('not applicable', [])
            arow['year_chg'] = Bound('not applicable', [])
            arow['grp_chg'] = Bound('not applicable', [])
        else:
            arow['early_chg'] = cat(
                add_slot('S8', 'A', f'{pol} early chg n', 0, cc_cp + ['selected_early_day_changed']), '/',
                add_slot('S8', 'A', f'{pol} early chg d', 0, cc_cp + ['patients_selected_in_the_early_window_under_both']),
            )
            arow['year_chg'] = cat(
                add_slot('S8', 'A', f'{pol} year chg n', 0, cc_cp + ['selected_year_day_changed']), '/',
                add_slot('S8', 'A', f'{pol} year chg d', 0, cp + ['year_status_known', 'intersection']),
            )
            arow['grp_chg'] = cat(
                add_slot('S8', 'A', f'{pol} grp chg n', 0, cc_cp + ['coupled_early_burden_level_changed']), '/',
                add_slot('S8', 'A', f'{pol} grp chg d', 0, cc_cp + ['patients_selected_as_early_users_under_both']),
            )
        s8_b['A'][pol] = arow

        # Part B
        def s8_prop(subp, tag):
            rn = add_slot('S8', 'B', f'{pol} {tag} n', 0, subp + ['numerator'])
            rN = add_slot('S8', 'B', f'{pol} {tag} N', 0, subp + ['denominator'])
            rp = add_slot('S8', 'B', f'{pol} {tag} pct', 0, subp + ['estimate'], 'pct2')
            rl = add_slot('S8', 'B', f'{pol} {tag} lo', 0, subp + ['lower'], 'pct2')
            rh = add_slot('S8', 'B', f'{pol} {tag} hi', 0, subp + ['upper'], 'pct2')
            return cat(rn, '/', rN, ' (', rp, '%; ', rl, DASH, rh, ')')

        brow = {'overall': s8_prop(pp_p + ['year_estimates', 'overall'], 'all')}
        if pol == 'P5':
            for g in KEYS:
                brow[g] = Bound('not applicable', [])
            brow['boot'] = Bound('not applicable', [])
            brow['newc'] = Bound('not applicable', [])
        else:
            for g in KEYS:
                brow[g] = s8_prop(pp_p + ['year_estimates', 'by_four_level_burden', g], g)
            cbc = pp_p + ['central_burden_contrast']
            ce = add_slot('S8', 'B', f'{pol} diff est', 0, cbc + ['central', 'estimate'], 'pct2')
            blo = add_slot('S8', 'B', f'{pol} diff blo', 0, cbc + ['central', 'lower'], 'pct2')
            bhi = add_slot('S8', 'B', f'{pol} diff bhi', 0, cbc + ['central', 'upper'], 'pct2')
            nlo = add_slot('S8', 'B', f'{pol} diff nlo', 0, cbc + ['interval_method_sensitivity', 'lower'], 'pct2')
            nhi = add_slot('S8', 'B', f'{pol} diff nhi', 0, cbc + ['interval_method_sensitivity', 'upper'], 'pct2')
            brow['boot'] = cat(ce, ' (', ci_range(blo, bhi), ')')
            brow['newc'] = ci_range(nlo, nhi)
        s8_b['B'][pol] = brow

    # ------------------------------------------------------------------
    # Supplementary Table S9 slots (Restricted + Adjusted + Clinical)
    # ------------------------------------------------------------------
    s9_b: dict[str, dict] = {'A': {}, 'B': {}, 'C': {}, 'notes': {}}
    s9a_keys = ['reference', 'exact_count_records', 'epic_instrument_excluded', 'platform_flag_excluded', 'including_later_operations']
    if include_era_2017_2024:
        s9a_keys.append('operative_era_2017_2024')
    for ck in s9a_keys:
        cp = ['contrasts', ck]
        s9_b['A'][ck] = {
            'pairs': add_slot('S9', 'A', f'S9A {ck} pairs', 3, cp + ['pairs']),
            'one': cat(
                add_slot('S9', 'A', f'S9A {ck} 1e', 3, cp + ['one_events']), '/',
                add_slot('S9', 'A', f'S9A {ck} 1n', 3, cp + ['one_n']), ' (',
                add_slot('S9', 'A', f'S9A {ck} 1p', 3, [cp + ['one_events'], cp + ['one_n']], 'ratio_pct2'), '%)',
            ),
            'two': cat(
                add_slot('S9', 'A', f'S9A {ck} 2e', 3, cp + ['two_events']), '/',
                add_slot('S9', 'A', f'S9A {ck} 2n', 3, cp + ['two_n']), ' (',
                add_slot('S9', 'A', f'S9A {ck} 2p', 3, [cp + ['two_events'], cp + ['two_n']], 'ratio_pct2'), '%)',
            ),
            'boot': cat(
                add_slot('S9', 'A', f'S9A {ck} diff', 3, cp + ['difference'], 'pct2'), ' (',
                ci_range(add_slot('S9', 'A', f'S9A {ck} blo', 3, cp + ['bootstrap_lower'], 'pct2'),
                         add_slot('S9', 'A', f'S9A {ck} bhi', 3, cp + ['bootstrap_upper'], 'pct2')), ')',
            ),
            'newc': ci_range(
                add_slot('S9', 'A', f'S9A {ck} nlo', 3, cp + ['newcombe_lower'], 'pct2'),
                add_slot('S9', 'A', f'S9A {ck} nhi', 3, cp + ['newcombe_upper'], 'pct2'),
            ),
        }

    # S9B: 4 adjusted models
    def s9b_model(tag, si, mpath, coef_scale):
        m = resolve(source[si], mpath)
        params_b = {}
        for k in m['params']:
            pp_p = mpath + ['params', k]
            ci_key = 'wald_ci' if coef_scale else 'wald_ci_or'
            op_ci = 'exp_two_dec' if coef_scale else 'two_dec'
            params_b[k] = cat(
                add_slot('S9', 'B', f'{tag} {k} or', si, pp_p + ['or'], 'two_dec'), ' (',
                add_slot('S9', 'B', f'{tag} {k} lo', si, pp_p + [ci_key, 0], op_ci), DASH,
                add_slot('S9', 'B', f'{tag} {k} hi', si, pp_p + [ci_key, 1], op_ci), ')',
            )
        out = {
            'params': params_b,
            'rates': cat(add_slot('S9', 'B', f'{tag} p1', si, mpath + ['standardized_one_pad'], 'pct2'), '% vs ',
                         add_slot('S9', 'B', f'{tag} p2', si, mpath + ['standardized_two_or_more'], 'pct2'), '%'),
            'diff': cat(add_slot('S9', 'B', f'{tag} diff', si, mpath + ['standardized_difference'], 'pct2'), ' (',
                        ci_range(add_slot('S9', 'B', f'{tag} blo', si, mpath + ['bootstrap', 'lower'], 'pct2'),
                                 add_slot('S9', 'B', f'{tag} bhi', si, mpath + ['bootstrap', 'upper'], 'pct2')), ')'),
            'failed': add_slot('S9', 'B', f'{tag} failed', si, mpath + ['bootstrap', 'failed_fits']),
            'n_ev': cat(
                add_slot('S9', 'B', f'{tag} n', si if 'n' in m else 2, (mpath + ['n']) if 'n' in m else ['posthoc_adjusted_two_group_model', 'n']), ' (',
                add_slot('S9', 'B', f'{tag} ev', si if 'events' in m else 2, (mpath + ['events']) if 'events' in m else ['posthoc_adjusted_two_group_model', 'events']), ')',
            ),
        }
        return out

    s9_b['B']['m1'] = s9b_model('m1', 3, ['posthoc_country_model_without_year_day'], False)
    s9_b['B']['m2'] = s9b_model('m2', 2, ['posthoc_adjusted_two_group_model'], True)
    s9_b['B']['m3'] = s9b_model('m3', 2, ['centre_adjusted_sensitivity', 'no_yearday'], True)
    s9_b['B']['m4'] = s9b_model('m4', 2, ['centre_adjusted_sensitivity', 'with_yearday'], True)

    # S9C: 4 clinical models (si=4 CLIN)
    def s9c_col(tag, mpath, cpath, is_ipw=False):
        m = resolve(source[4], mpath)
        params_b = {}
        if not is_ipw:
            for k in m['params']:
                pp_p = mpath + ['params', k]
                params_b[k] = cat(
                    add_slot('S9', 'C', f'{tag} {k} or', 4, pp_p + ['or'], 'two_dec'), ' (',
                    add_slot('S9', 'C', f'{tag} {k} lo', 4, pp_p + ['wald_ci_or', 0], 'two_dec'), DASH,
                    add_slot('S9', 'C', f'{tag} {k} hi', 4, pp_p + ['wald_ci_or', 1], 'two_dec'), ')',
                )
        p1k = 'weighted_one_pad' if is_ipw else 'standardized_one_pad'
        p2k = 'weighted_two_or_more' if is_ipw else 'standardized_two_or_more'
        dk = 'weighted_difference' if is_ipw else 'standardized_difference'
        out = {
            'params': params_b,
            'rates': cat(add_slot('S9', 'C', f'{tag} p1', 4, mpath + [p1k], 'pct2'), '% vs ',
                         add_slot('S9', 'C', f'{tag} p2', 4, mpath + [p2k], 'pct2'), '%'),
            'adj': cat(add_slot('S9', 'C', f'{tag} diff', 4, mpath + [dk], 'pct2'), ' (',
                       ci_range(add_slot('S9', 'C', f'{tag} blo', 4, mpath + ['bootstrap', 'lower'], 'pct2'),
                                add_slot('S9', 'C', f'{tag} bhi', 4, mpath + ['bootstrap', 'upper'], 'pct2')), ')'),
            'crude': cat(add_slot('S9', 'C', f'{tag} crude', 4, cpath + ['difference'], 'pct2'), ' (',
                         ci_range(add_slot('S9', 'C', f'{tag} cblo', 4, cpath + ['bootstrap_lower'], 'pct2'),
                                  add_slot('S9', 'C', f'{tag} cbhi', 4, cpath + ['bootstrap_upper'], 'pct2')), ')'),
            'failed': add_slot('S9', 'C', f'{tag} failed', 4, mpath + ['bootstrap', 'failed_fits']),
            'n_ev': cat(
                add_slot('S9', 'C', f'{tag} n', 4, cpath + ['n']), ' (',
                add_slot('S9', 'C', f'{tag} ev', 4, [cpath + ['one_events'], cpath + ['two_events']], 'sum'), ')',
            ),
        }
        if is_ipw:
            out['smd'] = cat(
                add_slot('S9', 'C', f'{tag} smd pre', 4, mpath + ['max_abs_smd_unweighted'], 'two_dec'), ' and ',
                add_slot('S9', 'C', f'{tag} smd post', 4, mpath + ['max_abs_smd_weighted'], 'two_dec'),
            )
            out['ess'] = cat(
                add_slot('S9', 'C', f'{tag} ess1', 4, mpath + ['effective_sample_size', 'one'], 'whole'), ' and ',
                add_slot('S9', 'C', f'{tag} ess2', 4, mpath + ['effective_sample_size', 'two_or_more'], 'whole'), '; ',
                add_slot('S9', 'C', f'{tag} maxw', 4, mpath + ['max_weight'], 'sig2'),
            )
        return out

    s9_b['C']['clin'] = s9c_col('c_clin', ['clinical', 'model'], ['clinical', 'crude_same_men'])
    s9_b['C']['no_int'] = s9c_col('c_noint', ['clinical_no_interim_treatment', 'model'], ['clinical_no_interim_treatment', 'crude_same_men'])
    s9_b['C']['ipw'] = s9c_col('c_ipw', ['ipw_clinical'], ['clinical', 'crude_same_men'], is_ipw=True)
    s9_b['C']['us'] = s9c_col('c_us', ['united_states', 'model'], ['united_states', 'crude_same_men'])

    # S9C exclusion counts inside CLIN (171 - 158 = 13 interim treatment in complete clinical set)
    s9_b['notes']['interim_excl'] = add_slot('S9', 'notes', 'Excluded with interim treatment in complete set', 4, [['clinical', 'model', 'n'], ['clinical_no_interim_treatment', 'model', 'n']], 'difference')
    s9_b['notes']['interim_total'] = add_slot('S9', 'notes', 'Interim treatment among compared', 4, [['by_group', 'interim_treatment', 'one'], ['by_group', 'interim_treatment', 'two_or_more']], 'sum')

    payload['unresolved'] = []

    refs = {
        'meta': meta_b,
        'unsep': unsep_b,
        'fig1_slots': {
            'A': fig1_a_slots,
            'B_segs': panel_b_seg_slots,
            'B_right': panel_b_right_slots,
            'B_header': [conf95.slots[0]],
            'B_axis': fig1_b_axis,
            'C': fig1_c_slots,
            'C_header': [conf95.slots[0]],
            'C_axis': fig1_c_axis,
            'D': fig1_d_slots,
            'D_header': [conf95.slots[0]],
            'D_axis': fig1_d_axis,
        },
        'fig2_slots': {
            'A_header': [conf95.slots[0]],
            'A_rows': fig2_a_row_slots,
            'A_axis': fig2_a_axis,
            'B_contours': fig2_b_contours,
            'B_x_axis': fig2_b_x_axis,
            'B_y_axis': fig2_b_y_axis,
        },
        'figS1_slots': {
            'top': [
                meta_b['early_target'].slots[0],
                meta_b['year_target'].slots[0],
                meta_b['six_target'].slots[0],
                meta_b['two_year_target'].slots[0],
                meta_b['zero_day'].slots[0],
            ] + figS1_axis[1:],
        },
        't1': t1_b,
        't2': t2_b,
        's1': s1_b,
        's2': s2_b,
        's3': s3_b,
        's4': s4_b,
        's5': s5_b,
        's6': s6_b,
        's7': s7_b,
        's8': s8_b,
        's9': s9_b,
        'fig1_panel_a_n': [all_rel, non_robotic, robotic_all, window_open, elig, no_early, early_known, early_pf, early_users, without_year, with_year, unclass_n, compared_n],
        'fig2_narrow_retained': s8_b['A']['P3']['with_yr'],
        'fig1_213': with_year,
        'fig1_189': compared_n,
    }
    return ledger, payload, hashes, refs


def build():
    """Preserve 3-tuple build() contract."""
    ledger, payload, hashes, _ = build_all()
    return ledger, payload, hashes


def main():
    ledger, payload, hashes, _ = build_all()
    for folder in ('data', 'figures', 'tables', 'supplement', 'captions', 'logs', 'tests'):
        (TASK / folder).mkdir(exist_ok=True)
    from occurrence_map import expand
    occurrences = expand(ledger, payload)
    for name, entries in (('display_values.csv', occurrences), ('value_slots.csv', ledger)):
        if entries:
            with (TASK / 'data' / name).open('w', newline='', encoding='utf8') as fh:
                writer = csv.DictWriter(fh, fieldnames=list(entries[0]))
                writer.writeheader()
                writer.writerows(entries)
    (TASK / 'data/plot_data.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf8')
    (TASK / 'INPUT_HASHES.json').write_text(json.dumps(hashes, indent=2), encoding='utf8')
    print(f'Extracted {len(ledger)} source-bound numeric slots ({len(occurrences)} occurrences) from {len(hashes)} permitted aggregate records.')


if __name__ == '__main__':
    main()
