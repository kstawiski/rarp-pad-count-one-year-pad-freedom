#!/usr/bin/env python3
"""Reusable numerical primitives for the observed-assessment extension of manuscript1.

Helper module only. It loads no source data, exposes no command line interface, fits no
model, computes no P value and takes no analysis decision. A later accepted analysis
script imports these functions and supplies its own already-selected patient rows.

Scope of the uncertainty reported here
--------------------------------------
Every interval below is conditional sampling uncertainty for the supplied rows under an
independent-patient assumption, one row per patient per analysis. The intervals do not
cover record ambiguity, documentary rule choice, date selection policy, outcome
misclassification, unknown assessment status or source-system selection into the cohort.
Those remain separate accounting and sensitivity questions for the analysis that calls
this module. Nothing here converts a documentary proportion into a clinical probability.

Input contract shared by the two-group functions
------------------------------------------------
`rows` is a sequence of `(category, outcome)` patient tuples. `category` is a `str`
label or `None` for an unknown category. `outcome` is strictly binary, accepted as
`bool`, `numpy.bool_` or an integer `0`/`1`. Floats, strings and any other integer are
rejected. The pair travels together through every resample, so the association between
category and outcome is never broken by column-wise sampling.

Rows are canonicalised to a sorted multiset of value pairs before any random draw. Two
inputs holding the same pairs in a different order therefore give byte-identical output,
including bootstrap limits, for the same seed.

Unknown-category rows stay in the accounting and stay in the full resampling population.
They contribute to neither group numerator nor group denominator.

Return values are strict JSON-compatible scalars. A quantity that cannot be estimated is
`None`, never `NaN`, and is accompanied by an explicit reason code.
"""
import json
import math
from collections import Counter

import numpy as np

CONFIDENCE_DEFAULT = 0.95
BOOTSTRAP_RESAMPLES_DEFAULT = 2000
BOOTSTRAP_SEED_DEFAULT = 20260907
# Default adopted for this project's observed-assessment amendment. A different
# project policy must be passed explicitly and justified by the caller.
MAX_INVALID_FRACTION_DEFAULT = 0.05

METHOD_NEWCOMBE = 'newcombe_score_difference'
METHOD_BOOTSTRAP = 'patient_percentile_bootstrap'
INTERVAL_METHODS = (METHOD_NEWCOMBE, METHOD_BOOTSTRAP)

UNCERTAINTY_SCOPE = ('conditional_sampling_uncertainty_only; independent_patient_rows; '
                     'not_measurement_error; not_record_ambiguity; not_source_system_selection')
_UNKNOWN_KEY = ''
_CODE_A0, _CODE_A1, _CODE_B0, _CODE_B1, _CODE_OTHER = 0, 1, 2, 3, 4


def require(ok, code):
    """Hard input validation. `code` is a stable machine-readable token."""
    if not ok:
        raise ValueError(code)


def _is_count(value):
    return isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_))


def _check_confidence(confidence):
    require(isinstance(confidence, float) and math.isfinite(confidence), 'CONFIDENCE_NOT_FLOAT')
    require(0.0 < confidence < 1.0, 'CONFIDENCE_OUT_OF_RANGE')


def _check_invalid_fraction(value):
    require(isinstance(value, (int, float, np.integer, np.floating))
            and not isinstance(value, (bool, np.bool_))
            and math.isfinite(float(value)) and 0.0 <= float(value) <= 1.0,
            'MAX_INVALID_FRACTION_INVALID')


