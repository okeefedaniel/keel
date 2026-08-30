#!/usr/bin/env python3
"""Sync local product venvs to the keel pin in their requirements.txt.

Renovate keeps each product's ``requirements.txt`` keel pin fresh and rebuilds
the DEPLOYED image, but it never touches a developer's local ``.venv`` — so
after you ``git pull`` a merged keel bump, the pin moves while the installed
keel stays stale. Testing against a stale venv produces false bugs that do not
exist on demo/prod (CSP console-error floods, favicon-manifest 500s, etc. — see
keel/CLAUDE.md "Local dev" notes). This script closes that gap.

For each venv whose installed keel != the requirements.txt pin it runs:
    pip install -r requirements.txt   (brings keel — and anything else — to pin)
    manage.py migrate                 (best-effort; skipped if DB unreachable)
    manage.py collectstatic --noinput (best-effort; needed for manifest storage)

It is idempotent and fast: a venv already on its pin is a no-op.

A venv is only "ok" when it is genuinely healthy, not merely version-matched.
--check reports these distinctly, and exits 1 on any of them:

    DRIFT       importable keel != the requirements.txt pin
    EDITABLE    keel resolves OUTSIDE the venv's site-packages (an editable /
                path install pointing at the live source tree). It reports the
                checkout's version however stale the venv is, so it can never
                show drift — drift-invisible by construction, never 'ok'.
    INCOMPLETE  keel is on pin but required distributions were never installed
    MISMATCH    the importable version disagrees with pip's metadata
    BROKEN      keel is not importable at all

Both `venv/` and `.venv/` are checked, per product. They coexist across the
suite and keel.testing runs each product's Django suite in `venv/`, which this
script did not look at at all.

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
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PIN_RE = re.compile(r"okeefedaniel/keel(?:\.git)?@v(?P<ver>\d+\.\d+\.\d+)")

# Both layouts are in the wild and BOTH matter: keel.testing.config.Product
# defaults to `venv/bin/python`, so that is the venv the nightly actually runs
# every product's Django suite in — while this script historically only ever
# looked at `.venv`. It reported "ok" about a venv nothing tests against.
VENV_DIRS = ("venv", ".venv")

# Distribution name out of a requirements.txt line. Handles the three shapes in
# the suite's files: `keel @ git+https://...@v0.57.2`, `Django>=5.2,<6.1`, and
# `django-allauth[mfa,socialaccount]>=65.0,<66.0`.
REQ_NAME_RE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(?:[<>=!~;@]|$)")

# Executed BY the product's venv interpreter, with cwd set to the product dir so
# the import environment matches how the harness runs `manage.py test`. Reports
# what would really be imported, where from, and what pip metadata claims — the
# three can disagree, and each disagreement is its own failure mode.
PROBE = r"""
import json, sys, sysconfig
from importlib.metadata import PackageNotFoundError, version

res = {"purelib": sysconfig.get_paths()["purelib"],
       "platlib": sysconfig.get_paths()["platlib"]}
try:
    import keel
    res["version"] = getattr(keel, "__version__", None)
    res["file"] = getattr(keel, "__file__", None)
except Exception as exc:
    res["import_error"] = "%s: %s" % (type(exc).__name__, exc)
try:
    res["metadata_version"] = version("keel")
except PackageNotFoundError:
    res["metadata_version"] = None
except Exception as exc:
    res["metadata_error"] = str(exc)
missing = []
for name in sys.argv[1:]:
    try:
        version(name)
    except PackageNotFoundError:
        missing.append(name)
    except Exception:
        pass
