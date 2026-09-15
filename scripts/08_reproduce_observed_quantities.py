#!/usr/bin/env python3
"""Objective-reproduction entry point for the M1-OBSERVED aggregate analysis.

Reproduction wrapper only. This script computes no estimate of its own. It
re-executes the accepted derivation (`06_derive_observed_assessments.py`) and
the accepted estimation (`07_observed_status_estimates.py`) against the
authoritative release in memory, compares each recomputation with the saved
aggregate evidence bytes, and reports the declared publication-defining
quantities read out of the RECOMPUTED record. Reading the saved evidence file
as the source of a reported value would reproduce nothing, so no reported value
is taken from it: the saved bytes are used only as the comparison target of the
two byte-equality quantities.

Why a separate entry point exists. `manuscript_cli.py
analysis-reproduction-record` executes exactly one frozen entry point with
`cwd` at the workspace root and then reads re-executed values out of a results
artifact whose shape the installed contract fixes as

    {"quantities": {"<quantity_id>": "<value as a string>", ...}}

Script 07 cannot be that entry point. Its `--output` is constrained to
`manuscript1/evidence/`, so it cannot write into
`analysis/M1-OBSERVED/reproduction/`, and its stdout is a human summary rather
than the contract shape. Editing 06 or 07 to emit the contract shape would
change their SHA-256 and discard their verified build and exact-verification
state. This wrapper adds a new file and leaves 06 and 07 byte-identical.

Reported precision. Numeric values are emitted unrounded, as exact decimal
scalings of the recomputed float. The reproduction input declares the
three-decimal value the manuscript prints with `absolute_tolerance` 0.0005, so
an agreeing recomputation lands inside the declared tolerance and a real
divergence beyond the printed precision is still visible. Counts, booleans and
stable labels are compared exactly.

Byte differences are quantities, not crashes. A derivation or estimation record
that no longer reproduces its saved bytes is reported through
`M1-OBSERVED-derivation-bytes-exactly-reproduced` and
`M1-OBSERVED-estimates-bytes-exactly-reproduced`, and this script still exits
zero so the producer reads the results artifact and derives a discrepancy. A
genuine source, binding or verification failure exits nonzero with a stable
code and no exception text.

Privacy. Every emitted value is an aggregate count, proportion, interval bound,
boolean or stable uppercase label. No identifier, exact date, narrative, record
or private source filename is emitted, and every emitted value is re-checked
against that rule before the results artifact is written. The results artifact
is a subject-manifest member read by the reproduction record. Keep it that way.

Governing design: manuscript1/ANALYSIS_AMENDMENT_OBSERVED_ASSESSMENTS.md. The
reported quantities describe documented care under a declared documentary rule.
They are not treatment effects, not clinical probabilities and not adjudicated
patient facts. No model is fitted here and none is fitted upstream.
"""
from decimal import Decimal, InvalidOperation
from pathlib import Path
import importlib.util
import json
import math
import os
import re
import sys
import warnings

HERE = Path(__file__).resolve().parents[1]
SCRIPT_DIR = HERE / 'scripts'
ESTIMATES_SCRIPT = SCRIPT_DIR / '07_observed_status_estimates.py'
RESULTS_DIR = HERE / 'analysis/M1-OBSERVED/reproduction'
RESULTS = RESULTS_DIR / 'results.json'

GENERIC_FAILURE = 'OBSERVED_REPRODUCTION_FAILED_SOURCE_DETAIL_WITHHELD'
STABLE_CODE = re.compile(r'^[A-Z0-9_]{4,64}$')
DATE_SHAPED = re.compile(r'\d{4}-\d{2}-\d{2}')
QUANTITY_ID = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$')
QUANTITY_VALUE = re.compile(r'^[A-Za-z0-9_.:+-]{1,64}$')
STABLE_LABEL = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')

