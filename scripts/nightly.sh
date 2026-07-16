#!/usr/bin/env bash
# =============================================================================
# DockLabs Nightly Test Suite
# Runs at 2:00 AM via launchd (ai.docklabs.nightly-tests.plist).
#
# Install:
#   cp scripts/ai.docklabs.nightly-tests.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/ai.docklabs.nightly-tests.plist
#
# What it does:
#   1. Run full test suite with --auto-fix --json --notify-dashboard
#   2. If auto-fix changed files, commit them to nightly/auto-fix-<date> and
#      open a PR (clean repos only — see Phase 2). Never commits to main:
#      a push to main auto-deploys Railway, and these are unattended regex
#      rewrites of settings.py, not reasoned edits.
#   3. POST unfixable failures to Keel dashboard API
#
# Paths are overridable so this is runnable from a checkout anywhere:
#   DOCKLABS_BASE_DIR=/path/to/repos scripts/nightly.sh
#
# Modes:
#   (default)      auto-fix -> branch + PR, dashboard POST
#   --report-only  no code changes at all; dashboard POST only
#   --dry-run      no writes anywhere, not even the dashboard
# =============================================================================

set -uo pipefail

DRY_RUN=0
REPORT_ONLY=0
for arg in "$@"; do
    case "${arg}" in
        --dry-run)     DRY_RUN=1 ;;
        --report-only) REPORT_ONLY=1 ;;
        *) echo "unknown argument: ${arg}" >&2; exit 2 ;;
    esac
done

# --- Configuration ---
# Derive from this script's own location rather than hardcoding: the
# previous absolute paths pointed at ~/SynologyDrive/Work/CT/Web, which
# stopped existing when the repos moved to ~/Code/CT. Nothing failed
# loudly — the job just could not find a single repo, and there was no
# cron entry invoking it either, so it went years without running.
KEEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_DIR="${DOCKLABS_BASE_DIR:-$(dirname "${KEEL_DIR}")}"
export DOCKLABS_BASE_DIR="${BASE_DIR}"   # keel.testing.config reads this
LOG_DIR="${KEEL_DIR}/logs"
REPORT_DIR="${KEEL_DIR}/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JSON_FILE="${REPORT_DIR}/nightly_${TIMESTAMP}.json"

# `python -m keel.testing` bootstraps keel_site.settings, which hard-fails
# on a chain of production guards (SECRET_KEY, then ALLOWED_HOSTS, ...)
# while DEBUG is off — the harness died before emitting a single result and
# left a 0-byte report. Each guard has an `if DEBUG:` fallback, and this is
# a local test harness, so satisfy them all at the root rather than
# enumerating env vars that grow every time a guard is added. Django's test
# runner forces DEBUG=False for the tests themselves, so this only affects
# the import-time checks. The key signs nothing that outlives the run.
export DEBUG="${DEBUG:-True}"
export SECRET_KEY="${SECRET_KEY:-nightly-test-key-not-for-production}"

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

# Python from keel's venv. Accept either layout — the repo uses venv/,
# this script only ever looked for .venv/ and bailed.
if [ -x "${KEEL_DIR}/venv/bin/python" ]; then
    VENV_DIR="${KEEL_DIR}/venv"
elif [ -x "${KEEL_DIR}/.venv/bin/python" ]; then
    VENV_DIR="${KEEL_DIR}/.venv"
else
    echo "ERROR: no keel venv at ${KEEL_DIR}/venv or ${KEEL_DIR}/.venv"
    exit 1
fi
PYTHON="${VENV_DIR}/bin/python"

echo "============================================"
echo "DockLabs Nightly Tests — $(date)"
echo "============================================"
echo "Keel:  ${KEEL_DIR}"
echo "Repos: ${BASE_DIR}"

# Every repo the auto-fixer may touch. keel.testing maps some products
# onto a shared repo (admiralty->beacon, manifest->harbor), so this is the
# de-duplicated repo list, not the product list.
PRODUCT_DIRS="
${BASE_DIR}/admiralty
${BASE_DIR}/beacon
${BASE_DIR}/bounty
${BASE_DIR}/harbor
${BASE_DIR}/helm
${BASE_DIR}/lookout
${BASE_DIR}/manifest
${BASE_DIR}/purser
${BASE_DIR}/yeoman
${KEEL_DIR}
"

