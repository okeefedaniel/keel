#!/usr/bin/env bash
# =============================================================================
# DockLabs UI Consistency Audit
# Scans all products for visual inconsistencies and generates a report.
# Optionally invokes Claude Code to auto-fix issues.
#
# Usage:
#   ./scripts/ui_audit.sh                  # Run audit, show report
#   ./scripts/ui_audit.sh --fix            # Run audit + Claude auto-fix
#   ./scripts/ui_audit.sh --json           # JSON output
#   ./scripts/ui_audit.sh --products Beacon Harbor  # Specific products
#
# Cron entry (weekly, Sundays at 3 AM):
#   0 3 * * 0 /Users/dok/SynologyDrive/Work/CT/Web/keel/scripts/ui_audit.sh --fix >> /Users/dok/SynologyDrive/Work/CT/Web/keel/logs/ui_audit.log 2>&1
# =============================================================================

set -euo pipefail

KEEL_DIR="/Users/dok/SynologyDrive/Work/CT/Web/keel"
BASE_DIR="/Users/dok/SynologyDrive/Work/CT/Web"
LOG_DIR="${KEEL_DIR}/logs"
REPORT_DIR="${KEEL_DIR}/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="${REPORT_DIR}/ui_audit_${TIMESTAMP}.txt"
JSON_FILE="${REPORT_DIR}/ui_audit_${TIMESTAMP}.json"

mkdir -p "${LOG_DIR}" "${REPORT_DIR}"

# Find Python
PYTHON="${KEEL_DIR}/.venv/bin/python"
if [ ! -f "${PYTHON}" ]; then
    PYTHON="${KEEL_DIR}/venv/bin/python"
fi
if [ ! -f "${PYTHON}" ]; then
    PYTHON=$(which python3)
fi

# Parse args
FIX_MODE=false
EXTRA_ARGS=""
for arg in "$@"; do
    case "$arg" in
        --fix)  FIX_MODE=true ;;
        *)      EXTRA_ARGS="${EXTRA_ARGS} ${arg}" ;;
    esac
done

echo "============================================"
echo "DockLabs UI Consistency Audit — $(date)"
echo "============================================"
echo ""

cd "${KEEL_DIR}"

# Run the audit
set +e
${PYTHON} -m keel.testing --ui-only ${EXTRA_ARGS} \
    --report-file "${REPORT_FILE}" \
    --fix-prompt \
    2>"${LOG_DIR}/ui_audit_stderr_${TIMESTAMP}.log"
AUDIT_EXIT=$?
set -e

# Also generate JSON
${PYTHON} -m keel.testing --ui-only --json > "${JSON_FILE}" 2>/dev/null || true

echo ""
echo "Report: ${REPORT_FILE}"
echo "Exit code: ${AUDIT_EXIT}"

# --- Auto-fix with Claude Code ---
if [ "${FIX_MODE}" = true ] && [ ${AUDIT_EXIT} -ne 0 ]; then
    PROMPT_FILE="${REPORT_FILE%.txt}.prompt"

    if [ ! -f "${PROMPT_FILE}" ]; then
        echo "No fix prompt generated, skipping auto-fix."
        exit ${AUDIT_EXIT}
    fi

    if ! command -v claude &>/dev/null; then
        echo "WARNING: claude CLI not found. Skipping auto-fix."
        exit ${AUDIT_EXIT}
    fi

    echo ""
    echo "============================================"
    echo "Auto-fixing UI inconsistencies with Claude..."
    echo "============================================"
    echo ""

    PROMPT=$(cat "${PROMPT_FILE}")

    # Map products to directories
    declare -A PRODUCT_DIRS
    PRODUCT_DIRS[Beacon]="${BASE_DIR}/beacon"
    PRODUCT_DIRS[Harbor]="${BASE_DIR}/harbor"
    PRODUCT_DIRS[Lookout]="${BASE_DIR}/lookout"
    PRODUCT_DIRS[Keel]="${BASE_DIR}/keel"

    # Determine which products need fixing from JSON report
    FAILED_AREAS=$(${PYTHON} -c "
import json
try:
    data = json.load(open('${JSON_FILE}'))
    products = set()
    for f in data.get('failures', []):
        label = f.get('label', '')
        for p in ['Beacon', 'Harbor', 'Lookout', 'Keel']:
            if p in label:
                products.add(p)
    # If cross-product issues, fix in keel (shared CSS/JS)
    if not products:
        products.add('Keel')
    print(' '.join(products))
except:
    print('Keel')
" 2>/dev/null)

    echo "Products to fix: ${FAILED_AREAS}"

    for PRODUCT in ${FAILED_AREAS}; do
        PRODUCT_DIR="${PRODUCT_DIRS[${PRODUCT}]:-}"
        if [ -z "${PRODUCT_DIR}" ] || [ ! -d "${PRODUCT_DIR}" ]; then
            echo "Unknown product directory: ${PRODUCT}, skipping"
            continue
        fi

        echo ""
        echo "--- Fixing UI issues in ${PRODUCT} (${PRODUCT_DIR}) ---"

        FIX_PROMPT="The DockLabs UI consistency audit found issues in ${PRODUCT}.

${PROMPT}

Fix the UI inconsistencies listed above. Focus on:
1. Aligning CDN versions to the canonical versions in keel's docklabs.css
2. Replacing hard-coded colors with CSS custom properties (var(--ct-blue), etc.)
3. Ensuring all base templates load shared docklabs.css and docklabs.js
4. Using consistent component patterns (Bootstrap 5 cards, tables, badges)
5. Adding missing accessibility features (skip links, ARIA labels, lang attr)
6. Removing any jQuery, console.log, or Bootstrap 4 remnants

After fixing, commit changes with a descriptive message."

        cd "${PRODUCT_DIR}"
        echo "${FIX_PROMPT}" | claude --print --dangerously-skip-permissions \
            2>>"${LOG_DIR}/ui_fix_${PRODUCT}_${TIMESTAMP}.log" || true
        cd "${KEEL_DIR}"

        echo "Fix attempt for ${PRODUCT} complete"
    done

    # Verification run
    echo ""
    echo "============================================"
    echo "Verification run..."
    echo "============================================"

    VERIFY_FILE="${REPORT_DIR}/ui_verify_${TIMESTAMP}.txt"
    set +e
    ${PYTHON} -m keel.testing --ui-only --report-file "${VERIFY_FILE}" 2>/dev/null
    VERIFY_EXIT=$?
    set -e

    echo "Verification: ${VERIFY_FILE}"
    echo "Verification exit code: ${VERIFY_EXIT}"

    if [ ${VERIFY_EXIT} -eq 0 ]; then
        echo ""
        echo "ALL UI ISSUES RESOLVED"
    else
        echo ""
        echo "WARNING: Some UI issues remain. Manual review needed."
    fi
fi

# Cleanup old reports (keep 30 days)
find "${REPORT_DIR}" -name "ui_audit_*" -mtime +30 -delete 2>/dev/null || true
find "${REPORT_DIR}" -name "ui_verify_*" -mtime +30 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "ui_audit_*" -mtime +30 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "ui_fix_*" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "UI audit complete — $(date)"
echo "============================================"

exit ${AUDIT_EXIT}
