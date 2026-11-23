#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: bash scripts/run_cohort_rebase.sh {check-all-operations|record|verify}" >&2
    exit 2
fi

MODE="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
M1_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$M1_DIR/../delegated_tasks/ms1-nau-rebase-20261121/phase1/run_logs"

case "$MODE" in
    check-all-operations)
        FLAGS=(--cohort all_operations --verify)
        ;;
    record)
        FLAGS=(--cohort completed_window --record-gates)
        ;;
    verify)
        FLAGS=(--cohort completed_window --verify)
        ;;
    *)
        echo "Usage: bash scripts/run_cohort_rebase.sh {check-all-operations|record|verify}" >&2
        exit 2
        ;;
esac

mkdir -p "$LOG_DIR"
cd "$M1_DIR"

STEPS=(
    "06_derive_observed_assessments.py"
    "07_observed_status_estimates.py"
    "10_posthoc_twogroup_analyses.py"
    "11_selection_followup_sensitivity.py"
    "15_clinical_adjustment.py"
    "16_strengthening_analyses.py"
)

for script in "${STEPS[@]}"; do
    step="${script%.py}"
    log_file="$LOG_DIR/${MODE}-${step}.log"
    echo "[run_cohort_rebase] running $script ${FLAGS[*]} -> $log_file"
    if ! python -B "scripts/$script" "${FLAGS[@]}" >"$log_file" 2>&1; then
        echo "[run_cohort_rebase] FAILED at $script (see $log_file)" >&2
        cat "$log_file" >&2
        exit 1
    fi
    cat "$log_file"
done

echo "[run_cohort_rebase] ALL_STEPS_PASSED mode=$MODE"