# Fixed, code-bound expectations. A wrapper that silently emitted a different
# number of quantities, or a different table shape, would let a missing
# publication-defining quantity pass as `not-executable` instead of failing.
QUANTITY_COUNT = 129
DERIVATION_ONLY_QUANTITY_COUNT = 1
TABLE_COLUMNS = ('analysis', 'policy', 'window', 'stratum_kind', 'stratum',
                 'numerator', 'denominator', 'estimate', 'lower', 'upper',
                 'estimable', 'not_estimable_reason')
TABLE_KEY_COLUMNS = 5
PAIR_ANALYSIS = 'later_pad_free_among_selected_pairs'
POLICIES = ('P0', 'P1', 'P2', 'P3', 'P4', 'P5')
BURDEN_LEVELS = (('one', 'one'),
                 ('two_or_more', 'two-or-more'),
                 ('nonconflicting_quantity_uncertain', 'uncertain'),
                 ('unresolved_quantity_evidence', 'unresolved'))
COUNTRY_LEVELS = (('Poland', 'poland'),
                  ('United States', 'united-states'),
                  ('unknown_or_other', 'unknown'))
LATER_WINDOWS = (('six', 'six-month'), ('two_year', 'two-year'))
TRANSITION_CELLS = (('early_pad_free|later_pad_free', 'early-free-later-free'),
                    ('early_pad_free|later_pad_use', 'early-free-later-use'),
                    ('early_pad_use|later_pad_free', 'early-use-later-free'),
                    ('early_pad_use|later_pad_use', 'early-use-later-use'),
                    ('paired_total', 'paired-total'))


def require(ok, code):
    """Hard contract check. `code` is a stable token that never carries source content."""
    if not ok:
        raise RuntimeError(code)


# --------------------------------------------------------------------------------------
# Typed extraction from the recomputed record
# --------------------------------------------------------------------------------------

def node(record, *path):
    """Walk a strict JSON mapping. A missing key or a wrong shape is a contract failure."""
    current = record
    for key in path:
        require(isinstance(current, dict), 'REPRODUCTION_RECORD_SHAPE_UNEXPECTED')
        require(key in current, 'REPRODUCTION_RECORD_KEY_MISSING')
        current = current[key]
    return current


def count(value):
    """Exact nonnegative integer. A Boolean, float, string or None is malformed."""
    require(not isinstance(value, bool), 'REPRODUCTION_COUNT_NOT_AN_INTEGER')
    require(isinstance(value, int), 'REPRODUCTION_COUNT_NOT_AN_INTEGER')
    require(value >= 0, 'REPRODUCTION_COUNT_NEGATIVE')
    return str(value)


def decimal_of(value):
    """Exact decimal of a finite real. Never a Boolean and never a coerced string."""
    require(not isinstance(value, bool), 'REPRODUCTION_NUMBER_NOT_NUMERIC')
    require(isinstance(value, (int, float)), 'REPRODUCTION_NUMBER_NOT_NUMERIC')
    require(math.isfinite(value), 'REPRODUCTION_NUMBER_NOT_FINITE')
    try:
        number = Decimal(repr(value))
    except InvalidOperation:
        raise RuntimeError('REPRODUCTION_NUMBER_NOT_NUMERIC')
    require(number.is_finite(), 'REPRODUCTION_NUMBER_NOT_FINITE')
    return number


def number(value):
    """Unrounded decimal text of a proportion or fraction on its own scale."""
    return format(decimal_of(value), 'f')


def percent(value):
    """Unrounded decimal text of a proportion expressed in percent.

    The scaling shifts the decimal exponent, so it is exact, introduces no float
    multiplication error and is not rounded. The declared three-decimal
    manuscript value with tolerance 0.0005 decides agreement; rounding here
    would instead hide the comparison.
    """
    return format(decimal_of(value).scaleb(2), 'f')


def flag(value):
    require(isinstance(value, bool), 'REPRODUCTION_FLAG_NOT_BOOLEAN')
    return 'true' if value else 'false'