# --- Phase 0: record which repos are clean BEFORE the run ---
# Phase 2 commits with `git add -A`, so it can only safely commit a repo
# whose tree was clean beforehand — otherwise it sweeps up whatever
# uncommitted work happened to be sitting there at 2am and pushes it.
# Bash 3.2 (macOS system bash) has no associative arrays, hence the
# space-delimited string + case-glob membership test.
# `git status --porcelain`, not `git diff`: diff cannot see untracked files,
# so a repo holding only untracked work reads as clean and Phase 2's
# `git add -A` would hoover it into the commit.
CLEAN_BEFORE=""
for PRODUCT_DIR in ${PRODUCT_DIRS}; do
    [ -d "${PRODUCT_DIR}/.git" ] || continue
    if [ -z "$(git -C "${PRODUCT_DIR}" status --porcelain 2>/dev/null)" ]; then
        CLEAN_BEFORE="${CLEAN_BEFORE} ${PRODUCT_DIR}"
    else
        echo "  note: $(basename "${PRODUCT_DIR}") has uncommitted changes — auto-commit disabled for it"
    fi
done

# --- Phase 1: Run full test suite ---
echo ""
echo "Phase 1: Running test suite..."
echo ""

cd "${KEEL_DIR}"
source "${VENV_DIR}/bin/activate"

if [ "${DRY_RUN}" -eq 1 ]; then
    TESTING_ARGS="--json"
    MODE_NOTE="[dry-run] no --auto-fix, no commit, no push, no dashboard POST"
elif [ "${REPORT_ONLY}" -eq 1 ]; then
    # --auto-fix regex-rewrites settings.py (see security_audit._fix_debug_setting)
    # and Phase 2 pushes to main, which auto-deploys Railway. Report-only keeps
    # the dashboard reporting and leaves the code alone.
    TESTING_ARGS="--json --notify-dashboard"
    MODE_NOTE="[report-only] no --auto-fix, no commit, no push; dashboard POST still runs"
else
    TESTING_ARGS="--auto-fix --json --notify-dashboard"
    MODE_NOTE="[auto-fix] will rewrite files, then branch + PR (never main)"
fi
echo "  ${MODE_NOTE}"
echo "  running: python -m keel.testing ${TESTING_ARGS}"

set +e
python -m keel.testing ${TESTING_ARGS} > "${JSON_FILE}" 2>"${LOG_DIR}/nightly_stderr_${TIMESTAMP}.log"
TEST_EXIT=$?
set -e

echo "Test exit code: ${TEST_EXIT}"
echo "JSON report: ${JSON_FILE}"

# --- Phase 2: If auto-fix changed files, commit and push ---
echo ""
echo "Phase 2: Checking for auto-fix changes..."
echo ""

for PRODUCT_DIR in ${PRODUCT_DIRS}; do
    # Was `[ ! -d .git ] && [ ! -d dir ]`, which only skipped when BOTH
    # were missing — a non-repo directory fell through to `cd` + git.
    [ -d "${PRODUCT_DIR}/.git" ] || continue

    cd "${PRODUCT_DIR}"

    # Nothing changed — nothing to commit.
    if [ -z "$(git status --porcelain 2>/dev/null)" ]; then
        continue
    fi

    # Only commit repos that were clean before Phase 1 ran, so everything
    # staged by `git add -A` is attributable to the auto-fixer.
    case " ${CLEAN_BEFORE} " in
        *" ${PRODUCT_DIR} "*) ;;
        *)
            echo "  $(basename "${PRODUCT_DIR}"): SKIP — tree was already dirty before the run;" \
                 "auto-fix changes (if any) left in place for review"
            cd "${KEEL_DIR}"
            continue
            ;;
    esac

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

    ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'main')
    FIX_BRANCH="nightly/auto-fix-$(date +%Y%m%d)"

    if [ "${DRY_RUN}" -eq 1 ] || [ "${REPORT_ONLY}" -eq 1 ]; then
        echo "  [no-write] ${PRODUCT_NAME}: would open ${FIX_BRANCH} (${DESCRIPTION})"
        cd "${KEEL_DIR}"
        continue
    fi

    # Land fixes on a dated branch and open a PR — never on ${ORIGINAL_BRANCH}.
    # Pushing main here would auto-deploy Railway straight to production from
    # an unattended 2am regex rewrite of settings.py. A PR keeps the
    # automation useful while leaving a human in front of prod.
    echo "  ${PRODUCT_NAME}: ${DESCRIPTION} -> ${FIX_BRANCH}"
    git checkout -q -B "${FIX_BRANCH}" || { echo "  WARNING: branch failed for ${PRODUCT_NAME}"; cd "${KEEL_DIR}"; continue; }
    git add -A
    git commit -q -m "Nightly auto-fix: ${DESCRIPTION} in ${PRODUCT_NAME}" \
        -m "Authored unattended by scripts/nightly.sh on $(date +%Y-%m-%d). The tree was clean before the run, so every change here is the auto-fixer's. Review before merging — these are regex rewrites, not reasoned edits." \
        || true

    # Not silenced: a swallowed push error reads exactly like a success in
    # the morning's log.
    if git push -q -u origin "${FIX_BRANCH}"; then
        echo "  ${PRODUCT_NAME}: pushed $(git rev-parse --short HEAD) to ${FIX_BRANCH}"
        # Best-effort. gh may not resolve its keychain auth under launchd;
        # the branch is pushed either way, so a failure here costs a click.
        if command -v gh >/dev/null 2>&1; then
            gh pr create --base "${ORIGINAL_BRANCH}" --head "${FIX_BRANCH}" \
                --title "Nightly auto-fix: ${DESCRIPTION} in ${PRODUCT_NAME}" \
                --body "Automated by \`keel/scripts/nightly.sh\` on $(date +%Y-%m-%d). Regex-based rewrites — review before merging. Full report: \`${JSON_FILE}\`" \
                >/dev/null 2>&1 && echo "  ${PRODUCT_NAME}: PR opened" \
                || echo "  ${PRODUCT_NAME}: branch pushed; open a PR manually (gh pr create failed — may already exist)"
        fi
    else
        echo "  WARNING: push failed for ${PRODUCT_NAME} (commit is local at $(git rev-parse --short HEAD) on ${FIX_BRANCH})"
    fi

    # Put the checkout back where it was, so the morning doesn't start on a
    # nightly branch. The fixes are committed, so the tree is clean.
    git checkout -q "${ORIGINAL_BRANCH}" || echo "  WARNING: ${PRODUCT_NAME} left on ${FIX_BRANCH}"

    cd "${KEEL_DIR}"
