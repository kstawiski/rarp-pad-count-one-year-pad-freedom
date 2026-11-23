#!/usr/bin/env python3
"""Shared study-cohort eligibility, output-path and calibration-gate helpers.

Defines the completed one-year window eligibility rule in one place:
    operation date + 425 days < 2026-04-01

Supports switching between:
  - ``completed_window`` (default): RARP patients whose 425-day window ended before 2026-04-01.
  - ``all_operations``: every RARP patient in the release (earlier reference cohort).
"""
from datetime import date, timedelta
from pathlib import Path
import json
import math

import pandas as pd

HERE = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = HERE / 'evidence'
GATES_PATH = EVIDENCE_DIR / 'COHORT_GATES.json'

COHORT_COMPLETED_WINDOW = 'completed_window'
COHORT_ALL_OPERATIONS = 'all_operations'
COHORTS = (COHORT_COMPLETED_WINDOW, COHORT_ALL_OPERATIONS)
DEFAULT_COHORT = COHORT_COMPLETED_WINDOW

COMMON_EXTRACT_DATE = '2026-04-01'
COMMON_EXTRACT = pd.Timestamp(COMMON_EXTRACT_DATE)
YEAR_WINDOW_CLOSE = 425
CUTOFF_SURGERY_DATE = pd.Timestamp(
    (date.fromisoformat(COMMON_EXTRACT_DATE) - timedelta(days=YEAR_WINDOW_CLOSE)).isoformat()
)
RULE_NAME = 'operation_date_plus_425_days_before_2026_04_01'

# Calendar-period term of the adjusted models ("recent" versus earlier operations). In the earlier
# cohort it contrasted operations from 2025 onwards with earlier ones. The completed-window cohort
# ends with operations of January 2025, so that contrast is nearly constant there and the term
# contrasts operations from 2024 onwards with earlier ones.
RECENT_PERIOD_START_YEAR = {'all_operations': 2025, 'completed_window': 2024}


def recent_period_start_year(cohort_name):
    """First operative year counted as the recent period in the adjusted models of a cohort."""
    return RECENT_PERIOD_START_YEAR[cohort_name]

FROZEN_EVIDENCE_NAMES = frozenset({
    'OBSERVED_ASSESSMENT_DERIVATION.json',
    'OBSERVED_STATUS_ESTIMATES.json',
    'POSTHOC_TWOGROUP.json',
    'SELECTION_FOLLOWUP_SENSITIVITY.json',
    'CLINICAL_ADJUSTMENT.json',
    'STRENGTHENING_ANALYSES.json',
})


class GateError(RuntimeError):
    """Raised when a cohort calibration gate is missing or fails."""

    def __init__(self, code, detail=''):
        super().__init__(code)
        self.code = code
        self.detail = detail


def validate_cohort_name(cohort_name):
    """Validate and return a declared cohort identifier."""
    if cohort_name not in COHORTS:
        raise ValueError(f'UNKNOWN_COHORT:{cohort_name}')
    return cohort_name


def parse_operation_dates(series):
    """Parse exact ISO YYYY-MM-DD operation dates; missing or malformed entries yield NaT."""
    cleaned = series.fillna('').astype(str).str.strip()
    iso = cleaned.str.fullmatch(r'\d{4}-\d{2}-\d{2}')
    return pd.to_datetime(cleaned.where(iso, ''), format='%Y-%m-%d', errors='coerce')


def eligible_mask(patients, cohort_name=DEFAULT_COHORT, *, date_col='surgery_date'):
    """Return `(active_eligible, closed_window, unusable_date)` boolean Series aligned to `patients`."""
    validate_cohort_name(cohort_name)
    if date_col in patients.columns:
        parsed = parse_operation_dates(patients[date_col])
    else:
        parsed = pd.Series(pd.NaT, index=patients.index, dtype='datetime64[ns]')
    unusable = parsed.isna()
    closed = (~unusable) & (parsed < CUTOFF_SURGERY_DATE)
    closed = closed.fillna(False).astype(bool)
    unusable = unusable.fillna(True).astype(bool)
    if cohort_name == COHORT_ALL_OPERATIONS:
        active = pd.Series(True, index=patients.index, dtype=bool)
    else:
        active = closed
    return active, closed, unusable