def label(value):
    """Stable declared label. Free text and anything date-shaped is refused."""
    require(isinstance(value, str) and STABLE_LABEL.fullmatch(value),
            'REPRODUCTION_LABEL_NOT_STABLE')
    require(not DATE_SHAPED.search(value), 'REPRODUCTION_LABEL_DATE_SHAPED')
    return value


def reason(value):
    """Not-estimable reason of a stratum, with an absent reason kept derivable.

    A stratum that became estimable has no reason. Emitting a stable token for
    that state reports the change as a discrepant quantity instead of failing
    the whole run and losing every other comparison.
    """
    return 'NONE' if value is None else label(value)


def size(value):
    require(isinstance(value, list), 'REPRODUCTION_RECORD_SHAPE_UNEXPECTED')
    return str(len(value))


def put(out, key, value):
    """Insert one quantity. A repeated id is a failure, never a silent overwrite."""
    require(isinstance(key, str) and QUANTITY_ID.fullmatch(key) and len(key) <= 128,
            'REPRODUCTION_QUANTITY_ID_INVALID')
    require(key not in out, 'REPRODUCTION_QUANTITY_ID_DUPLICATE')
    require(isinstance(value, str) and QUANTITY_VALUE.fullmatch(value),
            'REPRODUCTION_QUANTITY_VALUE_UNSAFE')
    require(not DATE_SHAPED.search(value), 'REPRODUCTION_QUANTITY_VALUE_DATE_SHAPED')
    out[key] = value


def interval(out, prefix, block, *, numerator_id, denominator_id):
    """One Wilson proportion block: counts exactly, bounds unrounded in percent."""
    require(isinstance(block, dict), 'REPRODUCTION_RECORD_SHAPE_UNEXPECTED')
    put(out, numerator_id, count(node(block, 'numerator')))
    put(out, denominator_id, count(node(block, 'denominator')))
    put(out, prefix + '-percent', percent(node(block, 'estimate')))
    put(out, prefix + '-wilson-lower-percent', percent(node(block, 'lower')))
    put(out, prefix + '-wilson-upper-percent', percent(node(block, 'upper')))


def table_index(record):
    """Strict index of the flattened estimate table.

    A dict comprehension or a plain assignment loop would let a repeated key
    overwrite a row and report the wrong stratum without any signal, so the
    insert refuses a repeated key.
    """
    table = node(record, 'estimate_table')
    columns = node(table, 'columns')
    require(isinstance(columns, list) and tuple(columns) == TABLE_COLUMNS,
            'REPRODUCTION_TABLE_COLUMNS_UNEXPECTED')
    rows = node(table, 'rows')
    require(isinstance(rows, list), 'REPRODUCTION_RECORD_SHAPE_UNEXPECTED')
    require(node(table, 'row_count') == len(rows), 'REPRODUCTION_TABLE_ROW_COUNT_MISMATCH')
    index = {}
    for row in rows:
        require(isinstance(row, list) and len(row) == len(TABLE_COLUMNS),
                'REPRODUCTION_TABLE_ROW_SHAPE_UNEXPECTED')
        key = tuple(row[:TABLE_KEY_COLUMNS])
        require(all(isinstance(part, str) for part in key),
                'REPRODUCTION_TABLE_KEY_NOT_A_LABEL')
        require(key not in index, 'REPRODUCTION_TABLE_KEY_DUPLICATE')
        index[key] = dict(zip(TABLE_COLUMNS, row))
    return index


# --------------------------------------------------------------------------------------
# Declared quantity map
# --------------------------------------------------------------------------------------

