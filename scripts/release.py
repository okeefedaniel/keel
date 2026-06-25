#!/usr/bin/env python3
"""Keel release tool: changelog fragments + one-step version bump + tag.

Why this exists
---------------
Keel is consumed by every DockLabs app, pinned by immutable git **tag**
(``keel @ git+https://.../keel.git@vX.Y.Z``). Pip caches a git install by
package name+version, so the *only* thing that reliably defeats the
"pip-cache-trap" (stale wheel reused across deploys) is that consumers pin an
immutable ref and that ref is always a real tagged release.

The old rule — "every commit bumps ``__version__`` + ``pyproject.toml`` in the
same commit" — was a workaround for that trap, but it made every parallel keel
branch fight over the next version number and conflict on the top of
CHANGELOG.md. This tool removes that:

- During development you add a *fragment* under ``changes.d/`` (one file per
  change). Fragments never touch the version files or CHANGELOG.md, so parallel
  branches don't collide.
- At release time a maintainer runs ``release.py cut <part>``, which collates
  the fragments into a new CHANGELOG section, bumps both version files, commits,
  and tags — all in one shot. The tag is what consumers pin.

Usage
-----
    # Add a changelog fragment while working on a change:
    python scripts/release.py note fixed "**.foo** no longer NPEs on bar"
    python scripts/release.py note added "**Baz mixin** for quux products"

    # Cut a release (maintainer; serialized — only one cut at a time):
    python scripts/release.py cut patch            # 0.54.2 -> 0.54.3
    python scripts/release.py cut minor            # 0.54.2 -> 0.55.0
    python scripts/release.py cut patch --dry-run  # preview, write nothing
    python scripts/release.py cut patch --summary "One-line headline."

Stdlib only — no external deps.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "keel" / "__init__.py"
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
CHANGES_DIR = ROOT / "changes.d"

# filename category suffix -> heading, in render order.
CATEGORIES: dict[str, str] = {
    "added": "Added",
    "changed": "Changed",
    "fixed": "Fixed",
    "deprecated": "Deprecated",
    "removed": "Removed",
    "security": "Security",
    "consumer-note": "Consumer note",
}


def _die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _slugify(text: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen].rstrip("-")) or "change"


def _read_version() -> str:
    m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", INIT.read_text())
    if not m:
        _die(f"could not find __version__ in {INIT}")
    return m.group(1)


def _bump(version: str, part: str) -> str:
    try:
        major, minor, patch = (int(x) for x in version.split("."))
    except ValueError:
        _die(f"version {version!r} is not X.Y.Z; use --set-version")
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# --------------------------------------------------------------------------
# note: create a changelog fragment
# --------------------------------------------------------------------------
def cmd_note(args: argparse.Namespace) -> None:
    category = args.category.lower()
    if category not in CATEGORIES:
        _die(f"category {category!r} not in {', '.join(CATEGORIES)}")
    CHANGES_DIR.mkdir(exist_ok=True)
    slug = args.slug or _slugify(args.text)
    base = CHANGES_DIR / f"{slug}.{category}.md"
    path, n = base, 2
    while path.exists():
        path = CHANGES_DIR / f"{slug}-{n}.{category}.md"
        n += 1
    body = args.text.rstrip()
    # Prefix a bullet unless the author already wrote a list item. Require the
    # trailing space so "**bold**" (starts with '*') isn't mistaken for a bullet.
    if not body.lstrip().startswith(("- ", "* ")):
        body = f"- {body}"
    path.write_text(body + "\n")
    print(f"wrote {path.relative_to(ROOT)}")


# --------------------------------------------------------------------------
# cut: collate fragments, bump versions, commit + tag
# --------------------------------------------------------------------------
def _collect_fragments() -> tuple[dict[str, list[str]], list[Path]]:
    grouped: dict[str, list[str]] = {}
    files: list[Path] = []
    for path in sorted(CHANGES_DIR.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        parts = path.name.split(".")
        if len(parts) < 3 or parts[-2] not in CATEGORIES:
            print(f"  skip (no category suffix): {path.name}", file=sys.stderr)
            continue
        category = parts[-2]
        grouped.setdefault(category, []).append(path.read_text().rstrip())
        files.append(path)
    return grouped, files


def _build_section(version: str, date: str, summary: str | None,
                   grouped: dict[str, list[str]]) -> str:
    lines = [f"## {version} — {date}", ""]
    if summary:
        lines += [f"**{summary.strip()}**", ""]
    for key, heading in CATEGORIES.items():
        if key in grouped:
            lines.append(f"### {heading}")
            for chunk in grouped[key]:
                lines.append(chunk)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _insert_section(section: str) -> None:
    text = CHANGELOG.read_text()
    lines = text.splitlines(keepends=True)
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    new = lines[:idx] + [section, "\n"] + lines[idx:]
    CHANGELOG.write_text("".join(new))


def _write_version(new: str) -> None:
    INIT.write_text(re.sub(r"(__version__\s*=\s*')[^']+(')",
                           rf"\g<1>{new}\g<2>", INIT.read_text()))
    PYPROJECT.write_text(re.sub(r'(?m)^(version\s*=\s*")[^"]+(")',
                                rf"\g<1>{new}\g<2>", PYPROJECT.read_text()))


def _git(*args: str, dry: bool) -> None:
    if dry:
        print(f"  would run: git {' '.join(args)}")
        return
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def cmd_cut(args: argparse.Namespace) -> None:
    current = _read_version()
    new = args.set_version or _bump(current, args.part)
    date = args.date or _dt.date.today().isoformat()

    grouped, files = _collect_fragments()
    if not files and not args.allow_empty:
        _die("no changes.d/*.md fragments — nothing to release "
             "(add one with `release.py note <category> \"...\"`, "
             "or pass --allow-empty for a no-change cache-bust release)")

    section = _build_section(new, date, args.summary, grouped)
    print(f"== keel {current} -> {new} ({date}) ==\n")
    print(section)

    if args.dry_run:
        print(f"[dry-run] would update {INIT.name}, {PYPROJECT.name}, CHANGELOG.md")
        print(f"[dry-run] would git rm {len(files)} fragment(s)")
        _git("commit", "-m", f"release: keel v{new}", dry=True)
        if not args.no_tag:
            _git("tag", "-a", f"v{new}", "-m", f"keel v{new}", dry=True)
        return

    _insert_section(section)
    _write_version(new)
    for f in files:
        _git("rm", "--quiet", str(f.relative_to(ROOT)), dry=False)
    _git("add", str(INIT.relative_to(ROOT)), str(PYPROJECT.relative_to(ROOT)),
         "CHANGELOG.md", dry=False)
    _git("commit", "-m", f"release: keel v{new}", dry=False)
    if not args.no_tag:
        _git("tag", "-a", f"v{new}", "-m", f"keel v{new}", dry=False)
    if not args.no_push:
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
        _git("push", "origin", branch, dry=False)
        if not args.no_tag:
            _git("push", "origin", f"v{new}", dry=False)
    print(f"\nreleased keel v{new}"
          + ("" if args.no_tag else f" (tag v{new})")
          + (" — not pushed" if args.no_push else ""))


def main() -> None:
    p = argparse.ArgumentParser(description="Keel release tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("note", help="create a changelog fragment")
    n.add_argument("category", help=f"one of: {', '.join(CATEGORIES)}")
    n.add_argument("text", help="markdown bullet body for the change")
    n.add_argument("--slug", help="override the fragment filename slug")
    n.set_defaults(func=cmd_note)

    c = sub.add_parser("cut", help="collate fragments, bump version, tag")
    c.add_argument("part", nargs="?", default="patch",
                   choices=["major", "minor", "patch"],
                   help="semver part to bump (default: patch)")
    c.add_argument("--set-version", help="explicit X.Y.Z (overrides part)")
    c.add_argument("--summary", help="one-line headline under the version header")
    c.add_argument("--date", help="release date YYYY-MM-DD (default: today)")
    c.add_argument("--allow-empty", action="store_true",
                   help="cut even with no fragments (cache-bust release)")
    c.add_argument("--no-tag", action="store_true")
    c.add_argument("--no-push", action="store_true")
    c.add_argument("--dry-run", action="store_true", help="preview, write nothing")
    c.set_defaults(func=cmd_cut)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