def _truth_mask(series):
    return series.fillna('').astype(str).str.strip().str.lower().isin(['true', '1', '1.0'])


def apply_cohort(patients, cohort_name=DEFAULT_COHORT, *, id_col='master_patient_id',
                 robotic_col='robotic_platform_used', date_col='surgery_date'):
    """Apply the cohort rule at patient level before any assessment selection.

    Returns `(filtered_patients, eligible_robotic_ids, info)` where:
      - `filtered_patients` retains cohort-eligible rows of `patients`
      - `eligible_robotic_ids` is the set of eligible robotic patient keys
      - `info` carries the aggregate `cohort` metadata block and counts
    """
    validate_cohort_name(cohort_name)
    active, _closed, unusable = eligible_mask(patients, cohort_name, date_col=date_col)
    robotic = _truth_mask(patients[robotic_col]) if robotic_col in patients.columns else pd.Series(False, index=patients.index)
    eligible_robotic_mask = robotic & active
    eligible_robotic_ids = set(patients.loc[eligible_robotic_mask, id_col])
    robotic_total = int(robotic.sum())
    eligible_robotic_count = len(eligible_robotic_ids)
    excluded_robotic_count = int((robotic & ~active).sum())
    unusable_robotic = int((robotic & unusable).sum())
    unusable_all = int(unusable.sum())
    filtered_patients = patients.loc[active].copy()
    info = {
        'cohort_name': cohort_name,
        'rule_name': RULE_NAME if cohort_name == COHORT_COMPLETED_WINDOW else 'all_robotic_operations_in_release',
        'common_extract_date': COMMON_EXTRACT_DATE,
        'year_window_close_day': YEAR_WINDOW_CLOSE,
        'robotic_patients_total': robotic_total,
        'eligible_robotic_patients': eligible_robotic_count,
        'excluded_robotic_patients': excluded_robotic_count,
        'unusable_operation_date_robotic_patients': unusable_robotic,
        'unusable_operation_date_all_released_patients': unusable_all,
    }
    if cohort_name == COHORT_COMPLETED_WINDOW:
        info['model_recent_period_start_year'] = recent_period_start_year(cohort_name)
    return filtered_patients, eligible_robotic_ids, info


def output_path(base_path, cohort_name=DEFAULT_COHORT):
    """Map an existing evidence path to the cohort-specific output path."""
    validate_cohort_name(cohort_name)
    path = Path(base_path)
    if cohort_name == COHORT_ALL_OPERATIONS:
        return path
    return path.with_name(f'{path.stem}_COMPLETED_WINDOW{path.suffix}')


def is_frozen_evidence(path):
    """Return True if `path` points to one of the immutable earlier evidence records."""
    resolved = Path(path).resolve()
    return resolved.name in FROZEN_EVIDENCE_NAMES and resolved.parent == EVIDENCE_DIR.resolve()


def assert_writable_output(path):
    """Refuse to overwrite any existing immutable pre-rebase evidence record."""
    if is_frozen_evidence(path):
        raise RuntimeError('EXISTING_EVIDENCE_IMMUTABLE')
    return Path(path)


def add_cohort_args(parser):
    """Register standard `--cohort` and `--record-gates` options on an ArgumentParser."""
    parser.add_argument('--cohort', choices=COHORTS, default=DEFAULT_COHORT,
                        help='Study cohort selection (default: completed_window).')
    parser.add_argument('--record-gates', action='store_true',
                        help='Verify any pre-filled gates and record observed calibration gates into COHORT_GATES.json.')
    return parser


def _gate_matches(observed, expected):
    if isinstance(expected, dict) and 'value' in expected and 'tol' in expected:
        if isinstance(observed, bool) or not isinstance(observed, (int, float)):
            return False
        val = float(observed)
        return math.isfinite(val) and abs(val - float(expected['value'])) <= float(expected['tol'])
    if isinstance(expected, float) or isinstance(observed, float):
        if isinstance(observed, bool) or isinstance(expected, bool):
            return False
        if not isinstance(observed, (int, float)) or not isinstance(expected, (int, float)):
            return False
        val = float(observed)
        return math.isfinite(val) and abs(val - float(expected)) <= 1e-12
    return type(observed) is type(expected) and observed == expected