def collect(record):
    """Aggregate quantity map. Keys must equal the declared quantity ids exactly.

    `record` is the strict JSON view of the RECOMPUTED estimation record, not the
    saved evidence file.
    """
    require(isinstance(record, dict), 'REPRODUCTION_RECORD_SHAPE_UNEXPECTED')
    out = {}
    table = table_index(record)
    p0 = node(record, 'policies', 'P0')
    reference = node(record, 'p0_reference')
    year = node(p0, 'year_estimates')
    contrast = node(p0, 'central_burden_contrast')
    central = node(contrast, 'central')
    bootstrap = node(central, 'bootstrap')
    qualification = node(contrast, 'bootstrap_qualification')
    sensitivity = node(contrast, 'interval_method_sensitivity')
    burden = node(p0, 'four_level_burden_counts')
    paired = node(central, 'rows_by_category')
    availability = node(reference, 'observed_record_availability')
    reasons = node(availability, 'without_year_status_reasons')
    cells = node(p0, 'all_paired_transitions_year', 'cell_counts')
    disposition = node(record, 'model_disposition')

    # Primary P0 year proportion, read from the estimate block rather than the
    # policy denominators so that both derivation paths are reported.
    overall = node(year, 'overall')
    interval(out, 'P0-year-pad-free', overall,
             numerator_id='P0-year-estimate-numerator',
             denominator_id='P0-year-estimate-denominator')
    put(out, 'P0-early-users-without-year-status',
        count(node(p0, 'denominators', 'early_users_without_year')))

    # Six named policies, each with its own early-user, pair and success count.
    for policy in POLICIES:
        denominators = node(record, 'policies', policy, 'denominators')
        put(out, policy + '-early-pad-users', count(node(denominators, 'early_users')))
        put(out, policy + '-selected-early-to-year-pairs',
            count(node(denominators, 'early_users_with_year')))
        put(out, policy + '-year-pad-free-records',
            count(node(denominators, 'year_padfree_in_early_user_pairs')))

    # Four declared burden levels, with the accounting that proves none was
    # dropped, merged or silently placed outside the declared levels.
    by_burden = node(year, 'by_four_level_burden')
    for level, tag in BURDEN_LEVELS:
        put(out, 'P0-early-burden-' + tag, count(node(burden, level)))
        put(out, 'P0-paired-burden-' + tag, count(node(paired, level)))
        interval(out, 'P0-burden-' + tag + '-year-pad-free', node(by_burden, level),
                 numerator_id='P0-burden-' + tag + '-year-pad-free-records',
                 denominator_id='P0-burden-' + tag + '-selected-pairs')
    put(out, 'P0-early-burden-declared-total', count(node(burden, 'declared_total')))
    put(out, 'P0-early-burden-outside-declared-levels',
        count(node(burden, 'outside_declared_levels')))

    # The declared one-minus-two-or-more documentary contrast and its two intervals.
    put(out, 'P0-year-pad-free-burden-one', count(node(central, 'group_a', 'numerator')))
    put(out, 'P0-paired-burden-one-denominator', count(node(central, 'group_a', 'denominator')))
    put(out, 'P0-year-pad-free-burden-two-or-more', count(node(central, 'group_b', 'numerator')))
    put(out, 'P0-paired-burden-two-or-more-denominator',
        count(node(central, 'group_b', 'denominator')))
    put(out, 'P0-burden-contrast-percentage-points', percent(node(central, 'estimate')))
    put(out, 'P0-burden-contrast-bootstrap-lower-pp', percent(node(central, 'lower')))
    put(out, 'P0-burden-contrast-bootstrap-upper-pp', percent(node(central, 'upper')))
    put(out, 'P0-burden-contrast-newcombe-lower-pp', percent(node(sensitivity, 'lower')))
    put(out, 'P0-burden-contrast-newcombe-upper-pp', percent(node(sensitivity, 'upper')))

    # Bootstrap draw accounting. A percentile interval computed on a reduced set
    # of successful draws is a different quantity, so the draw ledger is reported
    # rather than assumed.
    put(out, 'P0-burden-contrast-bootstrap-resamples',
        count(node(bootstrap, 'resamples_requested')))
    put(out, 'P0-burden-contrast-bootstrap-successful-draws',
        count(node(bootstrap, 'resamples_successful')))
    put(out, 'P0-burden-contrast-bootstrap-failed-draws',
        count(node(bootstrap, 'resamples_invalid')))
    put(out, 'P0-burden-contrast-bootstrap-seed', count(node(qualification, 'seed')))
    put(out, 'P0-burden-contrast-bootstrap-invalid-fraction',
        number(node(bootstrap, 'observed_invalid_fraction')))
    put(out, 'P0-burden-contrast-bootstrap-max-invalid-fraction',
        number(node(bootstrap, 'max_invalid_fraction')))
    put(out, 'P0-burden-contrast-bootstrap-any-failed-draws',
        flag(node(qualification, 'any_failed_draws')))
    put(out, 'P0-burden-contrast-interval-conditional-on-successful-draws',
        flag(node(qualification, 'interval_conditional_on_successful_draws')))
    put(out, 'P0-burden-contrast-interval-held-for-repair',
        flag(node(qualification, 'interval_held_for_repair_or_method_amendment')))
    put(out, 'P0-burden-contrast-rows-total', count(node(central, 'rows_total')))
    put(out, 'P0-burden-contrast-rows-unknown-category',
        count(node(central, 'rows_unknown_category')))
    put(out, 'P0-burden-contrast-rows-other-named-category',
        count(node(central, 'rows_other_named_category')))

    # All four transition cells and their total. Reporting three of four would
    # let a cell move without changing anything that is compared.
    for cell, tag in TRANSITION_CELLS:
        put(out, 'P0-transition-' + tag, count(node(cells, cell)))

    # Added later windows, read through the flattened table so that the table a
    # display would be built from is itself reproduced.
    for window, tag in LATER_WINDOWS:
        key = (PAIR_ANALYSIS, 'P0', window, 'overall', 'overall')
        require(key in table, 'REPRODUCTION_TABLE_ROW_MISSING')
        interval(out, 'P0-' + tag + '-pad-free', table[key],
                 numerator_id='P0-' + tag + '-pad-free-records',
                 denominator_id='P0-' + tag + '-selected-pairs')

    # Record availability for the early users held out of the conditional
    # denominator. These patients are described, never scored as failures.
    interval(out, 'P0-availability', node(availability, 'overall'),
             numerator_id='P0-availability-with-year-status',
             denominator_id='P0-availability-early-users')
    put(out, 'P0-availability-without-year-status',
        count(node(availability, 'without_year_status')))
    put(out, 'P0-availability-reason-no-valid-year-window',
        count(node(reasons, 'no_valid_year_window_observation')))
    put(out, 'P0-availability-reason-conflicting-year-window-only',
        count(node(reasons, 'conflicting_year_window_evidence_only')))

    # Every country stratum, including the empty one. An empty stratum that is
    # dropped rather than reported as not estimable is a silent change.
    by_country = node(year, 'by_country')
    availability_by_country = node(availability, 'by_country')
    for country, tag in COUNTRY_LEVELS:
        block = node(by_country, country)
        put(out, 'P0-year-country-' + tag + '-numerator', count(node(block, 'numerator')))
        put(out, 'P0-year-country-' + tag + '-denominator', count(node(block, 'denominator')))
        put(out, 'P0-year-country-' + tag + '-estimable', flag(node(block, 'estimable')))
        available = node(availability_by_country, country)
        put(out, 'P0-availability-country-' + tag + '-denominator',
            count(node(available, 'denominator')))
        put(out, 'P0-availability-country-' + tag + '-estimable',
            flag(node(available, 'estimable')))
    put(out, 'P0-year-country-unknown-not-estimable-reason',
        reason(node(by_country, 'unknown_or_other', 'not_estimable_reason')))
    put(out, 'P0-availability-country-unknown-not-estimable-reason',
        reason(node(availability_by_country, 'unknown_or_other', 'not_estimable_reason')))

    # No model was fitted, standardised or penalised, and no candidate is
    # currently supported. The held original target is unaffected by this run.
    put(out, 'P0-adjusted-models-fitted', flag(node(record, 'model_fitted')))
    put(out, 'P0-model-disposition-model-fitted', flag(node(disposition, 'model_fitted')))
    put(out, 'P0-penalised-fit-performed',
        flag(node(disposition, 'firth_or_any_penalised_fit_performed')))
    put(out, 'P0-model-standardisation-performed',
        flag(node(disposition, 'model_standardisation_performed')))
    put(out, 'P0-supported-model-candidates',
        size(node(disposition, 'supported_model_candidates')))
    put(out, 'P0-model-disposition-state', label(node(disposition, 'state')))
    put(out, 'M1-OBSERVED-weights-applied', flag(node(record, 'weights_applied')))
    put(out, 'M1-OBSERVED-imputation-performed', flag(node(record, 'imputation_performed')))
    put(out, 'M1-OBSERVED-bounds-emitted', flag(node(record, 'bounds_emitted')))

    # Record-level shape, so a rebuilt record with fewer policies or a shorter
    # table cannot match on every individual number and still be a different record.
    put(out, 'M1-OBSERVED-estimate-table-rows', count(node(record, 'estimate_table', 'row_count')))
    put(out, 'M1-OBSERVED-policies-rebuilt', str(len(node(record, 'policies'))))
    put(out, 'M1-OBSERVED-reference-policy', label(node(record, 'reference_policy')))
    return out


