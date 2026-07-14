**`keel.testing.config`** now points every product at the repo and settings
module it actually has. `admiralty` and `manifest` were registered as
sub-products sharing the `beacon` / `harbor` repos, but both are standalone
repos with their own `admiralty_site.settings` / `manifest_site.settings`;
`beacon` pointed at a `beacon.settings` module that has never existed (the
beacon repo's project package is named `harbor` for historical reasons). The
practical effect was that Admiralty ran *Beacon's* 382-test suite under a
foreign settings module — 191 of the nightly's 295 failures — while Beacon,
Manifest, Harbor, Lookout and Bounty never ran a single test, each dying on a
`ModuleNotFoundError` that the runner recorded as one generic failure.

**`keel.testing.url_discovery`** now flags `500` exactly rather than `>= 500`,
matching `keel.testing.anon_sweep`. Django never emits 503 itself, so a 503 is
always app code deliberately reporting itself unconfigured — the documented
standalone-deploy behaviour of the `/api/v1/` feed endpoints. This was
reporting `500 on /api/v1/helm-feed/` against Yeoman and Purser with
`status=503` in its own detail line.

**`keel.testing.security_audit`** no longer scans `build/`, `.claude/`
worktrees, `staticfiles/` or `site-packages/` — byte copies of files already
scanned at their real path, which reported each finding two or three extra
times under a bogus path. `Sensitive Files` now asks git whether a match is
tracked instead of whether it exists on disk, so a gitignored local `.env` is
no longer reported as committed to the repo (the same check simultaneously
passed `.gitignore covers .env`).
