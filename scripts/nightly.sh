#!/usr/bin/env bash
# =============================================================================
# DockLabs Nightly Test Suite
# Runs at 2:00 AM ET via cron. Executes all product tests, then invokes
# Claude Code to auto-fix any failures.
#
# Cron entry (add via: crontab -e):
#   0 2 * * * /Users/dok/SynologyDrive/Work/CT/Web/keel/scripts/nightly.sh >> /Users/dok/SynologyDrive/Work/CT/Web/keel/logs/nightly.log 2>&1
#
# What it does:
#   1. Run Django unit tests for all products
#   2. Run smoke tests (every URL, every user type, every product)
#   3. Generate a report
#   4. If failures: invoke Claude Code per product to diagnose and fix
#   5. Re-run tests on fixed products to verify
#   6. Commit and push fixes
# =============================================================================

set -euo pipefail

# --- Configuration ---
KEEL_DIR="/Users/dok/SynologyDrive/Work/CT/Web/keel"
BASE_DIR="/Users/dok/SynologyDrive/Work/CT/Web"
LOG_DIR="${KEEL_DIR}/logs"
REPORT_DIR="${KEEL_DIR}/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="${REPORT_DIR}/nightly_${TIMESTAMP}.txt"
JSON_FILE="${REPORT_DIR}/nightly_${TIMESTAMP}.json"
PROMPT_FILE="${REPORT_DIR}/nightly_${TIMESTAMP}.prompt"

# Ensure directories exist
mkdir -p "${LOG_DIR}" "${REPORT_DIR}"

# Use keel's own Python (or system python3)
PYTHON="${KEEL_DIR}/venv/bin/python"
if [ ! -f "${PYTHON}" ]; then
    PYTHON=$(which python3)
fi

echo "============================================"
echo "DockLabs Nightly Tests — $(date)"
echo "============================================"

# --- Phase 1: Run all tests ---
echo ""
echo "Phase 1: Running test suite..."
echo ""

cd "${KEEL_DIR}"

# Run tests, capture exit code
set +e
${PYTHON} -m keel.testing \
    --report-file "${REPORT_FILE}" \
    --fix-prompt \
    2>"${LOG_DIR}/nightly_stderr_${TIMESTAMP}.log"
TEST_EXIT=$?
set -e

# Also generate JSON report
${PYTHON} -m keel.testing --json > "${JSON_FILE}" 2>/dev/null || true

echo ""
echo "Report written to: ${REPORT_FILE}"
echo "Test exit code: ${TEST_EXIT}"
echo ""