def load_gates(gates_path=None):
    """Load the calibration gates JSON."""
    gates_file = Path(GATES_PATH if gates_path is None else gates_path)
    if not gates_file.is_file():
        raise GateError('COHORT_GATES_FILE_MISSING', str(gates_file))
    return json.loads(gates_file.read_text())


def check_or_record_gates(script_key, cohort_name, observed, *, record=False, gates_path=None):
    """Check observed calibration gates against `COHORT_GATES.json` (or record them when `record=True`).

    Any pre-filled non-null gate is verified even when `record=True` before missing/toleranced
    entries are written.
    """
    validate_cohort_name(cohort_name)
    gates_file = Path(GATES_PATH if gates_path is None else gates_path)
    data = load_gates(gates_file)
    cohort_section = data.setdefault(cohort_name, {})
    section = cohort_section.setdefault(script_key, {})

    for key, obs_val in observed.items():
        if key not in section or section[key] is None:
            if not record:
                raise GateError('COHORT_GATE_NOT_RECORDED', f'{cohort_name}.{script_key}.{key}')
        else:
            exp_val = section[key]
            if not _gate_matches(obs_val, exp_val):
                raise GateError('COHORT_GATE_MISMATCH',
                                f'{cohort_name}.{script_key}.{key}: observed={obs_val!r} expected={exp_val!r}')

    if not record:
        extra = set(section) - set(observed)
        if extra:
            raise GateError('COHORT_GATE_KEY_MISMATCH', f'{cohort_name}.{script_key}: extra={sorted(extra)}')
        return {k: observed[k] for k in observed}

    for key, obs_val in observed.items():
        if isinstance(obs_val, bool):
            section[key] = bool(obs_val)
        elif isinstance(obs_val, int):
            section[key] = int(obs_val)
        elif isinstance(obs_val, float):
            if not math.isfinite(obs_val):
                raise GateError('COHORT_GATE_NONFINITE', f'{cohort_name}.{script_key}.{key}')
            section[key] = float(obs_val)
        else:
            section[key] = obs_val

    gates_file.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
    return {k: section[k] for k in observed}


def _compare_values(saved, current, path, float_tol, stats):
    if isinstance(saved, dict) and isinstance(current, dict):
        if set(saved) != set(current):
            missing = sorted(set(saved) - set(current))
            extra = sorted(set(current) - set(saved))
            return False, f'{path}: keys differ missing={missing} extra={extra}'
        for k in sorted(saved):
            ok, reason = _compare_values(saved[k], current[k], f'{path}.{k}' if path else k, float_tol, stats)
            if not ok:
                return False, reason
        return True, ''
    if isinstance(saved, list) and isinstance(current, list):
        if len(saved) != len(current):
            return False, f'{path}: len {len(current)} != {len(saved)}'
        for i, (a, b) in enumerate(zip(saved, current)):
            ok, reason = _compare_values(a, b, f'{path}[{i}]', float_tol, stats)
            if not ok:
                return False, reason
        return True, ''
    if isinstance(saved, (int, float)) and not isinstance(saved, bool) \
            and isinstance(current, (int, float)) and not isinstance(current, bool):
        if isinstance(saved, int) and isinstance(current, int):
            if saved != current:
                return False, f'{path}: {current} != {saved}'
            return True, ''
        diff = abs(float(saved) - float(current))
        if diff > stats['max_float_diff']:
            stats['max_float_diff'] = diff
        if not (math.isfinite(float(current)) and diff <= float_tol):
            return False, f'{path}: float diff {diff} > {float_tol}'
        return True, ''
    if type(saved) is not type(current) or saved != current:
        return False, f'{path}: {current!r} != {saved!r}'
    return True, ''


def compare_records_ignoring_provenance(saved, current, *, ignore_keys=(), float_tol=1e-12):
    """Compare two JSON dicts in `all_operations --verify` mode excluding code/software provenance keys."""
    if not isinstance(saved, dict) or not isinstance(current, dict):
        return False, 'root_not_dict', 0.0
    ignored = set(ignore_keys)
    s_filtered = {k: v for k, v in saved.items() if k not in ignored}
    c_filtered = {k: v for k, v in current.items() if k not in ignored}
    stats = {'max_float_diff': 0.0}
    ok, reason = _compare_values(s_filtered, c_filtered, '', float_tol, stats)
    return ok, reason, stats['max_float_diff']
