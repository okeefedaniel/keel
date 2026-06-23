# Changelog fragments

Each unreleased change drops **one file here** instead of editing `CHANGELOG.md`
or the version files directly. The release tool collates these into a new
`CHANGELOG.md` section and bumps the version when a maintainer cuts a release.

This exists so parallel keel branches stop colliding on the top of
`CHANGELOG.md` and on "the next version number." See the "Keel releases" section
in `CLAUDE.md` for the full rationale.

## Add a fragment

```bash
python scripts/release.py note fixed "**\`.text-bg-info\`** now forces white text"
python scripts/release.py note added "**Baz mixin** for quux products"
```

Or create the file by hand: `changes.d/<slug>.<category>.md`. The body is
markdown — usually one or more `-` bullets, matching the existing CHANGELOG
style (bold the symbol, then what changed and why).

**Do not** bump `keel/__init__.py` / `pyproject.toml` or edit `CHANGELOG.md`
in a feature commit. The release cut does that.

## Categories (the filename suffix)

`added` · `changed` · `fixed` · `deprecated` · `removed` · `security` · `consumer-note`

They render as `### Added`, `### Fixed`, … in the collated section.

## Cut a release (maintainer)

```bash
python scripts/release.py cut patch --summary "One-line headline."
# 0.54.2 -> 0.54.3: collates fragments, bumps both version files,
# commits "release: keel vX.Y.Z", tags vX.Y.Z, pushes branch + tag.
```

Consumers then pin the new **tag** (`keel @ git+...@vX.Y.Z`). The tag is what
defeats pip's cache trap — see CLAUDE.md.