# --------------------------------------------------------------------------------------
# Source-native re-execution
# --------------------------------------------------------------------------------------

def load_estimates():
    """Import the frozen estimation script by absolute path, never by search path.

    The path is a module constant. There is no argument, environment variable or
    working-directory effect that can point this at a different file, and a
    redirected or non-regular script is refused before it is executed.
    """
    require(ESTIMATES_SCRIPT.parent == SCRIPT_DIR, 'REPRODUCTION_ENTRY_SCOPE_FAILURE')
    require(not ESTIMATES_SCRIPT.is_symlink() and ESTIMATES_SCRIPT.is_file(),
            'REPRODUCTION_ESTIMATION_SCRIPT_REDIRECTED')
    require(ESTIMATES_SCRIPT.resolve() == ESTIMATES_SCRIPT,
            'REPRODUCTION_ESTIMATION_SCRIPT_REDIRECTED')
    spec = importlib.util.spec_from_file_location('observed_status_estimates_reproduction',
                                                  ESTIMATES_SCRIPT)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def saved_matches(path, text):
    """Exact byte comparison against a saved aggregate record. Never writes."""
    return (path.is_file() and not path.is_symlink() and path.read_text() == text)


def reproduce():
    """Re-execute both records in memory and return the declared quantity map.

    The derivation is recomputed here so that its byte agreement is measured
    rather than inferred from a downstream exception. When it does not agree,
    the estimation record cannot be built on it at all, so the disagreement is
    reported as the one derivable quantity instead of as a failure.
    """
    estimates = load_estimates()
    derivation = estimates.D

    recomputed_derivation = derivation.build_report(derivation.RELEASE)
    derivation_text = derivation.serialise(recomputed_derivation)
    derivation_exact = saved_matches(derivation.OUTPUT, derivation_text)

    quantities = {}
    if derivation_exact:
        recomputed_estimates = estimates.build_record(estimates.RELEASE,
                                                      estimates.DERIVATION_RECORD)
        estimates_text = estimates.serialise(recomputed_estimates)
        estimates_exact = saved_matches(estimates.OUTPUT, estimates_text)
        quantities = collect(json.loads(estimates_text))
        put(quantities, 'M1-OBSERVED-estimates-bytes-exactly-reproduced', flag(estimates_exact))
    put(quantities, 'M1-OBSERVED-derivation-bytes-exactly-reproduced', flag(derivation_exact))

    expected = QUANTITY_COUNT if derivation_exact else DERIVATION_ONLY_QUANTITY_COUNT
    require(len(quantities) == expected, 'REPRODUCTION_QUANTITY_COUNT_UNEXPECTED')
    return quantities, derivation_exact


