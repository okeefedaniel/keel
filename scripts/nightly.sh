#!/usr/bin/env bash
# =============================================================================
# DockLabs Nightly Test Suite
# Runs at 2:00 AM via cron.
#
# Cron entry:
#   0 2 * * * /Users/dok/SynologyDrive/Work/CT/Web/keel/scripts/nightly.sh >> /Users/dok/SynologyDrive/Work/CT/Web/keel/logs/nightly.log 2>&1
#
# What it does:
#   1. Run full test suite with --auto-fix --json --notify-dashboard
#   2. If auto-fix changed files, commit and push
#   3. POST unfixable failures to Keel dashboard API
# =============================================================================

set -uo pipefail

# --- Configuration ---
KEEL_DIR="/Users/dok/SynologyDrive/Work/CT/Web/keel"
BASE_DIR="/Users/dok/SynologyDrive/Work/CT/Web"
LOG_DIR="${KEEL_DIR}/logs"
REPORT_DIR="${KEEL_DIR}/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JSON_FILE="${REPORT_DIR}/nightly_${TIMESTAMP}.json"

KEEL_API_URL="https://keel.docklabs.ai/api/requests/ingest/"

# Load KEEL_API_KEY from .env or .zshrc
if [ -f "${KEEL_DIR}/.env" ]; then
    export $(grep -E '^KEEL_API_KEY=' "${KEEL_DIR}/.env" | xargs)
fi
if [ -z "${KEEL_API_KEY:-}" ] && [ -f "$HOME/.zshrc" ]; then
    eval "$(grep -E '^export KEEL_API_KEY=' "$HOME/.zshrc" 2>/dev/null)" || true
fi
if [ -z "${KEEL_API_KEY:-}" ]; then
    echo "ERROR: KEEL_API_KEY not set. Add it to ~/.zshrc or ${KEEL_DIR}/.env"
    exit 1
fi

# Ensure directories exist
mkdir -p "${LOG_DIR}" "${REPORT_DIR}"

# Python from keel's venv
PYTHON="${KEEL_DIR}/.venv/bin/python"
if [ ! -f "${PYTHON}" ]; then
    echo "ERROR: Keel venv not found at ${KEEL_DIR}/.venv"
    exit 1
fi

echo "============================================"
echo "DockLabs Nightly Tests — $(date)"
echo "============================================"

# --- Phase 1: Run full test suite ---
echo ""
echo "Phase 1: Running test suite with --auto-fix --json --notify-dashboard..."
echo ""

cd "${KEEL_DIR}"
source .venv/bin/activate

set +e
python -m keel.testing --auto-fix --json --notify-dashboard > "${JSON_FILE}" 2>"${LOG_DIR}/nightly_stderr_${TIMESTAMP}.log"
TEST_EXIT=$?
set -e

echo "Test exit code: ${TEST_EXIT}"
echo "JSON report: ${JSON_FILE}"

# --- Phase 2: If auto-fix changed files, commit and push ---
echo ""
echo "Phase 2: Checking for auto-fix changes..."
echo ""

# Product directories to check for changes
declare -a PRODUCT_DIRS=(
    "${BASE_DIR}/beacon"
    "${BASE_DIR}/harbor"
    "${BASE_DIR}/lookout"
    "${BASE_DIR}/keel"
)

for PRODUCT_DIR in "${PRODUCT_DIRS[@]}"; do
    if [ ! -d "${PRODUCT_DIR}/.git" ] && [ ! -d "${PRODUCT_DIR}" ]; then
        continue
    fi

    cd "${PRODUCT_DIR}"

    # Check for uncommitted changes
    if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
        continue
    fi

    # Describe the changes
    CHANGED_FILES=$(git diff --name-only 2>/dev/null)
    PRODUCT_NAME=$(basename "${PRODUCT_DIR}")

    DESCRIPTION=""
    if echo "${CHANGED_FILES}" | grep -q '\.css\|tokens\|style'; then
        DESCRIPTION="${DESCRIPTION}CSS token fixes, "
    fi
    if echo "${CHANGED_FILES}" | grep -q 'version\|setup\|pyproject\|package'; then
        DESCRIPTION="${DESCRIPTION}version updates, "
    fi
    if echo "${CHANGED_FILES}" | grep -q 'a11y\|accessibility\|aria\|alt'; then
        DESCRIPTION="${DESCRIPTION}accessibility fixes, "
    fi
    if echo "${CHANGED_FILES}" | grep -q 'settings\|config\|security'; then
        DESCRIPTION="${DESCRIPTION}security settings, "
    fi
    if [ -z "${DESCRIPTION}" ]; then
        DESCRIPTION="auto-detected issues, "
    fi
    DESCRIPTION="${DESCRIPTION%, }"  # trim trailing comma

    echo "  ${PRODUCT_NAME}: committing auto-fix changes (${DESCRIPTION})"
    git add -A
    git commit -m "Nightly auto-fix: ${DESCRIPTION} in ${PRODUCT_NAME}" 2>/dev/null || true
    git push origin HEAD 2>/dev/null || echo "  WARNING: push failed for ${PRODUCT_NAME}"

    cd "${KEEL_DIR}"
done

# --- Phase 3: POST unfixable failures to Keel dashboard API ---
echo ""
echo "Phase 3: Reporting unfixable failures to dashboard..."
echo ""

if [ ${TEST_EXIT} -ne 0 ] && [ -f "${JSON_FILE}" ]; then
    # Parse failures and POST each one
    python3 -c "
import json, sys, urllib.request, urllib.error, os

with open('${JSON_FILE}') as f:
    data = json.load(f)

failures = data.get('failures', [])
if not failures:
    print('No failures to report.')
    sys.exit(0)

api_url = '${KEEL_API_URL}'
api_key = os.environ['KEEL_API_KEY']
posted = 0
skipped = 0

for f in failures:
    section = f.get('section', '')
    label = f.get('label', 'Unknown test')
    detail = f.get('detail', '')
    product = f.get('product', 'Beacon')
    severity = f.get('severity', 'medium')

    # Skip if auto-fixed
    if f.get('auto_fixed', False):
        skipped += 1
        continue

    is_security = 'security' in section.lower() or severity.upper() in ('CRITICAL', 'HIGH')
    priority = 'high' if is_security else 'medium'

    payload = json.dumps({
        'title': f'Nightly Test Failure: {label}',
        'description': f'**Section:** {section}\n**Product:** {product}\n**Severity:** {severity}\n\n{detail}',
        'category': 'bug',
        'priority': priority,
        'product': product.lower(),
        'submitted_by_name': 'Nightly Test Bot',
        'submitted_by_email': 'info@docklabs.ai',
    }).encode()

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        posted += 1
        print(f'  Posted: {label} ({priority} priority)')
    except urllib.error.HTTPError as e:
        print(f'  FAILED to post {label}: HTTP {e.code} - {e.read().decode()[:200]}', file=sys.stderr)
    except Exception as e:
        print(f'  FAILED to post {label}: {e}', file=sys.stderr)

print(f'\n{posted} failure(s) posted, {skipped} auto-fixed (skipped).')
"
else
    echo "All tests passed — nothing to report."
fi

# --- Cleanup old reports (keep 30 days) ---
find "${REPORT_DIR}" -name "nightly_*" -mtime +30 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "nightly_*" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "Nightly test run complete — $(date)"
echo "============================================"

exit ${TEST_EXIT}
