#!/usr/bin/env python3
"""Sync local product venvs to the keel pin in their requirements.txt.

Renovate keeps each product's ``requirements.txt`` keel pin fresh and rebuilds
the DEPLOYED image, but it never touches a developer's local ``.venv`` — so
after you ``git pull`` a merged keel bump, the pin moves while the installed
keel stays stale. Testing against a stale venv produces false bugs that do not
exist on demo/prod (CSP console-error floods, favicon-manifest 500s, etc. — see
keel/CLAUDE.md "Local dev" notes). This script closes that gap.

For each product whose installed keel != the requirements.txt pin it runs:
    pip install -r requirements.txt   (brings keel — and anything else — to pin)
    manage.py migrate                 (best-effort; skipped if DB unreachable)
    manage.py collectstatic --noinput (best-effort; needed for manifest storage)

It is idempotent and fast: a product already on its pin is a no-op.

Usage:
    python scripts/sync_venvs.py                 # sync all suite products
    python scripts/sync_venvs.py harbor beacon   # only these
    python scripts/sync_venvs.py --check         # report drift, change nothing (exit 1 if any)
    python scripts/sync_venvs.py --force         # reinstall even if in sync
    python scripts/sync_venvs.py --quiet         # only print products that changed
    python scripts/sync_venvs.py --no-django     # skip migrate + collectstatic

Designed to be called three ways: by hand for a full sweep, by the per-repo
``post-merge`` git hook (installed via scripts/install-dev-hooks.sh) so a pull
that lands a keel bump auto-resyncs that one repo, and from a nightly launchd/
cron job as a backstop.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

PIN_RE = re.compile(r"okeefedaniel/keel(?:\.git)?@v(?P<ver>\d+\.\d+\.\d+)")


def suite_root() -> Path:
    # This file lives at <suite>/keel/scripts/sync_venvs.py
    return Path(__file__).resolve().parents[2]


def pinned_version(req: Path) -> str | None:
    try:
        for line in req.read_text().splitlines():
            m = PIN_RE.search(line)
            if m:
                return m.group("ver")
    except OSError:
        return None
    return None


def keel_requirement(req: Path) -> str | None:
    """Return the full keel requirement line (e.g. 'keel @ git+...@v0.56.2')."""
    try:
        for line in req.read_text().splitlines():
            s = line.strip()
            if s and not s.startswith("#") and PIN_RE.search(s):
                return s
    except OSError:
        return None
    return None


def installed_version(venv_py: Path) -> str | None:
    try:
        out = subprocess.run(
            [str(venv_py), "-c", "import keel; print(keel.__version__)"],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def discover(root: Path, names: list[str]) -> list[Path]:
    if names:
        dirs = [root / n for n in names]
    else:
        dirs = sorted(p for p in root.iterdir() if p.is_dir())
    out = []
    for d in dirs:
        venv_py = d / ".venv" / "bin" / "python"
        if (d / "requirements.txt").is_file() and venv_py.is_file() \
                and pinned_version(d / "requirements.txt"):
            out.append(d)
    return out


def run(cmd: list[str], cwd: Path, quiet: bool) -> bool:
    res = subprocess.run(cmd, cwd=cwd,
                         capture_output=quiet, text=True)
    return res.returncode == 0


def sync_one(prod: Path, *, check: bool, force: bool, quiet: bool,
             do_django: bool) -> str:
    """Return one of: 'ok', 'drift', 'synced', 'failed'."""
    venv_py = prod / ".venv" / "bin" / "python"
    pin = pinned_version(prod / "requirements.txt")
    have = installed_version(venv_py)
    in_sync = (have == pin)

    if in_sync and not force:
        if not quiet:
            print(f"  {prod.name:12} ok        keel=={have}")
        return "ok"

    if check:
        print(f"  {prod.name:12} DRIFT     installed={have or 'none'} pin={pin}")
        return "drift"

    print(f"  {prod.name:12} syncing   {have or 'none'} -> {pin} ...")
    pip = [str(venv_py), "-m", "pip", "install", "-q", "-r", "requirements.txt"]
    if not run(pip, prod, quiet):
        print(f"  {prod.name:12} FAILED    pip install")
        return "failed"

    # pip's git URL resolver won't DOWNGRADE an already-installed keel (the pip
    # cache trap — see keel/CLAUDE.md). If the venv sits ahead of a lagging pin
    # (e.g. local 0.56.3 vs pin 0.56.2), the -r install above is a silent no-op.
    # Force keel to the exact pinned tag so the venv faithfully matches deployed.
    if installed_version(venv_py) != pin:
        spec = keel_requirement(prod / "requirements.txt")
        if spec:
            run([str(venv_py), "-m", "pip", "install", "-q",
                 "--force-reinstall", "--no-deps", spec], prod, quiet)

    if do_django:
        # Best-effort: a stopped Postgres or unconfigured .env must not fail the
        # sync — the pin (the thing Renovate moved) is already installed.
        run([str(venv_py), "manage.py", "migrate", "--noinput"], prod, quiet=True)
        run([str(venv_py), "manage.py", "collectstatic", "--noinput"], prod, quiet=True)

    now = installed_version(venv_py)
    print(f"  {prod.name:12} synced    keel=={now}")
    return "synced" if now == pin else "failed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("products", nargs="*", help="product dir names (default: all)")
    ap.add_argument("--check", action="store_true", help="report drift only; exit 1 if any")
    ap.add_argument("--force", action="store_true", help="reinstall even if in sync")
    ap.add_argument("--quiet", action="store_true", help="suppress in-sync + pip output")
    ap.add_argument("--no-django", action="store_true", help="skip migrate + collectstatic")
    args = ap.parse_args()

    root = suite_root()
    prods = discover(root, args.products)
    if not prods:
        print("No syncable products found under", root)
        return 0

    print(f"{'Checking' if args.check else 'Syncing'} {len(prods)} product venv(s) under {root}")
    results = [sync_one(p, check=args.check, force=args.force, quiet=args.quiet,
                        do_django=not args.no_django) for p in prods]

    drift = results.count("drift")
    failed = results.count("failed")
    synced = results.count("synced")
    if args.check:
        if drift:
            print(f"\n{drift} product(s) out of sync. Run: python {Path(__file__).name}")
            return 1
        if not args.quiet:
            print("\nAll product venvs match their keel pin.")
        return 0
    if failed:
        print(f"\n{failed} product(s) failed to sync.")
        return 1
    if synced and not args.quiet:
        print(f"\nSynced {synced} product(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