# --------------------------------------------------------------------------------------
# Guarded aggregate output
# --------------------------------------------------------------------------------------

def validate_payload(payload):
    """Re-check the contract shape and the privacy rule on the exact bytes emitted."""
    require(isinstance(payload, dict) and set(payload) == {'quantities'},
            'REPRODUCTION_RESULTS_SHAPE_UNEXPECTED')
    quantities = payload['quantities']
    require(isinstance(quantities, dict) and quantities, 'REPRODUCTION_RESULTS_SHAPE_UNEXPECTED')
    for key, value in quantities.items():
        require(isinstance(key, str) and QUANTITY_ID.fullmatch(key) and len(key) <= 128,
                'REPRODUCTION_QUANTITY_ID_INVALID')
        require(isinstance(value, str) and QUANTITY_VALUE.fullmatch(value),
                'REPRODUCTION_QUANTITY_VALUE_UNSAFE')
    text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n'
    require(not DATE_SHAPED.search(text), 'REPRODUCTION_RESULTS_DATE_SHAPED')
    return text


def write_results(text):
    """Atomic write to the one code-bound aggregate path. No other file is written.

    The destination is a module constant, so no argument and no environment
    value can redirect it. A symlinked directory or file, or a resolved path
    that leaves the reproduction directory, refuses the write instead of
    following the redirect.
    """
    require(RESULTS.parent == RESULTS_DIR, 'RESULTS_SCOPE_FAILURE')
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    require(not RESULTS_DIR.is_symlink() and RESULTS_DIR.is_dir(), 'RESULTS_DIRECTORY_REDIRECTED')
    require(RESULTS_DIR.resolve() == RESULTS_DIR, 'RESULTS_DIRECTORY_REDIRECTED')
    require(not RESULTS.is_symlink(), 'RESULTS_PATH_REDIRECTED')
    require(not RESULTS.exists() or RESULTS.is_file(), 'RESULTS_PATH_NOT_A_FILE')
    temporary = RESULTS_DIR / ('.results.json.' + str(os.getpid()) + '.tmp')
    require(not temporary.is_symlink(), 'RESULTS_PATH_REDIRECTED')
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(handle, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, RESULTS)
    return RESULTS


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # One entry point, one behaviour. There is no flag, path or runner argument
    # that can change what is computed or where it is written.
    require(not argv, 'REPRODUCTION_ACCEPTS_NO_ARGUMENTS')
    quantities, derivation_exact = reproduce()
    payload = {'quantities': quantities}
    text = validate_payload(payload)
    write_results(text)
    # A byte difference is reported as a discrepant quantity, not as a crash.
    # Exiting nonzero here would make the producer skip the results artifact and
    # label every quantity not-executable, which says less than a discrepancy.
    print(json.dumps({
        'status': 'reproduction_quantities_written',
        'derivation_bytes_exactly_reproduced': derivation_exact,
        'estimates_bytes_exactly_reproduced':
            quantities.get('M1-OBSERVED-estimates-bytes-exactly-reproduced', 'not_derivable'),
        'quantity_count': len(quantities),
    }, sort_keys=True))
    return 0


def safe_main(argv=None):
    """Stable codes only. A message that is not a declared stable code is never surfaced."""
    try:
        with warnings.catch_warnings():
            # Parser and source exceptions can quote private field content. Never surface them.
            warnings.simplefilter('ignore')
            return main(argv)
    except (RuntimeError, ValueError) as error:
        message = str(error)
        print(message if STABLE_CODE.match(message) else GENERIC_FAILURE, file=sys.stderr)
        return 1
    except Exception:
        print(GENERIC_FAILURE, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(safe_main())
