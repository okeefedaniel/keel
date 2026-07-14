#!/usr/bin/env bash
# =============================================================================
# Nightly /qa-only — report-only QA sweep of a deployed DockLabs product.
#
# Runs at 03:00 via launchd (ai.docklabs.nightly-qa.plist), an hour behind
# nightly.sh so the two don't contend for the machine.
#
# Usage:
#   scripts/nightly-qa.sh [product] [url]
#   scripts/nightly-qa.sh beacon https://beacon.docklabs.ai
#
# Why /qa-only and not /qa: /qa fixes bugs and commits them. This runs
# unattended at 3am, and the exploratory findings it produces are exactly
# the ones that need judgement before a code change. It reports; you decide.
#
# This complements nightly.sh rather than duplicating it. nightly.sh runs
# deterministic checks (unit tests, URL sweeps, audits) and knows what it is
# looking for. This drives a real browser and finds things no assertion was
# written for. Neither subsumes the other.
# =============================================================================

set -uo pipefail

PRODUCT="${1:-beacon}"
URL="${2:-https://${PRODUCT}.docklabs.ai}"

KEEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_DIR="${DOCKLABS_BASE_DIR:-$(dirname "${KEEL_DIR}")}"
REPO_DIR="${BASE_DIR}/${PRODUCT}"
LOG_DIR="${KEEL_DIR}/logs"
REPORT_DIR="${KEEL_DIR}/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="${REPORT_DIR}/qa_${PRODUCT}_${TIMESTAMP}.md"

if [ ! -d "${REPO_DIR}" ]; then
    echo "ERROR: no repo at ${REPO_DIR}"
    exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "ERROR: claude CLI not on PATH (launchd agents get a minimal PATH — check the plist)"
    exit 1
fi

mkdir -p "${LOG_DIR}" "${REPORT_DIR}"

echo "============================================"
echo "Nightly QA — ${PRODUCT} — $(date)"
echo "Target: ${URL}"
echo "Report: ${REPORT_FILE}"
echo "============================================"

# Tell gstack nobody is watching, so its skills don't stop to ask questions
# that no one will answer.
export GSTACK_HEADLESS=1

cd "${REPO_DIR}" || exit 1

# --allowedTools rather than --dangerously-skip-permissions: this runs
# unattended against production, and /qa-only has no business editing files
# or pushing anything. Omitting Edit/Write is the enforcement.
set +e
timeout 3600 claude -p "/qa-only ${URL}" \
    --allowed-tools "Bash,Read,Glob,Grep,WebSearch,WebFetch" \
    --disallowed-tools "Edit,Write,NotebookEdit" \
    > "${REPORT_FILE}" 2>"${LOG_DIR}/qa_${PRODUCT}_stderr_${TIMESTAMP}.log"
QA_EXIT=$?
set -e

echo "claude exit code: ${QA_EXIT}"
echo "report bytes: $(wc -c < "${REPORT_FILE}" | tr -d ' ')"

# A 0-byte report is the signature of a job that never really ran — which is
# how nightly.sh sat broken for months. Fail loudly instead of exiting 0 on
# an empty file.
if [ ! -s "${REPORT_FILE}" ]; then
    echo "ERROR: empty QA report — the run produced nothing. stderr:"
    tail -20 "${LOG_DIR}/qa_${PRODUCT}_stderr_${TIMESTAMP}.log"
    exit 1
fi

if [ ${QA_EXIT} -eq 124 ]; then
    echo "WARNING: QA run hit the 60m timeout; report may be partial."
fi

echo ""
echo "--- report head ---"
head -40 "${REPORT_FILE}"
echo "--- end ---"

# Keep 30 days.
find "${REPORT_DIR}" -name "qa_*" -mtime +30 -delete 2>/dev/null || true
find "${LOG_DIR}" -name "qa_*" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "Nightly QA complete — $(date)"
exit ${QA_EXIT}