done

# --- Phase 3: POST unfixable failures to Keel dashboard API ---
echo ""
echo "Phase 3: Reporting unfixable failures to dashboard..."
echo ""

if [ "${DRY_RUN}" -eq 1 ]; then
    echo "  [dry-run] skipping dashboard POST"
elif [ ${TEST_EXIT} -ne 0 ] && [ -f "${JSON_FILE}" ]; then
    # Parse failures and POST each one.
    #
    # Only the ones we haven't reported before, and never more than
    # NIGHTLY_MAX_POSTS in a run. The first real run of this script posted 100
    # tickets in 74 seconds, and would have posted the same 100 again every
    # night: Phase 3 opened a ticket per unfixable failure with no memory
    # between runs, against a suite that currently reports ~295 failures. A
    # dashboard that grows by 100 duplicates a night is one nobody reads.
    #
    # The ledger keys on (product, section, label) — not the detail string,
    # which carries counts and timings that churn between runs.
    python3 -c "
import hashlib, json, sys, urllib.request, urllib.error, os

with open('${JSON_FILE}') as f:
    data = json.load(f)

failures = data.get('failures', [])
if not failures:
    print('No failures to report.')
    sys.exit(0)

api_url = '${KEEL_API_URL}'
api_key = os.environ['KEEL_API_KEY']
ledger_path = '${KEEL_DIR}/reports/.reported-failures'
max_posts = int(os.environ.get('NIGHTLY_MAX_POSTS', '25'))

def key(f):
    raw = '|'.join([f.get('product', ''), f.get('section', ''), f.get('label', '')])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

try:
    with open(ledger_path) as fh:
        seen = {line.strip() for line in fh if line.strip()}
except FileNotFoundError:
    seen = set()

fresh = [f for f in failures if key(f) not in seen]
already = len(failures) - len(fresh)
if already:
    print(f'  {already} failure(s) already reported in a previous run — not re-posting.')

# Cap loudly. A silent truncation reads as 'that was everything'.
if len(fresh) > max_posts:
    print(f'  {len(fresh)} new failures; capping at {max_posts}. '
          f'{len(fresh) - max_posts} not posted this run — they stay unreported '
          f'and will be offered again next run. Raise NIGHTLY_MAX_POSTS to widen.')
    fresh = fresh[:max_posts]

if not fresh:
    print('  Nothing new to report.')
    sys.exit(0)

failures = fresh
newly_posted = []
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
        # Ledger only on success, so a 502 retries next run instead of being
        # marked reported and lost. The dashboard 502'd on 7 of 107 posts the
        # first time this ran.
        newly_posted.append(key(f))
        print(f'  Posted: {label} ({priority} priority)')
    except urllib.error.HTTPError as e:
        print(f'  FAILED to post {label}: HTTP {e.code} - {e.read().decode()[:200]}', file=sys.stderr)
    except Exception as e:
        print(f'  FAILED to post {label}: {e}', file=sys.stderr)

if newly_posted:
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    with open(ledger_path, 'a') as fh:
        fh.write('\n'.join(newly_posted) + '\n')

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
