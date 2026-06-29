#!/usr/bin/env bash
# =============================================================================
# Install local git hooks that auto-resync a product's venv to its keel pin
# whenever a pull/checkout moves requirements.txt.
#
# This is the local-machine half of the keel-freshness automation. Renovate
# (each product's .github/workflows/renovate.yml) keeps the requirements.txt
# pin fresh and rebuilds the deployed image, but it cannot touch a developer's
# .venv. These post-merge / post-checkout hooks close the loop: the moment a
# `git pull` lands a Renovate keel bump, the local venv resyncs to the new pin
# via scripts/sync_venvs.py — so local dev never drifts behind deployed.
#
# Hooks live in each repo's local .git/hooks (NOT committed), so this is a
# per-machine, one-time setup. Re-run it after cloning on a new machine.
#
#   bash keel/scripts/install-dev-hooks.sh          # all suite products
#   bash keel/scripts/install-dev-hooks.sh harbor   # just one
# =============================================================================
set -uo pipefail

SUITE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MARKER="# >>> keel-venv-sync hook >>>"

products=("$@")
if [ "${#products[@]}" -eq 0 ]; then
  while IFS= read -r d; do products+=("$(basename "$d")"); done < <(
    find "$SUITE_ROOT" -maxdepth 1 -mindepth 1 -type d \
      -exec test -e '{}/requirements.txt' -a -e '{}/.git' ';' -print | sort)
fi

write_hook() {
  local repo="$1" name="$2" detect="$3"
  local hooks_dir="$repo/.git/hooks"
  local hook="$hooks_dir/$name"
  [ -d "$hooks_dir" ] || return 0
  if [ -f "$hook" ] && ! grep -q "$MARKER" "$hook"; then
    echo "  ! $(basename "$repo")/$name exists and isn't ours — skipping (merge by hand)"
    return 0
  fi
  cat > "$hook" <<EOF
#!/usr/bin/env bash
$MARKER
# Auto-resync this repo's .venv to the keel pin when requirements.txt moves.
# Installed by keel/scripts/install-dev-hooks.sh — reinstall overwrites this.
root="\$(git rev-parse --show-toplevel)"
sync="\$(dirname "\$root")/keel/scripts/sync_venvs.py"
[ -f "\$sync" ] || exit 0
$detect
echo "[keel-sync] requirements.txt changed — syncing \$(basename "\$root") venv to pin…"
python3 "\$sync" "\$(basename "\$root")" --quiet || true
# <<< keel-venv-sync hook <<<
EOF
  chmod +x "$hook"
  echo "  ✓ $(basename "$repo")/$name"
}

echo "Installing venv-sync hooks under $SUITE_ROOT"
for p in "${products[@]}"; do
  repo="$SUITE_ROOT/$p"
  [ -d "$repo/.git" ] || { echo "  - $p: not a git repo, skipping"; continue; }
  # post-merge: fires on `git pull` (the common case). Compare ORIG_HEAD..HEAD.
  write_hook "$repo" "post-merge" \
'if ! git diff --name-only ORIG_HEAD HEAD 2>/dev/null | grep -Eq "(^|/)requirements\.txt$"; then exit 0; fi'
  # post-checkout: fires on branch switch. $1=old $2=new $3=1 when branch checkout.
  write_hook "$repo" "post-checkout" \
'[ "$3" = "1" ] || exit 0
if ! git diff --name-only "$1" "$2" 2>/dev/null | grep -Eq "(^|/)requirements\.txt$"; then exit 0; fi'
done

echo
echo "Done. A pull/checkout that changes requirements.txt now resyncs that repo's venv."
echo "Manual full sweep any time:  python3 keel/scripts/sync_venvs.py --check"