res["missing"] = missing
print(json.dumps(res))
"""


def suite_root() -> Path:
    # DOCKLABS_BASE_DIR is the suite-wide override (keel.testing.config reads it,
    # nightly.sh exports it) and lets this run from a worktree, where the layout
    # assumption below resolves somewhere unrelated.
    env = os.environ.get("DOCKLABS_BASE_DIR")
    if env:
        return Path(env).expanduser().resolve()
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


def required_dists(req: Path) -> list[str]:
    """Top-level distribution names a requirements.txt asks for (keel excluded).

    Checked via importlib.metadata rather than by importing each module: the
    dist->module name map is not mechanical (drf-spectacular -> drf_spectacular,
    django-allauth -> allauth) and guessing it wrong reports phantom breakage.
    """
    names = []
    try:
        lines = req.read_text().splitlines()
    except OSError:
        return names
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-"):
            continue
        m = REQ_NAME_RE.match(s)
        if m and m.group("name").lower() != "keel":
            names.append(m.group("name"))
    return names


def probe(venv_py: Path, prod: Path) -> dict:
    """Ask the venv's own interpreter what it would really import.

    cwd is the product dir, never this script's cwd. `python -c` prepends the
    cwd to sys.path, so probing from inside the keel checkout resolved `import
    keel` to ./keel/ — the source tree — and reported the CHECKOUT's version for
    every product uniformly. That is what made --check unreliable in exactly the
    situation it exists to catch.
    """
    try:
        out = subprocess.run(
            [str(venv_py), "-c", PROBE, *required_dists(prod / "requirements.txt")],
            capture_output=True, text=True, timeout=120, cwd=str(prod),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"probe_error": str(exc)}
    try:
        return json.loads(out.stdout.strip() or "{}")
    except ValueError:
        return {"probe_error": (out.stderr or out.stdout).strip()[:200] or "no output"}


def classify(info: dict, pin: str | None) -> tuple[str, str]:
    """(status, detail). Only 'ok' counts as healthy."""
    if "probe_error" in info:
        return "BROKEN", f"probe failed: {info['probe_error']}"
    if "import_error" in info:
        return "BROKEN", f"cannot import keel: {info['import_error']}"

    ver, where = info.get("version"), info.get("file") or ""
    roots = [info.get("purelib") or "", info.get("platlib") or ""]
    inside = any(r and where.startswith(r) for r in roots)
    if not inside:
        # An editable/path install resolves to the live source tree, so it
        # reports the checkout's version no matter how stale the venv is. It is
        # drift-invisible by construction — never 'ok', regardless of version.
        return "EDITABLE", f"keel=={ver} imported from {where} (outside venv site-packages)"

    meta = info.get("metadata_version")
    if meta and ver and meta != ver:
        return "MISMATCH", f"imports {ver} but pip metadata says {meta}"
    if ver != pin:
        return "DRIFT", f"installed={ver or 'none'} pin={pin}"

    missing = info.get("missing") or []
    if missing:
        shown = ", ".join(missing[:4]) + (f" (+{len(missing) - 4} more)" if len(missing) > 4 else "")
        return "INCOMPLETE", f"keel=={ver} but {len(missing)} required dist(s) not installed: {shown}"
    return "ok", f"keel=={ver}"


def venv_pythons(prod: Path) -> list[Path]:
    return [prod / n / "bin" / "python" for n in VENV_DIRS
            if (prod / n / "bin" / "python").is_file()]


def discover(root: Path, names: list[str]) -> list[Path]:
    if names:
        dirs = [root / n for n in names]
    else:
        dirs = sorted(p for p in root.iterdir() if p.is_dir())
    out = []
    for d in dirs:
        if (d / "requirements.txt").is_file() and venv_pythons(d) \
                and pinned_version(d / "requirements.txt"):
            out.append(d)
    return out


def run(cmd: list[str], cwd: Path, quiet: bool) -> bool:
    res = subprocess.run(cmd, cwd=cwd,
                         capture_output=quiet, text=True)
    return res.returncode == 0


def sync_one(prod: Path, venv_py: Path, *, check: bool, force: bool, quiet: bool,
             do_django: bool) -> str:
    """Sync/check ONE venv. Return: 'ok', 'drift', 'synced', or 'failed'."""
    label = f"{prod.name}/{venv_py.parent.parent.name}"
    pin = pinned_version(prod / "requirements.txt")
    status, detail = classify(probe(venv_py, prod), pin)

    if status == "ok" and not force:
        if not quiet:
            print(f"  {label:20} ok        {detail}")
        return "ok"

    if check:
        print(f"  {label:20} {status:10} {detail}")
        return "drift"

    print(f"  {label:20} syncing   {detail} -> keel=={pin} ...")

    # An editable keel shadows anything pip installs into site-packages, so it
    # must come out first or the venv keeps importing the live source tree.
    if status == "EDITABLE":
        run([str(venv_py), "-m", "pip", "uninstall", "-y", "-q", "keel"], prod, quiet)

    pip = [str(venv_py), "-m", "pip", "install", "-q", "-r", "requirements.txt"]
    if not run(pip, prod, quiet):
        print(f"  {label:20} FAILED    pip install")
        return "failed"

    # pip's git URL resolver won't DOWNGRADE an already-installed keel (the pip
    # cache trap — see keel/CLAUDE.md). If the venv sits ahead of a lagging pin
    # (e.g. local 0.56.3 vs pin 0.56.2), the -r install above is a silent no-op.
    # Force keel to the exact pinned tag so the venv faithfully matches deployed.
    if classify(probe(venv_py, prod), pin)[0] != "ok":
        spec = keel_requirement(prod / "requirements.txt")
        if spec:
            run([str(venv_py), "-m", "pip", "install", "-q",
                 "--force-reinstall", "--no-deps", spec], prod, quiet)

    if do_django:
        # Best-effort: a stopped Postgres or unconfigured .env must not fail the
        # sync — the pin (the thing Renovate moved) is already installed.
        run([str(venv_py), "manage.py", "migrate", "--noinput"], prod, quiet=True)
        run([str(venv_py), "manage.py", "collectstatic", "--noinput"], prod, quiet=True)

    status, detail = classify(probe(venv_py, prod), pin)
    print(f"  {label:20} {'synced' if status == 'ok' else 'FAILED':9} {detail}")
    return "synced" if status == "ok" else "failed"


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

    targets = [(p, vp) for p in prods for vp in venv_pythons(p)]
    print(f"{'Checking' if args.check else 'Syncing'} {len(targets)} venv(s) "
          f"across {len(prods)} product(s) under {root}")
    results = [sync_one(p, vp, check=args.check, force=args.force, quiet=args.quiet,
                        do_django=not args.no_django) for p, vp in targets]

    drift = results.count("drift")
    failed = results.count("failed")
    synced = results.count("synced")
    if args.check:
        if drift:
            print(f"\n{drift} venv(s) not healthy. Run: python {Path(__file__).name}")
            return 1
        if not args.quiet:
            print("\nAll product venvs match their keel pin and are fully provisioned.")
        return 0
    if failed:
        print(f"\n{failed} product(s) failed to sync.")
        return 1
    if synced and not args.quiet:
        print(f"\nSynced {synced} product(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
