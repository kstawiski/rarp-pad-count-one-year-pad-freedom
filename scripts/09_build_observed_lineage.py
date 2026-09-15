#!/usr/bin/env python3
"""Privacy-safe local generator for the M1-OBSERVED source-to-input lineage.

Builds, from the authoritative release and the adopted observation policies, the
project population authority (catalog, authority index, category authority, prior
population inventory), the workspace-internal restricted master artifact, the
restricted all-policy analytic input, the identity inventories and the contract
lineage record ``analysis/M1-OBSERVED/input-lineage.json``. It also measures the
actual overlap of the historical 474 patient-day measurement review units with
every policy's selected observations.

Default mode is ``--check``: everything is assembled in memory, validated with the
installed contract validator inside a private temporary workspace, and only an
aggregate receipt is written to the report directory. ``--build`` writes the canonical
restricted artifacts and is reserved for manager execution.

Privacy: patient identities, dates and source values never reach stdout, stderr, the
aggregate receipt or exception messages. Restricted outputs are owner-only files in
owner-only directories. Failures inside the source path are reported by stable codes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import pandas as pd

HERE = Path(__file__).resolve().parents[1]
WORKSPACE = HERE.parent
SCRIPT_PATH = Path(__file__).resolve()
CLI_PATH = Path('/home/konrad/.codex/plugins/cache/konsta-research/konsta-research/8.0.35/scripts/manuscript_cli.py')
CONTRACT_PATH = CLI_PATH.parents[1] / 'shared/references/workflow-contract.json'
REPORT_DIR_DEFAULT = WORKSPACE / 'delegated_tasks/manuscript1_lineage_resolution'
REVIEW_UNITS_DEFAULT = WORKSPACE / 'delegated_tasks/manuscript1_cases_20260907/restricted/review_units.jsonl'
IDENTITY_INDEX_DEFAULT = WORKSPACE / 'delegated_tasks/manuscript1_cases_20260907/restricted/identity_index.jsonl'

ANALYSIS_ID = 'M1-OBSERVED'
AUTHORITY_ID = 'release-v1.1-2026-09-04-full-source-population'
IDENTITY_NAMESPACE = 'master_patient_id'
ID = 'master_patient_id'
CATEGORY_FIELD = 'patient_wide.platform'
CATEGORY_COLUMN = 'platform'
FLAG_COLUMN = 'robotic_platform_used'
CONFLICT_COLUMN = 'platform_conflict'
RELEASE_RELATIVE = 'data/prostatectomy_analysis_database_v1.1_2026-09-04'
DATA_SNAPSHOT_ID_DEFAULT = 'release-v1.1-2026-09-04-verified-inputs'
PIPELINE_SNAPSHOT_ID_DEFAULT = 'observed-assessment-py3.14.3-pandas2.3.3-numpy2.5.2'
MAPPED_CLASS = 'robotic-prostatectomy-observed-cohort'
POLICIES = ('P0', 'P1', 'P2', 'P3', 'P4', 'P5')
EXACT_POLICIES = ('P0', 'P1', 'P2', 'P3', 'P4')
LATER_WINDOWS = ('year', 'six', 'two_year')
ALL_WINDOWS = ('early',) + LATER_WINDOWS
BURDEN_LEVELS = ('one', 'two_or_more', 'nonconflicting_quantity_uncertain', 'unresolved_quantity_evidence')
EVIDENCE_PATTERNS = ('explicit_status_disagreement', 'missing_vs_known_status', 'disjoint_numeric_quantities',
                     'compatible_overlapping_quantities', 'nonidentical_numeric_quantities',
                     'missing_vs_known_quantity', 'coarse_uncertainty_vs_known_burden',
                     'candidate_burden_nonidentical', 'nonidentical_quantities_same_known_burden',
                     'equivalent_numeric_evidence', 'invalid_values_present', 'status_count_contradiction')
GENERIC_FAILURE = 'OBSERVED_LINEAGE_FAILED_SOURCE_DETAIL_WITHHELD'
# The adopted amendment that already fixes the analysis population (full robotic cohort,
# conventional laparoscopic excluded by design). Read for its digest only; never written.
AMENDMENT_RELATIVE = 'ANALYSIS_AMENDMENT_OBSERVED_ASSESSMENTS.md'
HUMAN_APPROVAL_KIND = 'manager-recorded-human-category-mapping-approval'
MANAGER_ENCODING_KIND = 'manager-encoding-of-authorized-category-rule'
STABLE_CODE = re.compile(r'^[A-Z0-9_]{4,64}$')
DATE_SHAPED = re.compile(r'\d{4}-\d{2}-\d{2}')

# Relative destinations inside the manuscript workspace. Nothing else may be written.
REL = {
    'population_dir': 'analysis/restricted/population',
    'master': 'analysis/restricted/population/master-population.csv',
    'master_inventory': 'analysis/restricted/population/master-identity-inventory.json',
    'category_authority': 'analysis/restricted/population/population-category-authority.json',
    'analytic_input': 'analysis/restricted/population/m1-observed-analytic-input.csv',
    'source_inventory': 'analysis/restricted/population/m1-observed-source-identity-inventory.json',
    'derived_inventory': 'analysis/restricted/population/m1-observed-derived-identity-inventory.json',
    'unit_overlap': 'analysis/restricted/population/m1-observed-review-unit-overlap.csv',
    'catalog': 'project/source-population-catalog.json',
    'authority_index': 'project/population-authority.json',
    'prior_inventory': 'project/prior-population-inventory.json',
    'lineage': 'analysis/M1-OBSERVED/input-lineage.json',
    'receipt': 'analysis/M1-OBSERVED/lineage-receipt.json',
    'dictionary': 'evidence/VARIABLE_MAP.csv',
    'decision': 'project/managed-binding-decision.json',
    'selection_script': 'scripts/06_derive_observed_assessments.py',
    'lineage_script': 'scripts/09_build_observed_lineage.py',
}
RESTRICTED_OUTPUTS = ('master', 'master_inventory', 'category_authority', 'analytic_input',
                      'source_inventory', 'derived_inventory', 'unit_overlap', 'lineage')
AGGREGATE_OUTPUTS = ('catalog', 'authority_index', 'prior_inventory', 'receipt')
PRIOR_ROOTS = ('analysis/preparation', 'analysis/restricted/stage1_preparation')

# Structured proposal. It is not an approval. A build requires a manager-recorded human
# approval whose digest equals PROPOSED_MAPPING_SHA256 (see category_mapping_digest).
PROPOSED_CATEGORY_MAPPING = {
    'da Vinci': {'decision': 'mapped', 'mapped_class': MAPPED_CLASS,
                 'expected_flag': 'true',
                 'rationale': 'Released operative platform is a robotic system. The adopted amendment analyses the '
                              'authoritative robotic cohort; the released robotic_platform_used flag must agree.'},
    'da Vinci SP': {'decision': 'mapped', 'mapped_class': MAPPED_CLASS,
                    'expected_flag': 'true',
                    'rationale': 'Released operative platform is a robotic system. The adopted amendment analyses the '
                                 'authoritative robotic cohort; the released robotic_platform_used flag must agree.'},
    'Versius': {'decision': 'mapped', 'mapped_class': MAPPED_CLASS,
                'expected_flag': 'true',
                'rationale': 'Released operative platform is a robotic system. The adopted amendment analyses the '
                             'authoritative robotic cohort; the released robotic_platform_used flag must agree.'},
    'Laparoscopic': {'decision': 'scientifically-excluded', 'mapped_class': '',
                     'expected_flag': 'false',
                     'rationale': 'Released operative platform is non-robotic. The adopted analysis target is the '
                                  'robotic cohort (ANALYSIS_AMENDMENT_OBSERVED_ASSESSMENTS.md, policy P0), so this '
                                  'category is outside the analysis population by design, not by uncertainty.'},
}


class LineageError(Exception):
    """Stable-code failure. The message is a code, never source content."""


def require(ok, code):
    if not ok:
        raise LineageError(code)


def unique_map(frame: pd.DataFrame, column: str, code: str) -> dict:
    """``dict(zip(...))`` silently keeps the last row; a duplicated identity must fail closed."""
    require(frame[ID].is_unique, code)
    return dict(zip(frame[ID], frame[column]))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value) -> str:
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def category_mapping_digest(mapping=PROPOSED_CATEGORY_MAPPING) -> str:
    public = {k: {'decision': v['decision'], 'mapped_class': v['mapped_class'], 'expected_flag': v['expected_flag'],
                  'rationale': v['rationale']} for k, v in mapping.items()}
    return sha256_bytes(json.dumps(public, sort_keys=True).encode('utf-8'))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / 'scripts' / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_cli(cli_path=CLI_PATH):
    spec = importlib.util.spec_from_file_location('manuscript_cli_for_lineage', cli_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------------------
# Human authority inputs (safe project records, no patient content)
# --------------------------------------------------------------------------------------

def load_decision(path: Path) -> dict:
    record = json.loads(path.read_text())
    require(record.get('record_kind') == 'manager-recorded-human-binding-decision', 'DECISION_RECORD_KIND')
    approved = record.get('approved_declarations') or {}
    for field in ('population_accountable_identity', 'tier_approver', 'authoritative_category_field_id',
                  'authoritative_release'):
        require(isinstance(approved.get(field), str) and approved[field].strip(), 'DECISION_FIELD_MISSING')
    require(approved['authoritative_category_field_id'] == CATEGORY_FIELD, 'DECISION_CATEGORY_FIELD_MISMATCH')
    require(approved['authoritative_release'] == RELEASE_RELATIVE, 'DECISION_RELEASE_MISMATCH')
    require(isinstance(record.get('human_identity'), str) and record['human_identity'].strip(), 'DECISION_HUMAN_MISSING')
    require(isinstance(record.get('analyst_identity'), str) and record['analyst_identity'].strip(),
            'DECISION_ANALYST_MISSING')
    require(isinstance(record.get('decision_id'), str) and record['decision_id'].strip(), 'DECISION_ID_MISSING')
    return {'accountable_identity': approved['population_accountable_identity'],
            'approved_by': record['human_identity'], 'tier_approver': approved['tier_approver'],
            'category_field': approved['authoritative_category_field_id'], 'decision_id': record['decision_id'],
            'human_identity': record['human_identity'], 'analyst_identity': record['analyst_identity']}


def expected_approval_facts(decision: dict, governing_amendment_sha256: str) -> dict:
    """The facts an authorization record must match, taken only from validated records.

    Every value here is read from the validated binding decision, computed from the
    mapping this script actually applies, or hashed from the governing amendment file.
    None of it is taken from the authorization record itself, so the record cannot
    self-attest its own authority.
    """
    require(isinstance(governing_amendment_sha256, str) and len(governing_amendment_sha256) == 64,
            'GOVERNING_AMENDMENT_DIGEST_INVALID')
    return {'mapping_sha256': category_mapping_digest(),
            'binding_decision_id': decision['decision_id'],
            'governing_amendment_sha256': governing_amendment_sha256,
            'human_authority': decision['human_identity'],
            'recorded_by': decision['analyst_identity']}


UNFILLED_PLACEHOLDER = re.compile(r'^<.*>$')


def nonempty(record: dict, field: str) -> bool:
    """A nonblank string that is not an unfilled ``<PENDING: ...>`` template placeholder."""
    value = record.get(field)
    return (isinstance(value, str) and bool(value.strip())
            and not UNFILLED_PLACEHOLDER.match(value.strip()))


def validate_mapping_approval(record: dict, expected: dict) -> dict:
    """Pure validation of a category-mapping authorization record against ``expected``.

    Two record kinds are authorization, and they are never conflated:

    * ``manager-recorded-human-category-mapping-approval`` — an actual *new* human answer
      approving the mapping. It must carry the exact mapping digest and the population
      authority from the binding decision as approver.
    * ``manager-encoding-of-authorized-category-rule`` — the manager's truthful statement
      that the mapping only encodes the already-adopted amendment scope (the full robotic
      cohort, conventional laparoscopic excluded by design). No new human answer is
      claimed, so the record must bind itself to the exact mapping digest, the binding
      decision it derives from, the digest of the governing amendment, the human authority
      of that decision and the analyst who recorded it, with a stated rationale and source.

    Any other record kind, or any mismatch against ``expected``, is invalid. Nothing here
    reads the filesystem or the release, so it is fully synthetic-testable.
    """
    kind = record.get('record_kind')
    problems = []
    if kind == HUMAN_APPROVAL_KIND:
        basis = 'new-human-category-mapping-approval'
        if record.get('mapping_sha256') != expected['mapping_sha256']:
            problems.append('mapping_digest_mismatch')
        if record.get('approved_by') != expected['human_authority']:
            problems.append('approver_differs_from_population_authority')
        if not nonempty(record, 'source'):
            problems.append('no_approval_source')
    elif kind == MANAGER_ENCODING_KIND:
        basis = 'manager-encoding-of-authorized-amendment-scope'
        if record.get('mapping_sha256') != expected['mapping_sha256']:
            problems.append('mapping_digest_mismatch')
        if record.get('binding_decision_id') != expected['binding_decision_id']:
            problems.append('binding_decision_id_mismatch')
        if record.get('governing_amendment_sha256') != expected['governing_amendment_sha256']:
            problems.append('governing_amendment_sha256_mismatch')
        if record.get('human_authority') != expected['human_authority']:
            problems.append('human_authority_differs_from_binding_decision')
        if record.get('recorded_by') != expected['recorded_by']:
            problems.append('recorded_by_is_not_the_binding_decision_analyst')
        if record.get('new_human_decision_claimed') is not False:
            problems.append('encoding_record_must_declare_no_new_human_decision')
        if not nonempty(record, 'rationale'):
            problems.append('no_encoding_rationale')
        if not nonempty(record, 'source'):
            problems.append('no_approval_source')
    else:
        basis = 'none'
        problems.append('wrong_record_kind')
    return {'present': True, 'valid': not problems, 'record_kind': kind if isinstance(kind, str) else '',
            'authorization_basis': basis if not problems else 'none',
            'reason': ','.join(problems) or 'authorized',
            'mapping_sha256': expected['mapping_sha256'],
            'checked_against': {k: v for k, v in sorted(expected.items())}}


def load_mapping_approval(path: Path | None, expected: dict) -> dict:
    """Read an authorization record and validate it against the expected facts."""
    if path is None:
        return {'present': False, 'valid': False, 'reason': 'no_category_mapping_approval_supplied',
                'authorization_basis': 'none', 'mapping_sha256': expected['mapping_sha256']}
    if not path.is_file():
        return {'present': False, 'valid': False, 'reason': 'category_mapping_approval_path_missing',
                'authorization_basis': 'none', 'mapping_sha256': expected['mapping_sha256']}
    try:
        record = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {'present': True, 'valid': False, 'reason': 'category_mapping_approval_malformed_json',
                'authorization_basis': 'none', 'mapping_sha256': expected['mapping_sha256']}
    if not isinstance(record, dict):
        return {'present': True, 'valid': False, 'reason': 'category_mapping_approval_not_an_object',
                'authorization_basis': 'none', 'mapping_sha256': expected['mapping_sha256']}
    return validate_mapping_approval(record, expected)


# --------------------------------------------------------------------------------------
# Pure assembly from in-memory inputs (release-independent, synthetic-testable)
# --------------------------------------------------------------------------------------

def category_table(patients: pd.DataFrame) -> pd.DataFrame:
    """Source identities with their authoritative category and reconciliation fields."""
    require(ID in patients.columns and CATEGORY_COLUMN in patients.columns, 'MASTER_COLUMNS_MISSING')
    table = patients[[ID, CATEGORY_COLUMN] + [c for c in (FLAG_COLUMN, CONFLICT_COLUMN) if c in patients.columns]].copy()
    for column in (FLAG_COLUMN, CONFLICT_COLUMN):
        if column not in table.columns:
            table[column] = ''
    table = table.astype(str)
    ids = table[ID].str.strip()
    require(ids.ne('').all(), 'MASTER_IDENTITY_BLANK')
    require(ids.is_unique, 'MASTER_IDENTITY_DUPLICATED')
    table[ID] = ids
    table[CATEGORY_COLUMN] = table[CATEGORY_COLUMN].str.strip()
    require(table[CATEGORY_COLUMN].ne('').all(), 'MASTER_CATEGORY_BLANK')
    table['_flag'] = table[FLAG_COLUMN].str.strip().str.lower().map(
        lambda v: 'true' if v in ('true', '1', '1.0') else 'false' if v in ('false', '0', '0.0') else 'blank' if v == '' else 'other')
    table['_conflict'] = table[CONFLICT_COLUMN].str.strip().str.lower().isin(['true', '1', '1.0'])
    return table.sort_values(ID, kind='stable').reset_index(drop=True)


def reconcile_categories(table: pd.DataFrame, mapping=PROPOSED_CATEGORY_MAPPING) -> dict:
    """Disposition of every source identity from the category authority proposal.

    A category outside the mapping, or a mapped/excluded category whose released robotic
    flag disagrees for an identity, yields ``unresolved`` for that identity. Nothing is
    overridden; the disagreement is reported for a human decision.
    """
    decisions = {}
    per_identity = {}
    categories = {}
    for category, group in table.groupby(CATEGORY_COLUMN, sort=True):
        spec = mapping.get(category)
        flags = group['_flag'].value_counts().to_dict()
        conflicts = int(group['_conflict'].sum())
        entry = {'observed_count': int(len(group)), 'robotic_flag_counts': {k: int(v) for k, v in sorted(flags.items())},
                 'platform_conflict_flag_true': conflicts}
        if spec is None:
            entry.update({'decision': 'unresolved', 'mapped_class': '', 'discrepant_identities': int(len(group)),
                          'reason': 'category_not_in_approved_mapping'})
            for pid in group[ID]:
                per_identity[pid] = ('unresolved', '', 'Category has no accountable mapping decision.')
        else:
            discrepant = group.loc[group['_flag'].ne(spec['expected_flag']), ID]
            entry.update({'decision': spec['decision'], 'mapped_class': spec['mapped_class'],
                          'discrepant_identities': int(len(discrepant)),
                          'reason': 'released_robotic_flag_disagrees_with_category' if len(discrepant) else 'consistent'})
            discrepant_set = set(discrepant)
            for pid in group[ID]:
                if pid in discrepant_set:
                    per_identity[pid] = ('unresolved', '', 'Released robotic flag disagrees with the authoritative '
                                                           'platform category; human reconciliation required.')
                else:
                    per_identity[pid] = (spec['decision'], spec['mapped_class'], spec['rationale'])
            if len(discrepant):
                entry['decision'] = 'unresolved'
                entry['mapped_class'] = ''
        categories[category] = entry
        decisions[category] = entry
    return {'categories': categories, 'per_identity': per_identity}


def policy_status_frame(policy_results: dict, mapped_ids: set) -> pd.DataFrame:
    """One row per retained (mapped) identity with the status of every policy.

    Columns express assessment or missing status per policy; nothing is dropped. Every
    identity in ``mapped_ids`` appears exactly once.
    """
    frame = pd.DataFrame({ID: sorted(mapped_ids)})
    for policy in POLICIES:
        result = policy_results.get(policy)
        prefix = policy + '_'
        if result is None:
            frame[prefix + 'status'] = 'policy_not_executed'
            continue
        selected = result['selected']
        early = selected.get('early')
        early_status = {}
        if early is not None and len(early):
            early_status = unique_map(early, '_status', 'POLICY_SELECTED_IDENTITY_DUPLICATED')
        frame[prefix + 'early_status'] = frame[ID].map(
            lambda pid: {0: 'pad_use', 1: 'pad_free'}.get(early_status.get(pid), 'no_selected_early_status'))
        for window in LATER_WINDOWS:
            later = selected.get(window)
            values = (unique_map(later, '_status', 'POLICY_SELECTED_IDENTITY_DUPLICATED')
                      if later is not None and len(later) else {})
            frame[prefix + window + '_status'] = frame[ID].map(
                lambda pid, values=values: {0: 'pad_use', 1: 'pad_free'}.get(values.get(pid), 'no_selected_status'))
        burden = result.get('burden')
        if burden is not None and len(burden) and '_burden' in burden.columns:
            levels = unique_map(burden, '_burden', 'POLICY_BURDEN_IDENTITY_DUPLICATED')
            frame[prefix + 'early_burden'] = frame[ID].map(lambda pid: levels.get(pid, 'not_applicable'))
        else:
            frame[prefix + 'early_burden'] = 'not_applicable_under_policy'
        excluded = set(result.get('excluded_ids', set()))
        frame[prefix + 'excluded_before_selection'] = frame[ID].isin(excluded)
    return frame


def policy_counts(policy_results: dict) -> dict:
    counts = {}
    for policy, result in policy_results.items():
        sets = result['sets']
        block = {'early_status_known': len(sets['early_status_known']), 'early_users': len(sets['early_users']),
                 'early_users_with_year': len(sets.get('early_users_with_year', set())),
                 'year_padfree_in_early_user_pairs': len(sets.get('year_padfree_in_early_user_pairs', set())),
                 'early_users_without_year': len(sets.get('early_users_without_year', set())),
                 'observation_rule': result.get('observation_rule', ''),
                 'excluded_before_selection': int(len(result.get('excluded_ids', set())))}
        burden = result.get('burden')
        if burden is not None and len(burden) and '_burden' in burden.columns:
            levels = unique_map(burden, '_burden', 'POLICY_BURDEN_IDENTITY_DUPLICATED')
            users, pairs = sets['early_users'], sets.get('early_users_with_year', set())
            free = sets.get('year_padfree_in_early_user_pairs', set())
            block['early_burden'] = {lvl: sum(1 for p in users if levels.get(p) == lvl) for lvl in BURDEN_LEVELS}
            block['paired_burden'] = {lvl: sum(1 for p in pairs if levels.get(p) == lvl) for lvl in BURDEN_LEVELS}
            block['year_padfree_by_burden'] = {lvl: sum(1 for p in free if levels.get(p) == lvl) for lvl in BURDEN_LEVELS}
        else:
            block['early_burden'] = 'not_applicable_under_policy'
        counts[policy] = block
    return counts


def unit_overlap(units: list, policy_results: dict, per_identity: dict, windows_by_policy: dict) -> tuple:
    """Actual overlap of historical patient-day review units with every policy.

    Returns a restricted per-unit frame (identity, day-level classification per policy)
    and an aggregate block with counts only. Classification per exact-day policy:

    * ``selected_<window>_day``: the unit day is the policy's selected day for that window.
    * ``in_window_not_selected``: the day lies in a policy window but another day was
      selected or the day was rule-classified unavailable (conflict) — the policy's own rule
      already expresses this; no fact was resolved.
    * ``identity_without_selected_early_status``: identity retained but no early status
      under the policy, so the unit cannot change a policy estimate without new selection.
    * ``off_window``: outside every policy window.
    * ``identity_outside_analysis_population``: the identity is not mapped into the cohort.
    P5 has no selected day; overlap is identity-level only.

    Exposure counts are reported twice and named accordingly: ``*_units`` counts review
    units (patient-days), ``*_people`` counts distinct identities. A patient with units on
    two different selected later days is two units and one person, and may be the same
    person already counted on a selected early day, so the early/later intersection and
    the later-only remainder are reported as well. Never read a ``*_units`` count as a
    number of patients.
    """
    rows = []
    aggregate = {'units_total': len(units), 'identities_total': len({u[ID] for u in units}),
                 'units_on_identities_outside_analysis_population': 0,
                 'units_on_unresolved_identities': 0, 'by_policy': {}}
    unit_days = []
    for unit in units:
        require(isinstance(unit.get(ID), str) and unit[ID] != '', 'REVIEW_UNIT_IDENTITY_BLANK')
        day = pd.to_datetime(unit.get('grouping_value'), errors='coerce', format='%Y-%m-%d')
        unit_days.append(day)
    for policy in POLICIES:
        result = policy_results.get(policy)
        if result is None:
            continue
        selected = result['selected']
        sel_maps = {}
        for window in ALL_WINDOWS:
            frame = selected.get(window)
            if frame is not None and len(frame):
                require(frame[ID].is_unique, 'POLICY_SELECTED_IDENTITY_DUPLICATED')
                sel_maps[window] = dict(zip(frame[ID], pd.to_datetime(frame['_date'])))
        burden_map = {}
        burden = result.get('burden')
        if burden is not None and len(burden) and '_burden' in burden.columns:
            burden_map = unique_map(burden, '_burden', 'POLICY_BURDEN_IDENTITY_DUPLICATED')
        day_index = result.get('day_index', {})  # identity -> {date -> postoperative day}
        windows = windows_by_policy.get(policy, {})
        sets = result['sets']
        users, pairs = sets['early_users'], sets.get('early_users_with_year', set())
        block = {'units': {}, 'identities': {}, 'selected_early_day_units_by_pattern': {p: 0 for p in EVIDENCE_PATTERNS},
                 'selected_day_units_by_pattern_by_window': {w: {p: 0 for p in EVIDENCE_PATTERNS} for w in ALL_WINDOWS},
                 'selected_early_day_early_user_units': 0, 'selected_early_day_paired_early_user_units': 0,
                 'selected_early_day_paired_by_burden_units': {lvl: 0 for lvl in BURDEN_LEVELS},
                 'selected_later_day_paired_early_user_units': 0}
        early_day_users, early_day_paired, later_day_paired = set(), set(), set()
        ident = {}
        for unit, day in zip(units, unit_days):
            pid = unit[ID]
            disposition = per_identity.get(pid, ('unresolved', '', ''))[0]
            if disposition == 'scientifically-excluded':
                cls = 'identity_outside_analysis_population'
            elif disposition != 'mapped':
                cls = 'identity_unresolved'
            elif policy == 'P5':
                cls = ('identity_in_P5_early_users' if pid in users else 'identity_not_in_P5_early_users')
                cls += '_day_unit_not_comparable_to_milestone_rule'
            elif pid in set(result.get('excluded_ids', set())):
                cls = 'identity_excluded_before_selection_by_policy'
            elif pd.isna(day):
                cls = 'undated_unit'
            else:
                hit = [w for w, m in sel_maps.items() if pid in m and m[pid] == day]
                if hit:
                    cls = 'selected_' + '+'.join(sorted(hit)) + '_day'
                    patterns = unit.get('evidence_patterns_stage0_valid_same_day', [])
                    for window in hit:
                        for pattern in patterns:
                            if pattern in block['selected_day_units_by_pattern_by_window'][window]:
                                block['selected_day_units_by_pattern_by_window'][window][pattern] += 1
                    if 'early' in hit:
                        if pid in users:
                            block['selected_early_day_early_user_units'] += 1
                            early_day_users.add(pid)
                        if pid in pairs:
                            block['selected_early_day_paired_early_user_units'] += 1
                            early_day_paired.add(pid)
                            lvl = burden_map.get(pid)
                            if lvl in block['selected_early_day_paired_by_burden_units']:
                                block['selected_early_day_paired_by_burden_units'][lvl] += 1
                        for pattern in patterns:
                            if pattern in block['selected_early_day_units_by_pattern']:
                                block['selected_early_day_units_by_pattern'][pattern] += 1
                    if any(w in LATER_WINDOWS for w in hit) and pid in pairs:
                        # One unit, even if it were somehow the selected day of two later
                        # windows: this counts exposed units, not window hits.
                        block['selected_later_day_paired_early_user_units'] += 1
                        later_day_paired.add(pid)
                else:
                    post_day = day_index.get(pid, {}).get(day)
                    if post_day is None:
                        cls = 'no_valid_candidate_row_on_unit_day'
                    else:
                        in_windows = [w for w, (lo, hi, _t) in windows.items() if lo <= post_day <= hi]
                        if in_windows:
                            cls = 'in_window_not_selected'
                        elif pid not in sets['early_status_known']:
                            cls = 'off_window_identity_without_selected_early_status'
                        else:
                            cls = 'off_window'
            block['units'][cls] = block['units'].get(cls, 0) + 1
            ident.setdefault(cls, set()).add(pid)
            rows.append({ID: pid, 'review_unit_id': unit.get('review_unit_id', ''), 'policy': policy, 'overlap_class': cls})
        block['identities'] = {k: len(v) for k, v in sorted(ident.items())}
        block['selected_early_day_early_user_people'] = len(early_day_users)
        block['selected_early_day_paired_early_user_people'] = len(early_day_paired)
        block['selected_early_day_paired_people_by_burden'] = {
            lvl: sum(1 for p in early_day_paired if burden_map.get(p) == lvl) for lvl in BURDEN_LEVELS}
        block['selected_later_day_paired_early_user_people'] = len(later_day_paired)
        block['paired_early_users_with_early_and_later_selected_day_units'] = len(early_day_paired & later_day_paired)
        block['paired_early_users_with_later_but_no_early_selected_day_unit'] = len(later_day_paired - early_day_paired)
        block['paired_early_users_with_any_selected_day_unit_people'] = len(early_day_paired | later_day_paired)
        if policy == 'P5':
            # No selected day exists under the milestone rule, so a zero here would read as
            # a measured absence of day-level exposure. State non-comparability instead.
            for key in ('selected_early_day_units_by_pattern', 'selected_day_units_by_pattern_by_window',
                        'selected_early_day_early_user_units', 'selected_early_day_early_user_people',
                        'selected_early_day_paired_early_user_units', 'selected_early_day_paired_early_user_people',
                        'selected_early_day_paired_by_burden_units', 'selected_early_day_paired_people_by_burden',
                        'selected_later_day_paired_early_user_units', 'selected_later_day_paired_early_user_people',
                        'paired_early_users_with_early_and_later_selected_day_units',
                        'paired_early_users_with_later_but_no_early_selected_day_unit',
                        'paired_early_users_with_any_selected_day_unit_people'):
                block[key] = 'not_applicable_no_selected_day_under_milestone_rule'
        aggregate['by_policy'][policy] = block
    first = policy_results.get(POLICIES[0])
    if first is not None:
        for unit in units:
            d = per_identity.get(unit[ID], ('unresolved',))[0]
            aggregate['units_on_identities_outside_analysis_population'] += int(d == 'scientifically-excluded')
            aggregate['units_on_unresolved_identities'] += int(d not in ('mapped', 'scientifically-excluded'))
    return pd.DataFrame(rows, columns=[ID, 'review_unit_id', 'policy', 'overlap_class']), aggregate


def assemble(table: pd.DataFrame, reconciliation: dict, policy_results: dict, decision: dict,
             context_hashes: dict, prior_inventory: dict, data_snapshot_id: str, pipeline_snapshot_id: str,
             units: list | None = None, windows_by_policy: dict | None = None) -> dict:
    """Assemble every artifact as bytes plus the aggregate receipt, without writing."""
    per_identity = reconciliation['per_identity']
    mapped_ids = {pid for pid, (d, _c, _r) in per_identity.items() if d == 'mapped'}
    status = policy_status_frame(policy_results, mapped_ids)
    units = units or []
    overlap_frame, overlap = unit_overlap(units, policy_results, per_identity, windows_by_policy or {})
    if len(overlap_frame):
        exposure = overlap_frame.loc[overlap_frame.overlap_class.str.startswith('selected_')]
        exposed = exposure.groupby([ID, 'policy']).overlap_class.agg(lambda s: '|'.join(sorted(set(s)))).unstack('policy')
        for policy in POLICIES:
            col = exposed[policy] if policy in exposed.columns else pd.Series(dtype=str)
            status[policy + '_review_unit_on_selected_day'] = status[ID].map(col).fillna('none')
        unit_counts = overlap_frame.drop_duplicates([ID, 'review_unit_id']).groupby(ID).size()
        status['historical_review_units_on_identity'] = status[ID].map(unit_counts).fillna(0).astype(int)
    else:
        for policy in POLICIES:
            status[policy + '_review_unit_on_selected_day'] = 'none'
        status['historical_review_units_on_identity'] = 0

    master_csv = table[[ID, CATEGORY_COLUMN, FLAG_COLUMN, CONFLICT_COLUMN]].to_csv(index=False).encode('utf-8')
    master_sha = sha256_bytes(master_csv)
    master_records = [{'record_id': pid, 'source_category_id': cat}
                      for pid, cat in zip(table[ID], table[CATEGORY_COLUMN])]
    master_inventory = {'record_kind': 'project-population-identity-inventory', 'authority_id': AUTHORITY_ID,
                        'identity_namespace': IDENTITY_NAMESPACE, 'authoritative_category_field_id': CATEGORY_FIELD,
                        'artifact_path': REL['master'], 'artifact_sha256': master_sha, 'records': master_records}
    master_inventory_bytes = canonical_json(master_inventory).encode('utf-8')

    decisions = []
    for category, entry in reconciliation['categories'].items():
        ids = sorted(table.loc[table[CATEGORY_COLUMN].eq(category), ID])
        spec = PROPOSED_CATEGORY_MAPPING.get(category)
        rationale = (spec['rationale'] if spec and entry['decision'] != 'unresolved'
                     else 'Unresolved: ' + entry['reason'] + '. Requires accountable human reconciliation.')
        decisions.append({'source_category_id': category, 'decision': entry['decision'],
                          'mapped_class': entry['mapped_class'], 'record_ids': ids,
                          'accountable_identity': decision['accountable_identity'], 'rationale': rationale})
    category_authority = {'record_kind': 'project-population-category-authority', 'authority_id': AUTHORITY_ID,
                          'accountable_identity': decision['accountable_identity'],
                          'authoritative_category_field_id': CATEGORY_FIELD, 'decisions': decisions}
    category_authority_bytes = canonical_json(category_authority).encode('utf-8')
    prior_public = {k: v for k, v in prior_inventory.items() if not k.startswith('_')}
    prior_bytes = canonical_json(prior_public).encode('utf-8')

    group = {'record_kind': 'project-population-authority-group', 'authority_id': AUTHORITY_ID,
             'accountable_identity': decision['accountable_identity'], 'identity_namespace': IDENTITY_NAMESPACE,
             'authoritative_category_field_id': CATEGORY_FIELD, 'master_artifact_path': REL['master'],
             'master_artifact_sha256': master_sha, 'master_identity_inventory_path': REL['master_inventory'],
             'master_identity_inventory_sha256': sha256_bytes(master_inventory_bytes),
             'category_authority_path': REL['category_authority'],
             'category_authority_sha256': sha256_bytes(category_authority_bytes),
             'prior_population_inventory_path': REL['prior_inventory'],
             'prior_population_inventory_sha256': sha256_bytes(prior_bytes)}
    catalog = {'record_kind': 'project-source-population-catalog', 'accountable_identity': decision['accountable_identity'],
               'approval_kind': 'human-project-approval', 'approved_by': decision['approved_by'], 'populations': [group]}
    catalog_bytes = canonical_json(catalog).encode('utf-8')
    authority_index = {'record_kind': 'project-population-authority-index',
                       'source_population_catalog_path': REL['catalog'],
                       'source_population_catalog_sha256': sha256_bytes(catalog_bytes), 'authority_groups': [group]}
    authority_bytes = canonical_json(authority_index).encode('utf-8')

    analytic_csv = status.to_csv(index=False).encode('utf-8')
    analytic_sha = sha256_bytes(analytic_csv)
    source_records = [{'source_node_id': 'source-master', 'record_id': r['record_id'],
                       'source_category_id': r['source_category_id']} for r in master_records]
    derived_records = [{'derived_node_id': 'derived-analytic-input', 'record_id': pid, 'mapped_class': MAPPED_CLASS}
                       for pid in status[ID]]
    source_inventory = {'record_kind': 'analysis-record-identity-inventory', 'identity_namespace': IDENTITY_NAMESPACE,
                        'authoritative_category_field_id': CATEGORY_FIELD, 'node_id': 'source-master',
                        'node_kind': 'source-snapshot', 'artifact_path': REL['master'], 'artifact_sha256': master_sha,
                        'records': source_records}
    derived_inventory = {'record_kind': 'analysis-record-identity-inventory', 'identity_namespace': IDENTITY_NAMESPACE,
                         'authoritative_category_field_id': '', 'node_id': 'derived-analytic-input',
                         'node_kind': 'derived-analytic-input', 'artifact_path': REL['analytic_input'],
                         'artifact_sha256': analytic_sha, 'records': derived_records}
    source_inventory_bytes = canonical_json(source_inventory).encode('utf-8')
    derived_inventory_bytes = canonical_json(derived_inventory).encode('utf-8')

    dispositions = []
    for pid, cat in zip(table[ID], table[CATEGORY_COLUMN]):
        d, cls, rationale = per_identity[pid]
        dispositions.append({'source_node_id': 'source-master', 'record_id': pid, 'source_category_id': cat,
                             'disposition': d, 'mapped_class': cls,
                             'derived_node_id': 'derived-analytic-input' if d == 'mapped' else '',
                             'derived_record_id': pid if d == 'mapped' else '', 'rationale': rationale})
    observed = [{'source_node_id': 'source-master', 'source_category_id': c, 'observed_count': e['observed_count']}
                for c, e in reconciliation['categories'].items()]
    category_reconciliation = []
    for c, e in reconciliation['categories'].items():
        derived_n = sum(1 for pid in table.loc[table[CATEGORY_COLUMN].eq(c), ID] if per_identity[pid][0] == 'mapped')
        category_reconciliation.append({'source_node_id': 'source-master', 'source_category_id': c,
                                        'observed_count': e['observed_count'], 'disposition': e['decision'],
                                        'mapped_class': e['mapped_class'], 'derived_count': derived_n,
                                        'dropped_count': e['observed_count'] - derived_n,
                                        'rationale': next(x['rationale'] for x in decisions if x['source_category_id'] == c)})
    nodes = [
        {'node_id': 'source-master', 'node_kind': 'source-snapshot', 'path': REL['master'], 'sha256': master_sha,
         'identity_inventory_path': REL['source_inventory'],
         'identity_inventory_sha256': sha256_bytes(source_inventory_bytes)},
        {'node_id': 'project-dictionary', 'node_kind': 'project-dictionary', 'path': REL['dictionary'],
         'sha256': context_hashes['dictionary'], 'identity_inventory_path': '', 'identity_inventory_sha256': ''},
        {'node_id': 'binding-decision', 'node_kind': 'project-adjudication', 'path': REL['decision'],
         'sha256': context_hashes['decision'], 'identity_inventory_path': '', 'identity_inventory_sha256': ''},
        {'node_id': 'selection-transform', 'node_kind': 'cohort-transform', 'path': REL['selection_script'],
         'sha256': context_hashes['selection_script'], 'identity_inventory_path': '', 'identity_inventory_sha256': ''},
        {'node_id': 'lineage-transform', 'node_kind': 'cohort-transform', 'path': REL['lineage_script'],
         'sha256': context_hashes['lineage_script'], 'identity_inventory_path': '', 'identity_inventory_sha256': ''},
        {'node_id': 'derived-analytic-input', 'node_kind': 'derived-analytic-input', 'path': REL['analytic_input'],
         'sha256': analytic_sha, 'identity_inventory_path': REL['derived_inventory'],
         'identity_inventory_sha256': sha256_bytes(derived_inventory_bytes)},
    ]
    edges = [{'from_node_id': a, 'to_node_id': b} for a, b in (
        ('source-master', 'project-dictionary'), ('source-master', 'binding-decision'),
        ('project-dictionary', 'selection-transform'), ('binding-decision', 'selection-transform'),
        ('selection-transform', 'lineage-transform'), ('lineage-transform', 'derived-analytic-input'))]
    lineage = {'record_kind': 'analysis-input-lineage', 'analysis_id': ANALYSIS_ID, 'data_snapshot_id': data_snapshot_id,
               'pipeline_snapshot_id': pipeline_snapshot_id, 'population_authority_id': AUTHORITY_ID,
               'authoritative_category_field_id': CATEGORY_FIELD, 'input_record_count': int(len(table)),
               'output_record_count': int(len(status)), 'dropped_record_count': int(len(table) - len(status)),
               'nodes': nodes, 'edges': edges, 'identity_namespace': IDENTITY_NAMESPACE,
               'source_records': source_records, 'derived_records': derived_records,
               'record_dispositions': dispositions, 'observed_categories': observed,
               'category_reconciliation': category_reconciliation}
    lineage_bytes = canonical_json(lineage).encode('utf-8')
    overlap_bytes = overlap_frame.to_csv(index=False).encode('utf-8')

    artifacts = {'master': master_csv, 'master_inventory': master_inventory_bytes,
                 'category_authority': category_authority_bytes, 'analytic_input': analytic_csv,
                 'source_inventory': source_inventory_bytes, 'derived_inventory': derived_inventory_bytes,
                 'unit_overlap': overlap_bytes, 'catalog': catalog_bytes, 'authority_index': authority_bytes,
                 'prior_inventory': prior_bytes, 'lineage': lineage_bytes}
    disposition_counts = {}
    for d, _c, _r in per_identity.values():
        disposition_counts[d] = disposition_counts.get(d, 0) + 1
    receipt = {
        'record_kind': 'aggregate-observed-lineage-receipt',
        'analysis_id': ANALYSIS_ID, 'population_authority_id': AUTHORITY_ID,
        'authoritative_category_field_id': CATEGORY_FIELD, 'identity_namespace': IDENTITY_NAMESPACE,
        'accountable_identity': decision['accountable_identity'], 'approved_by': decision['approved_by'],
        'binding_decision_id': decision.get('decision_id'),
        'category_mapping_sha256': category_mapping_digest(),
        'identity_accounting': {'input_record_count': lineage['input_record_count'],
                                'output_record_count': lineage['output_record_count'],
                                'dropped_record_count': lineage['dropped_record_count'],
                                'dispositions': disposition_counts,
                                'categories': reconciliation['categories'],
                                'retained_identities_mapped_once': bool(status[ID].is_unique and len(status) == len(mapped_ids))},
        'policy_counts': policy_counts(policy_results),
        'policy_status_columns': [c for c in status.columns if c != ID],
        'review_unit_overlap': overlap,
        'artifact_sha256': {key: sha256_bytes(value) for key, value in artifacts.items()},
        'artifact_paths': {key: REL[key] for key in artifacts},
        'context_sha256': context_hashes,
        'prior_population_summary': prior_inventory.get('_summary', {}),
        'graph': {'nodes': [(n['node_id'], n['node_kind']) for n in nodes], 'edges': [(e['from_node_id'], e['to_node_id']) for e in edges]},
    }
    return {'artifacts': artifacts, 'receipt': receipt, 'lineage': lineage, 'identities': set(table[ID])}


# --------------------------------------------------------------------------------------
# Safety guards
# --------------------------------------------------------------------------------------

RELEASE_DATE_TOKEN = RELEASE_RELATIVE.rsplit('_', 1)[-1]  # the release version date, not a patient date


def assert_safe_aggregate(text: str, identities: set, extra_forbidden=(), allowed_dates=(RELEASE_DATE_TOKEN,)):
    """No identity value, date-shaped token or forbidden token may appear in aggregate output.

    Only the release version date is permitted as a date-shaped token.
    """
    masked = text
    for token in allowed_dates:
        masked = masked.replace(token, '<release-date>')
    require(not DATE_SHAPED.search(masked), 'AGGREGATE_CONTAINS_DATE_SHAPED_TOKEN')
    for pid in identities:
        require(pid not in text, 'AGGREGATE_CONTAINS_IDENTITY')
    for token in extra_forbidden:
        require(token not in text, 'AGGREGATE_CONTAINS_FORBIDDEN_TOKEN')


def allowed_destination(workspace: Path, key: str) -> Path:
    require(key in REL, 'OUTPUT_KEY_NOT_ALLOWED')
    rel = PurePosixPath(REL[key])
    require(not rel.is_absolute() and '..' not in rel.parts, 'OUTPUT_PATH_UNSAFE')
    target = workspace.joinpath(*rel.parts)
    require(str(target.resolve()).startswith(str(workspace.resolve()) + os.sep), 'OUTPUT_ESCAPES_WORKSPACE')
    return target


def secure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink() and path.is_dir(), 'OUTPUT_DIR_REDIRECTED')
    os.chmod(path, 0o700)


def atomic_write(target: Path, data: bytes, mode: int, overwrite: bool):
    require(not target.is_symlink(), 'OUTPUT_TARGET_SYMLINK')
    if target.exists():
        require(overwrite or target.read_bytes() == data, 'OUTPUT_EXISTS_NONIDENTICAL')
    fd, tmp = tempfile.mkstemp(prefix='.tmp-', dir=str(target.parent))
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_artifacts(workspace: Path, artifacts: dict, receipt_bytes: bytes, overwrite: bool = False) -> dict:
    """Write every artifact to its allowed destination. Restricted files are owner-only."""
    written = {}
    secure_dir(allowed_destination(workspace, 'population_dir'))
    for key in RESTRICTED_OUTPUTS:
        target = allowed_destination(workspace, key)
        if key == 'lineage':
            target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, artifacts[key], 0o600, overwrite)
        written[key] = REL[key]
    for key in ('catalog', 'authority_index', 'prior_inventory'):
        target = allowed_destination(workspace, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, artifacts[key], 0o644, overwrite)
        written[key] = REL[key]
    target = allowed_destination(workspace, 'receipt')
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, receipt_bytes, 0o644, overwrite)
    written['receipt'] = REL['receipt']
    for key in RESTRICTED_OUTPUTS:
        require(stat.S_IMODE(allowed_destination(workspace, key).stat().st_mode) == 0o600, 'RESTRICTED_MODE_NOT_600')
    require(stat.S_IMODE(allowed_destination(workspace, 'population_dir').stat().st_mode) == 0o700, 'RESTRICTED_DIR_NOT_700')
    return written


# --------------------------------------------------------------------------------------
# Prior population inventory (genuine reconciliation of scoped historical populations)
# --------------------------------------------------------------------------------------

def reconcile_prior_populations(workspace: Path, master_ids: set, roots=PRIOR_ROOTS) -> dict:
    """Every file under each declared root, reconciled against the master identity set."""
    artifacts, summary = [], {'roots': list(roots), 'files': 0, 'reconciled': 0, 'not_population_bearing': 0, 'unresolved': 0}
    for root_rel in roots:
        root = workspace / root_rel
        require(root.is_dir() and not root.is_symlink(), 'PRIOR_ROOT_MISSING')
        for path in sorted(p for p in root.rglob('*') if p.is_file() and not p.is_symlink()):
            rel = path.relative_to(workspace).as_posix()
            status = classify_prior_artifact(path, master_ids)
            artifacts.append({'artifact_id': re.sub(r'[^A-Za-z0-9._-]', '-', rel), 'path': rel,
                              'sha256': sha256_file(path), 'reconciliation_status': status})
            summary['files'] += 1
            summary[status.replace('-', '_')] += 1
    return {'record_kind': 'project-prior-population-inventory', 'authority_id': AUTHORITY_ID,
            'discovery_roots': list(roots), 'artifacts': artifacts, '_summary': summary}


def classify_prior_artifact(path: Path, master_ids: set) -> str:
    if path.suffix.lower() == '.csv':
        try:
            header = list(pd.read_csv(path, dtype=str, nrows=0).columns)
        except Exception:
            header = []
        if ID in header:
            ids = set(pd.read_csv(path, dtype=str, keep_default_na=False, usecols=[ID])[ID].str.strip())
            ids.discard('')
            return 'reconciled' if ids <= master_ids and ids else 'unresolved'
    text = path.read_text(errors='ignore')
    return 'unresolved' if any(pid in text for pid in master_ids) else 'not-population-bearing'


def reconcile_external_identity_index(path: Path, master_ids: set) -> dict:
    """Counts-only reconciliation of the historical case packet identity index (outside workspace)."""
    if not path.is_file():
        return {'present': False}
    ids = set()
    with path.open() as fh:
        for line in fh:
            if line.strip():
                ids.add(json.loads(line)[ID])
    return {'present': True, 'sha256': sha256_file(path), 'identities': len(ids),
            'equal_to_master': ids == master_ids, 'only_in_index': len(ids - master_ids),
            'only_in_master': len(master_ids - ids)}


# --------------------------------------------------------------------------------------
# Official validation inside a private temporary workspace
# --------------------------------------------------------------------------------------

def official_validation(artifacts: dict, workspace_sources: dict, prior_copies: list, data_snapshot_id: str,
                        pipeline_snapshot_id: str, cli=None, contract=None) -> list:
    """Write all artifacts into a private temp workspace and run the installed validator."""
    cli = cli or load_cli()
    contract = contract or json.loads(CONTRACT_PATH.read_text())
    rules = contract['analysis_attestation_contract']
    temp = Path(tempfile.mkdtemp(prefix='m1-lineage-check-'))
    os.chmod(temp, 0o700)
    try:
        for rel, source in workspace_sources.items():
            target = temp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            os.chmod(target, 0o600)
        for rel, source in prior_copies:
            target = temp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            os.chmod(target, 0o600)
        for key, data in artifacts.items():
            if key == 'receipt':
                continue
            target = temp / REL[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            os.chmod(target, 0o600)
        row = {'input_lineage_path': REL['lineage'], 'data_snapshot_id': data_snapshot_id,
               'pipeline_snapshot_id': pipeline_snapshot_id}
        errors = []
        cli.validate_analysis_input_lineage(temp, rules, row, ANALYSIS_ID, errors)
        return errors
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def sanitize_errors(errors: list, identities: set) -> list:
    """Validator messages may quote identities; replace them before any output."""
    out = []
    for message in errors:
        text = str(message)
        for pid in identities:
            if pid in text:
                text = text.replace(pid, '<identity>')
        text = DATE_SHAPED.sub('<date>', text)
        out.append(text)
    return out


# --------------------------------------------------------------------------------------
# Release-bound execution
# --------------------------------------------------------------------------------------

def load_review_units(path: Path, master_ids: set | None = None, required: bool = True) -> list:
    """Load the historical review units, failing closed on every integrity defect.

    A missing, empty or malformed file must never degrade silently to an empty unit list:
    that would report a complete overlap measurement over zero units. When ``master_ids``
    is given, every unit identity must exist in the full source master.
    """
    require(path.is_file() or not required, 'REVIEW_UNITS_FILE_MISSING')
    if not path.is_file():
        return []
    units, seen = [], set()
    with path.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                raise LineageError('REVIEW_UNIT_MALFORMED_JSON') from None
            require(isinstance(record, dict), 'REVIEW_UNIT_NOT_AN_OBJECT')
            pid = record.get(ID)
            require(isinstance(pid, str) and pid.strip() != '', 'REVIEW_UNIT_IDENTITY_BLANK')
            unit_id = record.get('review_unit_id')
            require(isinstance(unit_id, str) and unit_id.strip() != '', 'REVIEW_UNIT_ID_BLANK')
            require(unit_id not in seen, 'REVIEW_UNIT_ID_DUPLICATED')
            seen.add(unit_id)
            patterns = record.get('evidence_patterns_stage0_valid_same_day', [])
            require(isinstance(patterns, list), 'REVIEW_UNIT_PATTERNS_MALFORMED')
            units.append({ID: pid.strip(), 'review_unit_id': unit_id,
                          'grouping_value': record.get('grouping_value', ''),
                          'evidence_patterns_stage0_valid_same_day': [str(p) for p in patterns]})
    require(units or not required, 'REVIEW_UNITS_FILE_EMPTY')
    if master_ids is not None:
        require({u[ID] for u in units} <= set(master_ids), 'REVIEW_UNIT_IDENTITY_NOT_IN_MASTER')
    return units


def wrap_policy_results(D, patients, events, milestones) -> tuple:
    """Run the adopted derivation for every policy and keep only in-memory frames."""
    results, windows = {}, {}
    for policy in POLICIES:
        result = D.derive(patients, events, milestones, policy)
        selection = result['selection']
        candidate = result['candidate']
        day_index = {}
        for pid, date_value, day in zip(candidate[ID], pd.to_datetime(candidate['_date']), candidate['_day']):
            if pd.notna(date_value) and pd.notna(day):
                day_index.setdefault(pid, {})[date_value] = int(day)
        excluded_ids = set()
        if policy == 'P4':
            reference = {key: D.select_window(candidate, window, 'nearest')[0] for key, window in D.WINDOWS.items()}
            excluded_ids = set(D.date_impact_patients(result['annotated'], result['robotic'], candidate, reference)[0])
            excluded_ids &= set(candidate[ID])
        results[policy] = {'selected': {k: v[[ID, '_date', '_status']] for k, v in selection['selected'].items()
                                        if hasattr(v, 'columns') and '_date' in v.columns}
                           if policy != 'P5' else {k: v[[ID, '_status']].assign(_date=pd.NaT)
                                                   for k, v in selection['selected'].items()},
                           'burden': selection['burden'], 'sets': result['sets'], 'excluded_ids': excluded_ids,
                           'observation_rule': selection['observation_rule'], 'day_index': day_index,
                           'robotic': set(result['robotic'])}
        windows[policy] = dict(D.NARROW_WINDOWS if policy == 'P3' else D.WINDOWS) if policy != 'P5' else {}
    return results, windows


def run(args) -> dict:
    decision = load_decision(args.decision)
    require(args.governing_amendment.is_file(), 'GOVERNING_AMENDMENT_MISSING')
    amendment_sha = sha256_file(args.governing_amendment)
    expected_facts = expected_approval_facts(decision, amendment_sha)
    approval = load_mapping_approval(args.category_mapping_approval, expected_facts)
    cli = load_cli(args.cli)
    contract = json.loads(args.contract.read_text())
    D = module('observed_assessment_derivation_for_lineage', '06_derive_observed_assessments.py')
    root = D.bind_root(D.RELEASE)
    before = D.bound_inputs()
    D.table_manifest(root)
    patients_core, events, milestones = D.read_core_tables(root)
    platform_frame = pd.read_csv(root / 'tables/patient_wide.csv', dtype=str, keep_default_na=False,
                                 usecols=[ID, CATEGORY_COLUMN, FLAG_COLUMN, CONFLICT_COLUMN])
    table = category_table(platform_frame)
    require(set(table[ID]) == set(patients_core[ID]), 'MASTER_SET_DIFFERS_FROM_CORE_TABLE')
    reconciliation = reconcile_categories(table)
    results, windows = wrap_policy_results(D, patients_core, events, milestones)
    robotic_flag_true = set(patients_core.loc[D.eda.truth(patients_core[FLAG_COLUMN]), ID])
    mapped = {pid for pid, (d, _c, _r) in reconciliation['per_identity'].items() if d == 'mapped'}
    for policy in results:
        require(results[policy]['robotic'] == robotic_flag_true, 'DERIVATION_ROBOTIC_SET_MISMATCH')
    master_ids = set(table[ID])
    prior = reconcile_prior_populations(HERE, master_ids)
    external = reconcile_external_identity_index(args.identity_index, master_ids)
    units = load_review_units(args.review_units, master_ids)
    context_hashes = {'dictionary': sha256_file(HERE / REL['dictionary']), 'decision': sha256_file(HERE / REL['decision']),
                      'selection_script': sha256_file(HERE / REL['selection_script']),
                      'lineage_script': sha256_file(SCRIPT_PATH),
                      'governing_amendment': amendment_sha,
                      'release_patient_wide': sha256_file(root / 'tables/patient_wide.csv'),
                      'release_continence_events_long': sha256_file(root / 'tables/continence_events_long.csv'),
                      'release_continence_milestones_long': sha256_file(root / 'tables/continence_milestones_long.csv'),
                      'review_units': sha256_file(args.review_units)}
    assembled = assemble(table, reconciliation, results, decision, context_hashes, prior, args.data_snapshot_id,
                         args.pipeline_snapshot_id, units, windows)
    after = D.bound_inputs()
    require(before == after == 122, 'BOUND_INPUT_VERIFICATION_FAILURE')
    receipt = assembled['receipt']
    receipt['mode'] = 'build' if args.build else 'check'
    receipt['generated_at_utc_compact'] = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    receipt['source_verification'] = {'bound_inputs_before': before, 'bound_inputs_after': after, 'source_writes_performed': False}
    receipt['category_mapping_approval'] = approval
    receipt['category_mapping_expected_facts'] = expected_facts
    receipt['governing_amendment'] = {'path': args.governing_amendment.name, 'sha256': amendment_sha}
    receipt['external_prior_population_identity_index'] = external
    receipt['robotic_flag_set_equals_mapped_set'] = mapped == robotic_flag_true
    receipt['mapped_minus_flag'] = len(mapped - robotic_flag_true)
    receipt['flag_minus_mapped'] = len(robotic_flag_true - mapped)
    expected = {'P0': (460, 226, 86), 'P1': (457, 221, 82), 'P2': (460, 226, 82), 'P3': (277, 89, 35),
                'P4': (445, 221, 86), 'P5': (599, 282, 119)}
    receipt['expected_policy_counts_reproduced'] = {
        p: [receipt['policy_counts'][p]['early_users'], receipt['policy_counts'][p]['early_users_with_year'],
            receipt['policy_counts'][p]['year_padfree_in_early_user_pairs']] == list(v) for p, v in expected.items()}
    sources = {REL['dictionary']: HERE / REL['dictionary'], REL['decision']: HERE / REL['decision'],
               REL['selection_script']: HERE / REL['selection_script'], REL['lineage_script']: SCRIPT_PATH}
    prior_copies = [(a['path'], HERE / a['path']) for a in prior['artifacts']]
    errors = official_validation(assembled['artifacts'], sources, prior_copies, args.data_snapshot_id,
                                 args.pipeline_snapshot_id, cli, contract)
    receipt['official_validator'] = {'function': 'validate_analysis_input_lineage', 'cli_sha256': sha256_file(args.cli),
                                     'contract_sha256': sha256_file(args.contract), 'error_count': len(errors),
                                     'errors': sanitize_errors(errors, assembled['identities'])}
    blockers = []
    if receipt['identity_accounting']['dispositions'].get('unresolved', 0):
        blockers.append('UNRESOLVED_IDENTITY_DISPOSITIONS')
    if not approval['valid']:
        blockers.append('CATEGORY_MAPPING_NOT_AUTHORIZED')
    if errors:
        blockers.append('OFFICIAL_VALIDATOR_ERRORS')
    if not all(receipt['expected_policy_counts_reproduced'].values()):
        blockers.append('POLICY_COUNTS_NOT_REPRODUCED')
    receipt['build_blockers'] = blockers
    receipt_text = canonical_json(receipt)
    assert_safe_aggregate(receipt_text, assembled['identities'])
    report_dir = args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = 'build' if args.build else 'check'
    receipt_path = report_dir / f'lineage-receipt-{stamp}.json'
    receipt_path.write_text(receipt_text)
    written = {}
    if args.build:
        require(not blockers, 'BUILD_BLOCKED_' + '_'.join(blockers)[:40] if blockers else 'BUILD_BLOCKED')
        written = write_artifacts(HERE, assembled['artifacts'], receipt_text.encode('utf-8'), overwrite=args.overwrite)
    return {'mode': stamp, 'receipt': str(receipt_path), 'receipt_sha256': sha256_bytes(receipt_text.encode('utf-8')),
            'build_blockers': blockers, 'validator_error_count': len(errors),
            'input_record_count': receipt['identity_accounting']['input_record_count'],
            'output_record_count': receipt['identity_accounting']['output_record_count'],
            'dropped_record_count': receipt['identity_accounting']['dropped_record_count'],
            'dispositions': receipt['identity_accounting']['dispositions'],
            'expected_policy_counts_reproduced': receipt['expected_policy_counts_reproduced'],
            'review_units_total': receipt['review_unit_overlap']['units_total'],
            'category_mapping_authorization': {'basis': approval.get('authorization_basis', 'none'),
                                               'reason': approval['reason']},
            'written': written}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='aggregate-only dry run (default)')
    mode.add_argument('--build', action='store_true', help='write canonical restricted artifacts (manager only)')
    parser.add_argument('--overwrite', action='store_true', help='allow replacing existing nonidentical outputs on --build')
    parser.add_argument('--decision', type=Path, default=HERE / REL['decision'])
    parser.add_argument('--category-mapping-approval', type=Path, default=None)
    parser.add_argument('--governing-amendment', type=Path, default=HERE / AMENDMENT_RELATIVE)
    parser.add_argument('--review-units', type=Path, default=REVIEW_UNITS_DEFAULT)
    parser.add_argument('--identity-index', type=Path, default=IDENTITY_INDEX_DEFAULT)
    parser.add_argument('--report-dir', type=Path, default=REPORT_DIR_DEFAULT)
    parser.add_argument('--data-snapshot-id', default=DATA_SNAPSHOT_ID_DEFAULT)
    parser.add_argument('--pipeline-snapshot-id', default=PIPELINE_SNAPSHOT_ID_DEFAULT)
    parser.add_argument('--cli', type=Path, default=CLI_PATH)
    parser.add_argument('--contract', type=Path, default=CONTRACT_PATH)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        summary = run(args)
    except LineageError as exc:
        code = str(exc) if STABLE_CODE.match(str(exc)) else GENERIC_FAILURE
        print(json.dumps({'status': 'failed', 'code': code}))
        return 2
    except Exception:  # noqa: BLE001 - source-derived detail is withheld by design
        print(json.dumps({'status': 'failed', 'code': GENERIC_FAILURE}))
        return 2
    print(json.dumps({'status': 'ok', **summary}, sort_keys=True))
    return 0 if not summary['build_blockers'] else 1


if __name__ == '__main__':
    sys.exit(main())