def _normal_quantile(p):
    """Inverse standard normal CDF, pure Python.

    Acklam's rational approximation refined by one Halley step against `math.erfc`.
    Verified against `scipy.stats.norm.ppf` in the focused tests to better than 1e-12
    absolute across confidence levels 0.5 to 0.9999, including the adopted 0.95.
    Confidence levels outside that verified range have not been exhaustively checked. Accuracy degrades to about 1e-9 relative in the far tails beyond
    that range, bounded by the precision of `math.erfc` itself rather than by the
    refinement. The module therefore needs neither SciPy nor a hard-coded z constant.
    """
    require(0.0 < p < 1.0, 'QUANTILE_OUT_OF_RANGE')
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    low, high = 0.02425, 1.0 - 0.02425
    if p < low:
        q = math.sqrt(-2.0 * math.log(p))
        x = ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        x /= (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    elif p <= high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        x /= ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        x /= (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    err = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    u = err * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    return x - u / (1.0 + x * u / 2.0)


def wilson_interval(successes, trials, confidence=CONFIDENCE_DEFAULT):
    """Two-sided Wilson score interval for one binomial proportion.

    `successes` (k) and `trials` (n) must be non-negative integers with 0 <= k <= n.
    Booleans are rejected. `trials == 0` is not an error and is reported as an explicit
    not-estimable result rather than a zero, a NaN or a degenerate interval.

    The interval is the score interval without continuity correction, that is the exact
    solution of |k/n - p| = z * sqrt(p(1-p)/n). Limits are clipped to [0, 1] only to
    remove floating-point overshoot at k = 0 and k = n.

    Returns a dict with `numerator`, `denominator`, `estimate`, `lower`, `upper`,
    `estimable`, `not_estimable_reason`, `confidence`, `method` and `uncertainty_scope`.
    """
    require(_is_count(trials), 'TRIALS_NOT_INTEGER')
    require(int(trials) >= 0, 'TRIALS_NEGATIVE')
    require(_is_count(successes), 'SUCCESSES_NOT_INTEGER')
    n, k = int(trials), int(successes)
    require(0 <= k <= n, 'SUCCESSES_OUT_OF_RANGE')
    _check_confidence(confidence)
    out = {'numerator': k, 'denominator': n, 'estimate': None, 'lower': None, 'upper': None,
           'estimable': False, 'not_estimable_reason': 'ZERO_DENOMINATOR',
           'confidence': float(confidence), 'method': 'wilson_score_two_sided',
           'uncertainty_scope': UNCERTAINTY_SCOPE}
    if n == 0:
        return out
    z = _normal_quantile(0.5 + confidence / 2.0)
    z2 = z * z
    centre = (k + z2 / 2.0) / (n + z2)
    half = (z / (n + z2)) * math.sqrt(k * (n - k) / n + z2 / 4.0)
    out['estimate'] = k / n
    # The score limits are exactly 0 at k = 0 and exactly 1 at k = n. Rounding leaves the
    # far limit one ulp short of the boundary, so it is set from the identity instead.
    out['lower'] = 0.0 if k == 0 else min(1.0, max(0.0, centre - half))
    out['upper'] = 1.0 if k == n else min(1.0, max(0.0, centre + half))
    out['estimable'] = True
    out['not_estimable_reason'] = None
    return out


def _canonical_rows(rows, group_a, group_b):
    """Validate rows and return an order-invariant canonical tuple of value pairs."""
    require(isinstance(group_a, str) and group_a != '', 'GROUP_A_LABEL_INVALID')
    require(isinstance(group_b, str) and group_b != '', 'GROUP_B_LABEL_INVALID')
    require(group_a != group_b, 'GROUP_LABELS_NOT_DISTINCT')
    require(not isinstance(rows, (str, bytes, dict)), 'ROWS_NOT_SEQUENCE')
    try:
        material = list(rows)
    except TypeError:
        raise ValueError('ROWS_NOT_SEQUENCE')
    canonical = []
    for row in material:
        require(not isinstance(row, (str, bytes)), 'ROW_NOT_PAIR')
        try:
            pair = tuple(row)
        except TypeError:
            raise ValueError('ROW_NOT_PAIR')
        require(len(pair) == 2, 'ROW_NOT_PAIR')
        category, outcome = pair
        require(category is None or isinstance(category, str), 'CATEGORY_TYPE_INVALID')
        if isinstance(outcome, (bool, np.bool_)):
            value = int(outcome)
        elif _is_count(outcome):
            value = int(outcome)
        else:
            raise ValueError('OUTCOME_NOT_BINARY')
        require(value in (0, 1), 'OUTCOME_NOT_BINARY')
        canonical.append(((0, _UNKNOWN_KEY) if category is None else (1, category), value))
    canonical.sort()
    return tuple(canonical)


def _row_codes(canonical, group_a, group_b):
    """Map canonical rows to the five states used by every count below."""
    codes = np.empty(len(canonical), dtype=np.int64)
    for i, (key, value) in enumerate(canonical):
        label = None if key[0] == 0 else key[1]
        if label == group_a:
            codes[i] = _CODE_A1 if value else _CODE_A0
        elif label == group_b:
            codes[i] = _CODE_B1 if value else _CODE_B0
        else:
            codes[i] = _CODE_OTHER
    return codes


def _accounting(canonical, codes, group_a, group_b):
    by_category = Counter(key[1] for key, _ in canonical if key[0] == 1)
    unknown_count = sum(key[0] == 0 for key, _ in canonical)
    counts = np.bincount(codes, minlength=5) if len(codes) else np.zeros(5, dtype=np.int64)
    return {
        'rows_total': len(canonical),
        'rows_by_category': {name: int(value) for name, value in sorted(by_category.items())},
        'rows_unknown_category': int(unknown_count),
        'rows_by_category_scope': 'named_categories_only_missing_reported_separately',
        'rows_other_named_category': int(counts[_CODE_OTHER]) - int(unknown_count),
        'group_a_label': group_a,
        'group_b_label': group_b,
    }, counts


def _difference_point(counts):
    """Observed unadjusted difference p(a) - p(b), or None when a group is absent."""
    na = int(counts[_CODE_A0] + counts[_CODE_A1])
    nb = int(counts[_CODE_B0] + counts[_CODE_B1])
    if na == 0 or nb == 0:
        return None, na, nb
    return int(counts[_CODE_A1]) / na - int(counts[_CODE_B1]) / nb, na, nb


def _newcombe_limits(wa, wb):
    """Newcombe method 10, the square-and-add combination of two Wilson intervals.

    lower = d - sqrt((pa - la)^2 + (ub - pb)^2)
    upper = d + sqrt((ua - pa)^2 + (pb - lb)^2)
    with d = pa - pb. Recomputed here from that published formula, not from a library.
    """
    d = wa['estimate'] - wb['estimate']
    lower = d - math.sqrt((wa['estimate'] - wa['lower']) ** 2 + (wb['upper'] - wb['estimate']) ** 2)
    upper = d + math.sqrt((wa['upper'] - wa['estimate']) ** 2 + (wb['estimate'] - wb['lower']) ** 2)
    return max(-1.0, lower), min(1.0, upper)


def _percentile_bootstrap(codes, resamples, seed, confidence, draw):
    """Run the resampling loop and record every replicate outcome, valid or not.

    `draw` returns the resampled code array for one replicate. No replicate is silently
    discarded. A replicate in which either group is empty yields no difference and is
    counted under its own reason.
    """
    require(_is_count(resamples) and int(resamples) > 0, 'RESAMPLES_INVALID')
    require(_is_count(seed) and int(seed) >= 0, 'SEED_INVALID')
    rng = np.random.default_rng(int(seed))
    values, invalid = [], Counter()
    for _ in range(int(resamples)):
        counts = np.bincount(draw(rng), minlength=5)
        diff, na, nb = _difference_point(counts)
        if diff is None:
            if na == 0 and nb == 0:
                invalid['both_groups_absent'] += 1
            elif na == 0:
                invalid['group_a_absent'] += 1
            else:
                invalid['group_b_absent'] += 1
            continue
        values.append(diff)
    tail = (100.0 - 100.0 * confidence) / 2.0
    replicates = np.asarray(values, dtype=float)
    block = {
        'resamples_requested': int(resamples),
        'resamples_successful': int(replicates.size),
        'resamples_invalid': int(sum(invalid.values())),
        'invalid_reasons': {name: int(value) for name, value in sorted(invalid.items())},
        'seed': int(seed),
        'percentiles': [tail, 100.0 - tail],
        'quantile_rule': 'numpy_percentile_linear_interpolation_on_successful_replicates',
    }
    if replicates.size == 0:
        return block, None, None, 'BOOTSTRAP_NO_VALID_RESAMPLE'
    lo, hi = np.percentile(replicates, block['percentiles'])
    return block, float(lo), float(hi), None


def _difference_frame(accounting, counts, confidence, method):
    """Shared observed-data part of every two-group result."""
    diff, na, nb = _difference_point(counts)
    wa = wilson_interval(int(counts[_CODE_A1]), na, confidence)
    wb = wilson_interval(int(counts[_CODE_B1]), nb, confidence)
    out = dict(accounting)
    out.update({
        'group_a': wa, 'group_b': wb,
        'estimate': diff, 'lower': None, 'upper': None,
        'estimable': False, 'not_estimable_reason': None,
        'confidence': float(confidence), 'method': method,
        'contrast': 'proportion_group_a_minus_proportion_group_b',
        'adjusted': False,
        'uncertainty_scope': UNCERTAINTY_SCOPE,
    })
    if accounting['rows_total'] == 0:
        out['not_estimable_reason'] = 'NO_ROWS'
    elif diff is None:
        out['not_estimable_reason'] = 'GROUP_ABSENT_IN_OBSERVED_ROWS'
    return out, diff


def proportion_difference(rows, group_a, group_b, *, method,
                          confidence=CONFIDENCE_DEFAULT,
                          resamples=BOOTSTRAP_RESAMPLES_DEFAULT,
                          seed=BOOTSTRAP_SEED_DEFAULT,
                          max_invalid_fraction=MAX_INVALID_FRACTION_DEFAULT):
    """Unadjusted difference between two group proportions with one chosen interval.

    `method` has no default. The caller states which candidate interval it wants, so no
    interval is ever selected by inspecting the result. Both candidates are legitimate
    for these data and the accountable manager decides which is primary.

    `newcombe_score_difference`
        Newcombe method 10, square-and-add of the two Wilson score intervals. Closed
        form, boundary-respecting, defined whenever both groups have at least one row.

    `patient_percentile_bootstrap`
        Nonparametric percentile bootstrap over whole patient tuples drawn with
        replacement from the full canonical row multiset, including unknown-category
        rows, at the original total row count. B and the seed are explicit. Replicates
        that leave a group empty are counted, never dropped in silence, and the interval
        is withheld when the invalid fraction exceeds `max_invalid_fraction`.

    The point estimate is the observed difference in both cases. It never comes from the
    bootstrap distribution. No P value is produced.
    """
    require(method in INTERVAL_METHODS, 'INTERVAL_METHOD_UNKNOWN')
    _check_confidence(confidence)
    _check_invalid_fraction(max_invalid_fraction)
    canonical = _canonical_rows(rows, group_a, group_b)
    codes = _row_codes(canonical, group_a, group_b)
    accounting, counts = _accounting(canonical, codes, group_a, group_b)
    out, diff = _difference_frame(accounting, counts, confidence, method)
    if diff is None:
        return out
    if method == METHOD_NEWCOMBE:
        out['lower'], out['upper'] = _newcombe_limits(out['group_a'], out['group_b'])
        out['estimable'] = True
        out['interval_provenance'] = 'newcombe_1998_method_10_recomputed_from_formula'
        return out
    total = len(codes)
    block, lo, hi, reason = _percentile_bootstrap(
        codes, resamples, seed, confidence,
        lambda rng: codes[rng.integers(0, total, total)])
    block['resampling_unit'] = 'whole_patient_tuple_category_and_outcome_together'
    block['resampling_population'] = ('all_canonical_rows_including_unknown_category; '
                                      'with_replacement; size_equals_rows_total')
    block['max_invalid_fraction'] = float(max_invalid_fraction)
    block['observed_invalid_fraction'] = block['resamples_invalid'] / block['resamples_requested']
    out['bootstrap'] = block
    if reason is None and block['observed_invalid_fraction'] > max_invalid_fraction:
        reason = 'BOOTSTRAP_INVALID_FRACTION_EXCEEDED'
    if reason is not None:
        out['not_estimable_reason'] = reason
        return out
    out['lower'], out['upper'] = lo, hi
    out['estimable'] = True
    out['interval_provenance'] = 'nonparametric_percentile_bootstrap_over_patient_tuples'
    return out


def stratified_bootstrap_proportion_difference(rows, group_a, group_b, *,
                                               confidence=CONFIDENCE_DEFAULT,
                                               resamples=BOOTSTRAP_RESAMPLES_DEFAULT,
                                               seed=BOOTSTRAP_SEED_DEFAULT,
                                               max_invalid_fraction=MAX_INVALID_FRACTION_DEFAULT):
    """Bootstrap that resamples within each group at its observed size.

    A separate, explicitly named function. `proportion_difference` never substitutes it.
    Group sizes are held fixed, so no replicate can leave a group empty when both groups
    are present, and unknown-category rows do not enter the resampling population. That
    conditions on the observed group sizes, which is a different sampling model from the
    unconditional patient bootstrap. Use it deliberately, not as a repair for a high
    invalid fraction.
    """
    _check_confidence(confidence)
    _check_invalid_fraction(max_invalid_fraction)
    canonical = _canonical_rows(rows, group_a, group_b)
    codes = _row_codes(canonical, group_a, group_b)
    accounting, counts = _accounting(canonical, codes, group_a, group_b)
    method = 'stratified_within_group_percentile_bootstrap'
    out, diff = _difference_frame(accounting, counts, confidence, method)
    if diff is None:
        return out
    codes_a = codes[(codes == _CODE_A0) | (codes == _CODE_A1)]
    codes_b = codes[(codes == _CODE_B0) | (codes == _CODE_B1)]
    na, nb = codes_a.size, codes_b.size

    def draw(rng):
        return np.concatenate((codes_a[rng.integers(0, na, na)], codes_b[rng.integers(0, nb, nb)]))

    block, lo, hi, reason = _percentile_bootstrap(codes, resamples, seed, confidence, draw)
    block['resampling_unit'] = 'whole_patient_tuple_within_its_own_group'
    block['resampling_population'] = ('group_a_rows_and_group_b_rows_separately; with_replacement; '
                                      'group_sizes_held_at_observed_values; '
                                      'unknown_category_rows_excluded_from_resampling')
    block['max_invalid_fraction'] = float(max_invalid_fraction)
    block['observed_invalid_fraction'] = block['resamples_invalid'] / block['resamples_requested']
    out['bootstrap'] = block
    if reason is None and block['observed_invalid_fraction'] > max_invalid_fraction:
        reason = 'BOOTSTRAP_INVALID_FRACTION_EXCEEDED'
    if reason is not None:
        out['not_estimable_reason'] = reason
        return out
    out['lower'], out['upper'] = lo, hi
    out['estimable'] = True
    out['interval_provenance'] = 'stratified_within_group_percentile_bootstrap'
    return out


def leave_one_out_influence(rows, group_a, group_b):
    """Exact patient-level leave-one-out influence on the unadjusted difference.

    Every supplied row is removed once, the difference is recomputed on the remaining
    rows, and only aggregates are returned. No per-row influence array is emitted, so no
    single patient can be identified from the output.

    This is a diagnostic. It never marks a valid observation as an outlier and never
    removes anything from an analysis. A removal that empties a group is reported as an
    undefined removal, not as a missing value.

    Removing an unknown-category row leaves the difference unchanged and is counted as a
    defined removal with zero change. `sign_changes` counts removals that strictly reverse
    the observed direction of the difference.
    """
    canonical = _canonical_rows(rows, group_a, group_b)
    codes = _row_codes(canonical, group_a, group_b)
    accounting, counts = _accounting(canonical, codes, group_a, group_b)
    base, _, _ = _difference_point(counts)
    out = dict(accounting)
    out.update({
        'base_estimate': base,
        'estimable': False,
        'not_estimable_reason': None,
        'max_abs_change': None,
        'min_estimate': None,
        'max_estimate': None,
        'undefined_removals': 0,
        'defined_removals': 0,
        'sign_changes': 0,
        'removal_unit': 'one_patient_row',
        'per_row_output_emitted': False,
        'diagnostic_only_no_observation_removed': True,
        'uncertainty_scope': UNCERTAINTY_SCOPE,
    })
    if accounting['rows_total'] == 0:
        out['not_estimable_reason'] = 'NO_ROWS'
        return out
    if base is None:
        out['not_estimable_reason'] = 'GROUP_ABSENT_IN_OBSERVED_ROWS'
        out['undefined_removals'] = accounting['rows_total']
        return out
    estimates, undefined = [], 0
    for code in codes:
        reduced = counts.copy()
        reduced[code] -= 1
        value, _, _ = _difference_point(reduced)
        if value is None:
            undefined += 1
        else:
            estimates.append(value)
    out['undefined_removals'] = int(undefined)
    out['defined_removals'] = len(estimates)
    if not estimates:
        out['not_estimable_reason'] = 'ALL_REMOVALS_UNDEFINED'
        return out
    values = np.asarray(estimates, dtype=float)
    out['max_abs_change'] = float(np.max(np.abs(values - base)))
    out['min_estimate'] = float(values.min())
    out['max_estimate'] = float(values.max())
    # A strict reversal of the observed direction. A base difference of exactly zero has
    # no direction to reverse, so it reports no reversal rather than counting every row.
    if base > 0.0:
        out['sign_changes'] = int(np.sum(values < 0.0))
    elif base < 0.0:
        out['sign_changes'] = int(np.sum(values > 0.0))
    out['estimable'] = True
    return out


def json_safe(result):
    """Round-trip a result through JSON and fail loudly on NaN, infinity or a bad type."""
    text = json.dumps(result, allow_nan=False, sort_keys=True)
    return json.loads(text)
