#!/usr/bin/env bash
# =============================================================================
# DockLabs Security Audit
# Runs at 3:00 AM ET daily via cron. Scans all products for vulnerabilities,
# auto-fixes safe issues, and reports critical findings to the Keel dashboard.
#
# Cron entry (add via: crontab -e):
#   0 3 * * * /Users/dok/SynologyDrive/Work/CT/Web/keel/scripts/security_audit.sh >> /Users/dok/SynologyDrive/Work/CT/Web/keel/logs/security.log 2>&1
#
# What it does:
#   1. Run comprehensive security audit across all products
#   2. Auto-fix safe issues (missing security settings, DEBUG flags)
#   3. Report critical findings to the Keel dashboard (ChangeRequests)
#   4. If auto-fixes were made: commit and push
#   5. Optionally invoke Claude Code for complex fixes
# =============================================================================

set -euo pipefail

# --- Configuration ---
KEEL_DIR="/Users/dok/SynologyDrive/Work/CT/Web/keel"
BASE_DIR="/Users/dok/SynologyDrive/Work/CT/Web"
LOG_DIR="${KEEL_DIR}/logs"
REPORT_DIR="${KEEL_DIR}/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="${REPORT_DIR}/security_${TIMESTAMP}.txt"
JSON_FILE="${REPORT_DIR}/security_${TIMESTAMP}.json"

# Ensure directories exist
mkdir -p "${LOG_DIR}" "${REPORT_DIR}"

# Use keel's own Python (or system python3)
PYTHON="${KEEL_DIR}/venv/bin/python"
if [ ! -f "${PYTHON}" ]; then
    PYTHON=$(which python3)
fi

echo "============================================"
echo "DockLabs Security Audit — $(date)"
echo "============================================"

cd "${KEEL_DIR}"

# --- Phase 1: Run security audit with auto-fix ---
echo ""
echo "Phase 1: Security audit with auto-fix..."
echo ""

set +e
${PYTHON} -m keel.testing \
    --security-only \
    --auto-fix \
    --notify-dashboard \
    --report-file "${REPORT_FILE}" \
    2>"${LOG_DIR}/security_stderr_${TIMESTAMP}.log"
AUDIT_EXIT=$?
set -e

# Also generate JSON report
${PYTHON} -m keel.testing --security-only --json > "${JSON_FILE}" 2>/dev/null || true

echo ""
echo "Report written to: ${REPORT_FILE}"
echo "Audit exit code: ${AUDIT_EXIT}"
echo ""

# --- Phase 2: Commit auto-fixes ---
echo "============================================"
echo "Phase 2: Committing auto-fixes..."
echo "============================================"
echo ""

declare -A PRODUCT_DIRS
PRODUCT_DIRS[lookout]="${BASE_DIR}/lookout"
PRODUCT_DIRS[beacon]="${BASE_DIR}/beacon"
PRODUCT_DIRS[harbor]="${BASE_DIR}/harbor"
PRODUCT_DIRS[keel]="${BASE_DIR}/keel"

for PRODUCT in "${!PRODUCT_DIRS[@]}"; do
    PRODUCT_DIR="${PRODUCT_DIRS[${PRODUCT}]}"
    if [ -d "${PRODUCT_DIR}/.git" ]; then
        cd "${PRODUCT_DIR}"
        # Check for uncommitted changes in settings files
        CHANGES=$(git diff --name-only 2>/dev/null | grep -E 'settings\.py$' || true)
        if [ -n "${CHANGES}" ]; then
            echo "Auto-fixed settings in ${PRODUCT}:"
            echo "${CHANGES}"
            git add ${CHANGES}
            git commit -m "Security audit: auto-fix security settings

Auto-applied by nightly security audit on $(date +%Y-%m-%d).

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>" 2>/dev/null || true
            git push origin main 2>/dev/null || true
            echo "Pushed fixes for ${PRODUCT}"
        fi
        cd "${KEEL_DIR}"
    fi
done

# --- Phase 3: Claude Code for complex fixes ---
if [ ${AUDIT_EXIT} -ne 0 ]; then
    echo ""
    echo "============================================"
    echo "Phase 3: Critical findings detected"
    echo "============================================"
    echo ""

    # Extract critical findings count
    CRITICAL_COUNT=$(${PYTHON} -c "
import json
try:
    data = json.load(open('${JSON_FILE}'))
    critical = [r for r in data.get('results', []) if not r.get('passed', True)]
    print(len(critical))
except:
    print(0)
" 2>/dev/null)

    echo "Critical/failing checks: ${CRITICAL_COUNT}"
    echo "These have been reported to the Keel dashboard for review."
    echo ""

    # Optionally invoke Claude Code for non-trivial fixes
    if command -v claude &>/dev/null && [ "${CRITICAL_COUNT}" -gt 0 ]; then
        echo "Invoking Claude Code for complex security fixes..."

        SECURITY_PROMPT=$(${PYTHON} -c "
import json
data = json.load(open('${JSON_FILE}'))
failures = [r for r in data.get('results', []) if not r.get('passed', True)]
if failures:
    print('The nightly security audit found these issues:')
    print()
    for f in failures:
        print(f'- [{f.get(\"section\", \"\")}] {f.get(\"label\", \"\")}')
        if f.get('detail'):
            print(f'  Detail: {f[\"detail\"]}')
    print()
    print('For each issue:')
    print('1. Read the relevant code to understand the vulnerability')
    print('2. Fix the root cause with minimal changes')
    print('3. Ensure the fix does not break existing functionality')
    print('4. Commit with a descriptive message')
" 2>/dev/null)

        if [ -n "${SECURITY_PROMPT}" ]; then
            for PRODUCT in "${!PRODUCT_DIRS[@]}"; do
                PRODUCT_DIR="${PRODUCT_DIRS[${PRODUCT}]}"
                cd "${PRODUCT_DIR}"
                echo "${SECURITY_PROMPT}" | claude --print --dangerously-skip-permissions \
                    2>>"${LOG_DIR}/claude_security_${PRODUCT}_${TIMESTAMP}.log" || true
                cd "${KEEL_DIR}"
            done
        fi
    fi
else
    echo ""
    echo "All security checks passed."
fi

# --- Cleanup old reports (keep 30 days) ---
find "${REPORT_DIR}" -name "security_*" -mtime +30 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "security_*" -mtime +30 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "claude_security_*" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "Security audit complete — $(date)"
echo "============================================"

exit ${AUDIT_EXIT}