# --- Phase 2: Auto-fix failures with Claude Code ---
if [ ${TEST_EXIT} -ne 0 ] && [ -f "${PROMPT_FILE}" ]; then
    echo "============================================"
    echo "Phase 2: Auto-fixing failures with Claude..."
    echo "============================================"
    echo ""

    # Check if claude CLI is available
    if ! command -v claude &>/dev/null; then
        echo "WARNING: claude CLI not found. Skipping auto-fix."
        echo "Install: npm install -g @anthropic-ai/claude-code"
        cat "${REPORT_FILE}"
        exit ${TEST_EXIT}
    fi

    # Parse which products have failures from the JSON report
    FAILED_PRODUCTS=$(${PYTHON} -c "
import json, sys
try:
    data = json.load(open('${JSON_FILE}'))
    products = set()
    for f in data.get('failures', []):
        products.add(f.get('product', ''))
    print(' '.join(products))
except:
    print('')
" 2>/dev/null)

    echo "Products with failures: ${FAILED_PRODUCTS}"
    echo ""

    # Map product names to repo directories
    declare -A PRODUCT_DIRS
    PRODUCT_DIRS[Lookout]="${BASE_DIR}/lookout"
    PRODUCT_DIRS[Beacon]="${BASE_DIR}/beacon"
    PRODUCT_DIRS[Admiralty]="${BASE_DIR}/beacon"
    PRODUCT_DIRS[Harbor]="${BASE_DIR}/harbor"
    PRODUCT_DIRS[Manifest]="${BASE_DIR}/harbor"

    PROMPT=$(cat "${PROMPT_FILE}")

    for PRODUCT in ${FAILED_PRODUCTS}; do
        PRODUCT_DIR="${PRODUCT_DIRS[${PRODUCT}]:-}"
        if [ -z "${PRODUCT_DIR}" ]; then
            echo "Unknown product: ${PRODUCT}, skipping"
            continue
        fi

        echo "--- Fixing ${PRODUCT} in ${PRODUCT_DIR} ---"

        # Extract just this product's failures for a focused prompt
        PRODUCT_PROMPT=$(${PYTHON} -c "
import json
data = json.load(open('${JSON_FILE}'))
failures = [f for f in data.get('failures', []) if f.get('product') == '${PRODUCT}']
if failures:
    print('The nightly test suite found these failures in ${PRODUCT}:')
    print()
    for f in failures:
        print(f'- [{f[\"section\"]}] {f[\"label\"]}')
        if f.get('detail'):
            print(f'  Detail: {f[\"detail\"]}')
    print()
    print('Investigate each failure, identify the root cause, and fix it.')
    print('After fixing, run: python manage.py test --verbosity=2')
    print('Commit fixes with a descriptive message.')
" 2>/dev/null)

        if [ -z "${PRODUCT_PROMPT}" ]; then
            echo "No failures extracted for ${PRODUCT}, skipping"
            continue
        fi

        # Run Claude Code in the product directory
        # --print for non-interactive, --dangerously-skip-permissions for unattended
        cd "${PRODUCT_DIR}"
        echo "${PRODUCT_PROMPT}" | claude --print --dangerously-skip-permissions \
            2>>"${LOG_DIR}/claude_fix_${PRODUCT}_${TIMESTAMP}.log" || true
        cd "${KEEL_DIR}"

        echo "Claude fix attempt for ${PRODUCT} complete"
        echo ""
    done

    # --- Phase 3: Re-run tests on fixed products ---
    echo "============================================"
    echo "Phase 3: Verification run..."
    echo "============================================"
    echo ""

    VERIFY_FILE="${REPORT_DIR}/verify_${TIMESTAMP}.txt"
    set +e
    ${PYTHON} -m keel.testing \
        --report-file "${VERIFY_FILE}" \
        2>/dev/null
    VERIFY_EXIT=$?
    set -e

    echo ""
    echo "Verification report: ${VERIFY_FILE}"
    echo "Verification exit code: ${VERIFY_EXIT}"

    if [ ${VERIFY_EXIT} -eq 0 ]; then
        echo ""
        echo "ALL FIXES VERIFIED — pushing changes"
        echo ""
        # Push any committed fixes
        for PRODUCT_DIR in $(echo "${PRODUCT_DIRS[@]}" | tr ' ' '\n' | sort -u); do
            if [ -d "${PRODUCT_DIR}/.git" ]; then
                cd "${PRODUCT_DIR}"
                # Check if there are unpushed commits
                UNPUSHED=$(git log origin/main..HEAD --oneline 2>/dev/null | wc -l)
                if [ "${UNPUSHED}" -gt 0 ]; then
                    echo "Pushing ${UNPUSHED} fix commit(s) from ${PRODUCT_DIR}"
                    git push origin main 2>/dev/null || true
                fi
                cd "${KEEL_DIR}"
            fi
        done
    else
        echo ""
        echo "WARNING: Some failures remain after auto-fix."
        echo "Manual intervention required."
        echo ""
    fi
else
    echo "All tests passed — no fixes needed."
fi

# --- Cleanup old reports (keep 30 days) ---
find "${REPORT_DIR}" -name "nightly_*" -mtime +30 -delete 2>/dev/null || true
find "${REPORT_DIR}" -name "verify_*" -mtime +30 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "nightly_*" -mtime +30 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "claude_fix_*" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "Nightly test run complete — $(date)"
echo "============================================"

exit ${TEST_EXIT}
