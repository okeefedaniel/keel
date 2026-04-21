# DockLabs Design System v3 — "Civic Institution"

**Owner:** Dan
**Status:** Draft — reviewed by /plan-eng-review, awaiting final approval before execution
**Target ship:** Every customer deployment on v3 (see Deployment Flexibility §0.5)
**Reference:** `/private/tmp/beacon-design-preview.html` (the aesthetic we're porting)
**Supersedes:** `docklabs-v2.css` "Warm Harbor v2" (Poppins, 6-14px radii, CT blue #1a3a6b)

---

## 0. Goal

Replace the current SaaS-leaning aesthetic with a civic-institution aesthetic across all 9 DockLabs products + Helm. Typography-forward, warm-neutral, document-first. Fleet-switcher coherence is non-negotiable — all products must ship on v3 within one rolling window or the suite feels broken.

### Success criteria

1. Every authenticated page in every product reads as "civic institution," not "SaaS startup."
2. Fleet switcher between any two deployed products is visually seamless.
3. No page-load regression > 100ms (Core Web Vitals LCP) vs v2 baseline.
4. No CLS regression (< 0.1) from font swap.
5. No transfer-size regression > 150KB per page.
6. WCAG 2.1 AA on all body text and UI controls — no regressions.
7. Zero product-specific font declarations outside the shared tokens.
8. **Any product deployed standalone on v3 looks correct** (no "missing styles" because peers aren't deployed).

## 0.5 Deployment Flexibility Constraints

Per `keel/CLAUDE.md` "Deployment Flexibility" section: the suite ships as individual products or any combination. v3 design migration respects this:

- **CSS + fonts ship entirely inside the `keel` pip package.** A single-product customer gets the complete design system via `pip install keel` + `collectstatic`. No peer products required.
- **Font files live in `keel/keel/core/static/fonts/`.** They are collected into the product's static files at build time. No external CDN, no cross-product font server.
- **Fleet switcher styling works with N=1.** The v3 sidebar must render correctly when `KEEL_FLEET_PRODUCTS` (filtered by env-var presence) has one entry or nine.
- **Per-customer rollout is possible.** The 20-service Phase D cutover describes the DockLabs-hosted deployment. A customer running their own Railway/Fly/on-prem deployment can pull v3 whenever they bump their keel pin — the design system is self-contained per product.
- **Phase D "tight window" only applies when multiple products share a fleet switcher UX.** Solo deployments can upgrade independently with zero coordination.

---

## 1. Design Decisions (LOCKED before execution)

These come from the Beacon preview + the cross-suite review. Any change to these requires a fresh review.

### 1.1 Typography
| Role | Font | Fallback | Usage |
|---|---|---|---|
| Display | Fraunces (variable opsz, 400-700) | Georgia, serif | H1-H3, page titles, section headers |
| Sans (body/UI) | Instrument Sans (variable, 400-700) | -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif | Body, buttons, form inputs, labels |
| Mono (data) | JetBrains Mono (400-600) | ui-monospace, SFMono-Regular, Menlo, monospace | Codes, NAICS, FOIA §, IDs, tabular figures, breadcrumbs, small caps labels |

**Poppins — LOCKED:** Kept on unauthenticated marketing/landing surfaces (`keel/layouts/public.html` and anything that extends `base_public.html`) to preserve the CT state brand feel on public-facing pages. Removed from authenticated app surfaces (everything under `keel/layouts/app.html` / `base.html`). Load Poppins only when the public layout renders — do NOT ship it on authenticated pages just to "have it available." Separate `@font-face` block scoped to the public layout.

**Scope of "public" (LOCKED):** landing `/`, login/signup/password-reset forms, email-verification confirmations, marketing/about pages, any route served by `base_public.html`. Everything served by `base.html` → `app.html` (dashboard, detail pages, modals, settings) is authenticated and uses v3 fonts.

### 1.2 Color tokens (changes vs v2)
```
--ct-blue          #1a3a6b → #0A2B4E    (darker, more institutional)
--ct-blue-hover    #254d8f → #12395F
--bg-page          #FFFFFF → #FAF7F2    (paper, not white — biggest single-token shift)
--bg-card          #FFFFFF (unchanged — cards stand out against paper)
--accent           NEW: --brass #B8860B  (FOIA/retention-risk/warning accent)
--accent-soft      NEW: #F5EAD0
--border           #E8E5E0 → #E8E3D9    (marginal — kept warm)
--muted            #6B6B6B → #5B5348    (tightened for AA contrast on paper bg — SEE §6.1)
--success          #0D9488 → #2D5F3F    (forest, not teal — institutional)
--error            #E55353 → #8B2E2A    (brick, not alarm red)
--info             #1A3A6B → #2C5F8D    (distinct from primary navy)
```

Deprecated: `--accent-teal`, `--accent-teal-light`, `--accent-yellow`, `--accent-yellow-light`. Migration: any component using `--accent-teal` maps to `--success`; `--accent-yellow` maps to `--brass`.

### 1.3 Geometry
| Token | v2 | v3 |
|---|---|---|
| `--radius-sm` | 6px | 4px (buttons, inputs — kept small for touch affordance) |
| `--radius-md` | 10px | 0 (cards, alerts) |
| `--radius-lg` | 14px | 0 (modals, large containers) |
| `--radius-pill` | N/A | 0 (pills are rectangular in v3) |

No rounded-pill shapes anywhere. Cards are right-angled with thin rules. This is the single loudest visual shift.

### 1.4 Shadows & elevation
Kept from v2 — the current shadows are already restrained. `--shadow-sm/md/lg` stay as-is.

### 1.5 Spacing
Kept from v2. The preview's `--s-1` through `--s7` scale maps 1:1 onto existing Bootstrap utilities; no grid rewrite.

---

## 2. Token Migration — `docklabs-v2.css` Diff

**File to modify:** `keel/keel/core/static/css/docklabs-v2.css` (1514 lines)

**Strategy:** Additive. Keep `--ct-blue`, `--bg-page`, etc. as token *names* (everything in the suite references them). Change only the *values*. Add new tokens (`--font-display`, `--font-sans`, `--font-mono`, `--brass`, `--brass-soft`). Mark deprecated aliases with a comment but keep them resolving for one release so product-specific CSS doesn't break.

### 2.1 Section 1 (Design Tokens) — rewrite values per §1.2/1.3

### 2.2 Section 3 (Body & Typography) — replace
```css
body {
    font-family: var(--font-sans);
    background: var(--bg-page);
    color: var(--text-primary);
    line-height: 1.55;
}
h1, h2, h3, h4, h5, h6 {
    font-family: var(--font-display);
    font-weight: 500;
    letter-spacing: -0.015em;
}
h1 { font-size: 40px; line-height: 1.05; }   /* up from 26px — page titles */
h2 { font-size: 28px; line-height: 1.15; }
h3 { font-size: 18px; font-weight: 600; }
h4 { font-size: 14px; font-family: var(--font-mono); text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-secondary); font-weight: 500; }
code, kbd, samp, pre, .mono, .font-mono { font-family: var(--font-mono); }
.section-label { font-family: var(--font-mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-secondary); }
```

### 2.3 Section 4 (Buttons) — font + radius
- `font-family: var(--font-sans)` (was Poppins)
- `border-radius: var(--radius-sm)` (stays 4px)
- Keep hover/focus behavior

### 2.4 Sections 5-N — Tables, forms, alerts, cards, sidebar, topbar
For each component: swap `radius-md/lg` → `0`, swap Poppins refs → `var(--font-sans)`, swap body/neutral color refs → new tokens. Individual diffs handled at implementation time, but the token-level changes do 90% of the work automatically because components reference tokens.

### 2.5 New section: FOIA/brass treatment
Port the `.foia` and `.callout` patterns from the Beacon preview into `docklabs-v2.css`. These are suite-wide utilities — Admiralty needs them too, and Harbor wants them for retention-risk grants.

### 2.6 Animation audit
The `fadeUp` animation (keel 0.11.10 fix) must be re-audited — confirm no `opacity: 0` regressions. Call out explicitly in the diff PR.

---

## 3. Font Loading Strategy

Three variable fonts = real perf risk. Get this right.

### 3.1 Subset & self-host (RECOMMENDED)
- Subset each font to Latin + Latin-Extended + tabular figures + small caps (JetBrains Mono only).
- Serve as WOFF2 from WhiteNoise via `keel/core/static/fonts/`.
- Drop Google Fonts `<link>`. Removes third-party DNS + connection.
- Estimated weight after subsetting: Fraunces ~45KB, Instrument Sans ~25KB, JetBrains Mono ~30KB. Total ~100KB vs ~280KB unsubsetted.

### 3.2 `@font-face` with `font-display: swap` and constrained weight ranges
```css
@font-face {
  font-family: 'Fraunces';
  src: url('/static/fonts/fraunces-var.woff2') format('woff2-variations');
  font-weight: 400 700;       /* constrained: we only use 400-700, saves ~40% */
  font-display: swap;
}
@font-face {
  font-family: 'Instrument Sans';
  src: url('/static/fonts/instrument-sans-var.woff2') format('woff2-variations');
  font-weight: 400 700;
  font-display: swap;
}
@font-face {
  font-family: 'JetBrains Mono';
  src: url('/static/fonts/jetbrains-mono-var.woff2') format('woff2-variations');
  font-weight: 400 600;
  font-display: swap;
}
```

### 3.3 Preload the two above-the-fold fonts (LOCKED)
In `keel/layouts/app.html` `<head>`:
```html
<link rel="preload" href="{% static 'fonts/fraunces-var.woff2' %}" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{% static 'fonts/instrument-sans-var.woff2' %}" as="font" type="font/woff2" crossorigin>
```
**Decision locked:** preload Fraunces AND Instrument Sans. Rationale: Fraunces paints H1 (LCP candidate) and Instrument Sans paints body + stat cards + nav above the fold. Preloading both eliminates the dominant CLS source from swap-in. JetBrains Mono is secondary content (codes, IDs) and swaps with acceptable visual impact. ~+25KB preload cost vs Fraunces-only, paid once per cold navigation.

### 3.4 Fallback styling with `size-adjust`
System fallbacks `Georgia` (serif), `-apple-system` (sans), and `ui-monospace` (mono) are close-enough metrics that FOUT is tolerable. **Phase A deliverable:** measure first paint with each fallback and lock `size-adjust`, `ascent-override`, `descent-override` values per `@font-face` before Phase B. Do not ship v3 with unlocked fallback metrics — that's the main CLS source after the preload fix.

---

## 4. Component Migration Order

Components live mostly in `keel/keel/core/templates/keel/components/` and are shared. Migrate in this order so each commit lands a self-contained improvement:

1. **Tokens + body + typography** (§2.1-2.2). Immediate global impact.
2. **Buttons + form inputs** (§2.3). Every page has these.
3. **Tables** — the `table-clickable` pattern + thin rules per preview.
4. **Cards** — sharpen radii to 0. Re-test all card-dependent templates.
5. **`stat_card.html` / `stat_cards_row.html`** — critical for Helm. Port mono treatment from Beacon preview.
6. **`sidebar.html`** — `.sb-item` font change, active-state left border (per preview).
7. **`topbar.html`** — breadcrumbs in mono, ⌘K kbd pill in mono.
8. **`empty_state.html`** — warmth + mono body per Beacon preview §3.
9. **`fleet_switcher.html`** — minor. Align typography with new tokens.
10. **`chart.html` / `chart_scripts.html`** — axis fonts → Instrument Sans, tabular → JetBrains Mono. Color palette refresh.
11. **New: `.foia` and `.callout` utilities** (§2.5).
12. **Alerts** — port the left-border treatment from preview.

Each step commits to the `design-v3` branch on `keel`. **Version bump cadence (LOCKED):** bump `keel.__version__` twice total, not per-step.
- End of Phase A: `0.12.0-design-v3-preview` — demo-only pin consumed by Phase B/C product branches.
- Start of Phase D: `0.12.0` — production-ready pin consumed by all product merges to `main`.

Rationale: 12 per-step bumps × 9 products = 108 pin-update PRs, which is chaotic. Two pin bumps per product (preview → prod) is the minimum that still exercises the keel-package distribution surface separately from the final cutover.

---

## 5. Per-Product Migration Checklist

Goal: minimize product-specific overrides. After v3, every product file below should be smaller than today.

### Shared prep (run once, before any product-level work)
- [ ] `keel` `design-v3` branch created
- [ ] `docklabs-v2.css` v3 port merged on that branch
- [ ] `keel.__version__` bumped to `0.12.0-design-v3-preview` + `pyproject.toml`
- [ ] Test demo deployed to `demo-keel.docklabs.ai` on the branch
- [ ] **Fork reconciliation done BEFORE Phase B.** Diff `bounty/static/css/docklabs.css`, `helm/static/css/docklabs.css`, `yeoman/static/css/docklabs.css` against the shared `keel/keel/core/static/css/docklabs.css`. Any diverged copy must be deleted or reconciled now, or it will shadow the shared CSS on those three products. If they're stale, delete. If they have real overrides, fold the overrides into each product's `<product>.css` file and delete the local `docklabs.css` copy.
- [ ] **Configure demo-service branch tracking.** For each product's `<product>-demo` Railway service, verify the deploy branch. If it tracks `main`, temporarily change to `design-v3` for Phase B/C via `railway service update --branch design-v3` (or Railway dashboard). Document the original branch so it can be restored to `main` before Phase D. Without this, pushing `design-v3` to a product repo deploys NOTHING to demo — you'll debug an empty deploy instead of reviewing v3.
- [ ] **Keel's own services.** `keel.docklabs.ai` (prod OIDC IdP) and `demo-keel.docklabs.ai` serve authenticated pages (login, consent). These are services too — count them in Phase D. Total Phase D footprint: **20 services** (9 products × 2 + keel × 2).

### Prod + demo pairing (READ THIS FIRST)
Every product has TWO Railway services: `<product>` (prod, domain `<product>.docklabs.ai`) and `<product>-demo` (demo, domain `demo-<product>.docklabs.ai`). They share one repo and one `requirements.txt`. Implications:

- **A single PR bumps the keel pin for both services.** Auto-deploy on push to `main` triggers both services to redeploy in parallel.
- **Demo is always the staging target.** We deploy demo on a feature branch (`design-v3`) first; prod deploys when the branch merges to `main`. **Demo service must be configured to track `design-v3` before Phase B** (see Shared prep step).
- **Database schema is independent per service pair except bounty.** `bounty` prod and `bounty-demo` share one Postgres (per `reference_deployment.md`). No schema changes in this plan, but keep the note for future migrations.
- **Demo gets `DEMO_MODE=true` + seed users.** Visual regressions show up on both prod and demo since CSS is identical, but interactive flows (auth, OIDC chain, fleet switcher) differ slightly. Test both.
- **Demo is the honest review surface.** Product owners validate v3 on `demo-<product>.docklabs.ai` before prod cutover. Treat demo as the canonical "pre-prod" for every product.
- **The full Phase D cutover window deploys 20 services** (9 prod + 9 demo + keel prod + keel demo). Budget accordingly.

### Per-product steps (repeat for all 9)
For each of: `admiralty`, `beacon`, `bounty`, `harbor`, `helm`, `lookout`, `manifest`, `purser`, `yeoman`:

1. [ ] **On a `design-v3` branch of the product repo**, pin `keel @ git+...@<v3-sha>` in `requirements.txt`.
2. [ ] **Audit product-specific CSS file** (`{product}.css`). Delete every rule that now duplicates v3 tokens. Every survivor must have a one-line comment explaining why it can't live in shared CSS.
3. [ ] **Grep for Poppins string literals** — `grep -r "Poppins" .` — Poppins may remain ONLY in files that extend `base_public.html` or `keel/layouts/public.html`. Every other hit: kill.
4. [ ] **Grep for hardcoded colors** — `grep -rE "#[0-9a-fA-F]{6}"` — replace with tokens.
5. [ ] **Grep for hardcoded radii** — `grep -rE "border-radius:\s*[0-9]+px"` — replace with `var(--radius-sm)` or `0`.
6. [ ] **Product-specific components audit** (see §5.1 below).
7. [ ] **Push `design-v3` branch** — Railway auto-deploys the branch to `<product>-demo` (verify in Railway dashboard that demo is pointing at `design-v3`; some services may be pinned to `main`).
8. [ ] **Screenshot sweep on demo** — mandatory route set, not "10 key routes": `/dashboard/`, one list page, one detail page, one form page, one empty-state page, one error-state page (403 or 500), one modal/dialog, the login page (unauthenticated — verifies Poppins still loads on public layout). 8 routes × before/after = 16 screenshots per product. Use `/design-shotgun` or `/browse`.
9. [ ] **Benchmark on demo** — LCP on `/dashboard/` + one detail page vs v2 baseline. Gates:
   - LCP delta ≤ +100ms
   - CLS < 0.1 (primary risk: font swap-in — validates the preload + size-adjust work)
   - Transfer size delta ≤ +150KB per page
   - Store measurements in `keel/docs/plans/design-v3-benchmarks.md`
10. [ ] **Fleet-switcher smoke test** — log into `demo-helm.docklabs.ai`, click through to this product's `/dashboard/`, confirm visual continuity. Also: let session expire mid-chain, confirm v3 login form renders correctly (catches broken Poppins/public-layout isolation).
11. [ ] **PR opened** with before/after screenshots + benchmark deltas. Demo URL in PR description.
12. [ ] **Before Phase D merge:** restore `<product>-demo` service branch tracking from `design-v3` back to `main`, so merge-to-main triggers both prod and demo deploys.
13. [ ] **On merge to `main`**, prod service auto-deploys. Post-merge smoke on `<product>.docklabs.ai`.

### 5.1 Product-specific notes

- **admiralty** — Best natural fit. Audit `admiralty.css` (126 lines) hard; most of it should go. Add FOIA chip to every request-list row.
- **beacon** — Already proved the aesthetic. `beacon.css` (132 lines) should be pruned heavily — the preview already demonstrated everything lives in shared CSS.
- **bounty** — Federal-opportunities list density is the risk. Test `portal/federal_opportunities.html` early. May need a compact list variant (`--list-compact`) added to shared CSS.
- **harbor** — Grant cards need the brass/amber treatment for retention risk. `harbor.css` (56 lines) stays small.
- **helm** — **The canary.** Do it second, right after Beacon. Stat card port from Beacon preview §03. Every feed-card in `helm.css` (149 lines) must be visually retested because Helm aggregates from all 8.
- **lookout** — Status colors matter. Validate success/warning/error contrast on paper bg at small sizes. `lookout.css` (70 lines).
- **manifest** — Signatures view is document-heavy; the aesthetic sings here. Also shares `signatures/` with Harbor (pending extraction per `keel/CLAUDE.md:359`). If the extraction happens before v3 ships, cut once; if not, apply v3 twice.
- **purser** — Mono tabular figures will look great. `purser.css` is only 16 lines — biggest win per line-of-code change.
- **yeoman** — Lightest product. Consider a `--density-compact` modifier for small invite records if they look overdressed. `yeoman/static/css/docklabs.css` (stale copy? — verify it's not a diverged fork).

### 5.2 Fork check
`bounty/static/css/docklabs.css`, `helm/static/css/docklabs.css`, `yeoman/static/css/docklabs.css` exist as product-local copies of the shared file. **Verify before v3 port:** are these intentional overrides, stale forks, or build artifacts? Any diverged copies must be deleted or reconciled before the v3 port, or they will shadow the shared CSS on those three products.

---

## 6. Accessibility Gates

### 6.1 Contrast audit (LOCKED from computation)
All pairs below tested on `--bg-page: #FAF7F2`:

| Foreground | Background | Ratio | AA body (4.5) | AA small (4.5) | AAA (7.0) |
|---|---|---|---|---|---|
| `--text-primary` (#1A1A1A) | paper | 16.8:1 | ✓ | ✓ | ✓ |
| `--text-secondary` (#5B5348) | paper | 6.14:1 | ✓ | ✓ | ✗ |
| `--muted` (#5B5348) | paper | 6.14:1 | ✓ | ✓ | ✗ |
| `--brass` (#B8860B) | paper | 3.58:1 | ✗ (UI only — 3:1 threshold ✓) | ✗ | ✗ |
| `--brass` (#B8860B) | `--brass-soft` (#F5EAD0) | 2.96:1 | ✗ | ✗ | ✗ |
| `--ct-blue` (#0A2B4E) | paper | 13.1:1 | ✓ | ✓ | ✓ |

**Decisions:**
- `--muted: #5B5348` — **locked.** Passes AA everywhere. (Preview's #6B6458 at 4.87:1 was borderline; tightened.)
- `--brass` on paper at 3.58:1 — **acceptable for UI (icons, borders) only.** Any brass-colored TEXT must be on white `--surface` or use a darker brass for contrast. Add `--brass-text: #7A5A07` (8.24:1 on paper) for text usage.
- `--brass` on `--brass-soft` for FOIA pills — **fails AA**. Either (a) darken pill text to `--brass-text: #7A5A07` (4.74:1 on brass-soft ✓ AA), or (b) keep brass on brass-soft for visual-only cues and always pair with an icon + plain-text label. **Decision: (a).** Pills render text in `--brass-text`, not `--brass`.

### 6.2 Keyboard + screen reader sweep
- [ ] Skip links work on every product
- [ ] Focus-visible styles present on all interactive elements (buttons, links, inputs)
- [ ] Sharp-edged cards don't lose focus rings — verify explicitly
- [ ] Touch targets ≥ 44px on mobile (buttons currently 8px padding × 13px font ≈ 32px — may need bump)

### 6.3 Color-independent cues
FOIA chips and status pills must carry both color AND icon/text — never color alone.

---

## 7. Performance Gates

Run `/benchmark` before and after v3 port on each product's `/dashboard/`. Hard blocks:

- LCP ≥ current + 100ms → BLOCK. Investigate font loading.
- CLS ≥ 0.1 (any shift from font swap) → BLOCK. Use `size-adjust`.
- Transfer size delta > +150KB (full page) → investigate.

Store baselines in `keel/docs/plans/design-v3-benchmarks.md` (to be created during execution).

---

## 8. Rollout Strategy

### Phase A — Foundation (keel only)
- `keel` `design-v3` branch
- `docklabs-v2.css` v3 port (§2)
- Fonts self-hosted + preload (§3)
- Shared components migrated (§4)
- Gate: demo-keel deploys cleanly, contrast audit passes

### Phase B — Canaries (2 products, demo only)
- Beacon (already proven) + Helm (hardest)
- Each ships to `demo-beacon.docklabs.ai` and `demo-helm.docklabs.ai` on the `design-v3` branch
- Production services stay on v2 (main branch, old keel pin)
- Gate: fleet-switcher smoke between the two v3 demos and one v2 demo (e.g. `demo-harbor`). The *visible* seam between v3 and v2 is the evidence that Phase D must be a tight window

### Phase C — Remaining 7, parallel (demo only)
- Admiralty, Bounty, Harbor, Lookout, Manifest, Purser, Yeoman
- One PR per product, each on a `design-v3` branch deploying to that product's demo service
- Per-product checklist (§5) is the definition-of-done
- **At end of Phase C: all 9 demo services on v3, all 9 prod services still on v2**
- Fleet-switcher smoke across all 9 demos end-to-end

### Phase D — Production cutover (20 services, tight merge window)
- Gate: all 9 demos green + visually consistent + benchmarks passing
- **Merge window: 5 minutes of back-to-back merges to `main` across 9 product repos + keel.** Auto-deploys then propagate in parallel over 3-10 min depending on Railway queue.
- **Expected mixed state: up to 10 minutes** between first merge and last deploy healthcheck. Acceptable for internal staff tooling.
- **Rollback trigger: mixed state > 20 minutes** OR any prod service fails healthcheck after auto-deploy. Revert that product's merge (`git revert` on `main` + push).
- **Merge order:**
  1. Keel prod (bump to `0.12.0`, tag, publish). Keel's own services redeploy.
  2. Helm (aggregates from others — the canary in prod).
  3. Beacon (already proven aesthetic).
  4. Remaining 7 (Admiralty, Bounty, Harbor, Lookout, Manifest, Purser, Yeoman) — parallel merge, let Railway queue sort them.
- Fleet switcher on prod smoke-tested end-to-end across all prod domains as each lands.
- Comms post to staff: "You'll see a refresh. Nothing functional changed."

### Phase D — Customer-managed deployments (separate track)
Customer deployments (self-hosted, single or partial suite) upgrade independently. No tight window. Each customer bumps their keel pin to `0.12.0` on their own cadence. The plan's coordination constraints only apply to the DockLabs-hosted `*.docklabs.ai` fleet. This is the payoff for the standalone-deployment principle (§0.5).

### Phase E — Cleanup (week +1)
- Remove deprecated v2 token aliases from `docklabs-v2.css`
- Archive `docklabs.css` (v1) if no product still references it
- Update `keel/CLAUDE.md`: "Google Fonts: Poppins" → v3 fonts list
- Update `CLAUDE.md` UI & Frontend section to document v3 + the authenticated/public font split
- Announce design-v3 as shipped; close the branch

---

## 9. Rollback

If Phase D surfaces a blocker (auth-critical visual bug, perf regression on real user hardware, accessibility complaint), there are two distinct scenarios:

### Scenario A: Product-specific bug (single product's v3 broken, others fine)
- Every product's `main` branch is tagged `pre-v3-cutover` on its last v2 commit BEFORE Phase D begins. Rollback = `git revert` the merge commit on that product's `main`, push, auto-deploy reverts prod to v2.
- Demo service for that product stays on v3 for fix iteration.
- Other 8 products continue on v3 — partial-state period starts.
- Target: full-forward or full-back within 2 hours of any mixed state. Ship a patch + re-merge, or formally declare the product rolled-back and keep fleet switcher working with the one v2 holdout (CSS will render differently but v2 + v3 can coexist for a short window — visually inconsistent but not broken).

### Scenario B: Keel-shared-code bug (affects multiple products)
- Fix-forward via keel patch release. Bump keel to `0.12.1`, fix, publish.
- Re-pin all 9 products to `0.12.1` via a fast PR per repo (~30 min if prepared).
- Faster than reverting 9 products to v2.
- **Keep the last known-good keel SHA handy** before Phase D — you want it at hand for instant re-pin if the patch also fails.

### General rules
- DO NOT attempt partial rollback across prod for more than 2 hours — that's the fleet-switcher mixed state we're avoiding. Either all-forward or all-back.
- Products pin keel by commit SHA, so scenario A (one product) doesn't cascade.
- Customer deployments are untouched by rollback — they haven't upgraded yet.

---

## 10. Risks & Open Questions

### Risks (ranked)
1. **Font perf on slow connections** — three variable fonts. Mitigation: self-host + subset + preload + swap. Measure early.
2. **`--muted` contrast** (see §6.1). The preview uses #6B6458 which is borderline on #FAF7F2 at small sizes. Recommendation: ship v3 with #5B5348 and validate.
3. **Helm stat-card density regression** — serif H1 + mono figures may break information density on the exec dashboard. Validate in Phase B before committing remaining 7 products.
4. **Bootstrap class collisions** — v3 tokens override Bootstrap defaults, but Bootstrap utility classes (`.rounded`, `.shadow-sm`, `.bg-primary`) may need new overrides. Expect 1-2 rounds of fix-forward after Phase B.
5. **Signatures-extraction collision** (keel/CLAUDE.md:359) — if signatures extracts from Harbor/Manifest during v3, merge order matters. Recommendation: finish v3 first, then extract. One big migration at a time.
6. **Product-local `docklabs.css` forks** (§5.2) — unknown whether these are diverged or stale. Must resolve before Phase C.
7. **State brand challenge** — if anyone at CT asks "why aren't you using Poppins," we have the hedge (public/marketing shells still use Poppins). Document the call in `keel/CLAUDE.md`.

### Open questions — RESOLVED
- **Chart color palette** — LOCKED. Derive 6 chart colors from v3 tokens: `--chart-1` = navy (#0A2B4E), `--chart-2` = brass (#B8860B), `--chart-3` = success forest (#2D5F3F), `--chart-4` = info blue (#2C5F8D), `--chart-5` = muted (#5B5348), `--chart-6` = error brick (#8B2E2A). Added to `docklabs-v2.css` token block in Phase A. Chart scripts (`chart.html` / `chart_scripts.html`) reference these CSS vars.
- **Dark mode** — OUT OF SCOPE. v2 never shipped it; v3 doesn't either. Defer indefinitely.
- **Email templates** — OUT OF SCOPE FOR v3. `keel.notifications` HTML email stays on system fallbacks (`font-family: Georgia, serif` for headers, `-apple-system, sans-serif` for body). Web fonts are unreliable in email clients. Revisit as v3.1 if needed.
- **Admin console (Django admin)** — OUT OF SCOPE. Django admin uses its own styling. Theming it is a separate initiative. Low user visibility (dev-only surface).

---

## 11. Work Breakdown

Rough CC-assisted estimates. Human timing in parens.

| Phase | Work | CC estimate | Human estimate |
|---|---|---|---|
| A | keel v3 port (tokens + typography + components + fonts) | 2-3 hrs | 1-2 weeks |
| B | Beacon + Helm migration + validation | 1-2 hrs each | 3-5 days each |
| C | 7 remaining products (parallel, ~45 min each) | 4-5 hrs total | 2-3 weeks |
| D | Production cutover window | 1 hr | 1 hr |
| E | Cleanup + docs | 1 hr | 1 day |

Total: **~10-15 hours of CC-assisted work**, spanning 2-3 real-world weeks with validation, review, and user testing windows.

---

## 11.5 What already exists (reuse, don't rebuild)

- **`docklabs-v2.css` (1514 lines)** is the migration surface. Token names, selector structure, and component hierarchy all stay — only values change. We're not rewriting the system, we're retokening it.
- **Shared components** in `keel/keel/core/templates/keel/components/` (`stat_card.html`, `sidebar.html`, `topbar.html`, `empty_state.html`, `fleet_switcher.html`, `chart.html`, etc.) all stay. They reference tokens; changing tokens reshapes them automatically.
- **Bootstrap 5.3.3** stays. v3 overrides Bootstrap's primary/radius/font but doesn't replace the framework.
- **The beacon preview HTML** (`/private/tmp/beacon-design-preview.html`) is the reference implementation for the aesthetic. Every decision in §1 derives from it.
- **WhiteNoise compressed manifest storage** handles font serving — no new infra needed.
- **`table-clickable` + `data-href` pattern** from `docklabs-v2.js` stays. v3 just restyles the hover state.
- **`keel.notifications` email backend** stays untouched (per §10 decision — email out of scope).

## 11.6 Failure modes (per critical codepath)

| Codepath | Realistic failure | Test coverage? | Error handling? | User-visible? |
|---|---|---|---|---|
| Font preload (`app.html`) | 404 on font URL if `collectstatic` didn't run | No test | Browser falls back to system font (Georgia/system-ui) | Silent — fallback metrics may cause visible CLS |
| `@font-face src:` bad URL | Same as above | No test | Same fallback | Silent |
| Railway demo service tracks wrong branch | Empty deploy, silent failure | Smoke step 7 in §5 | None — you see v2 on demo | Loud (during review) |
| Keel pin bump + collectstatic race | Font files missing in first few requests post-deploy | No test | Fallback font | Visible for ~30s, self-corrects |
| Variable font weight out of range (e.g. code requests `font-weight: 800` but face declares `400 700`) | Browser synthesizes bold | No test | Synthetic bold — visually ugly | Visible — need grep for `font-weight` overflow |
| CSS token deprecation alias removed too early | Product-specific CSS referencing `--accent-teal` breaks | `grep` in per-product audit | None | Silent — untokened color goes to inherit/initial |
| Fleet switcher with N=1 | Customer deployed solo | Manual smoke per §0.5 | Template conditional hides switcher | Correct |
| OIDC redirect chain through v2 keel → v3 product | Login form styled as v2 but product is v3 — visual seam | Phase D Keel-first merge order | None — but Keel ships first so window is <5min | Visible during Phase D merge window only |

**Critical gaps** (no test AND no error handling AND silent):
1. Font 404 → silent fallback with CLS. **Mitigation:** Phase A deliverable locks `size-adjust` so fallback metrics match. Add a post-deploy health check that HEADs each font URL.
2. Untokened color after alias removal. **Mitigation:** Phase E (cleanup) must include a `grep` sweep for deprecated tokens before removing aliases.

Both are acceptable given the mitigations — flagging for visibility, not escalating.

## 12. Definition of Done

- [ ] All 9 products + Helm render on v3 in production
- [ ] Fleet switcher between any two products is visually seamless
- [ ] No open A11y findings at WCAG 2.1 AA
- [ ] No perf regressions > 100ms LCP
- [ ] `docklabs-v2.css` is the single source of truth; product-local CSS files only carry genuinely product-unique rules
- [ ] `keel/CLAUDE.md` updated to document v3 + font split
- [ ] Rollback tags in place on every product repo
- [ ] Design-v3 branch closed on keel

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 4 P1, 4 P2, 3 P3 findings — all applied to plan; 2 critical failure modes flagged with mitigations |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**VERDICT:** ENG CLEARED — plan pressure-tested, all findings applied, standalone-deployment principle codified in `keel/CLAUDE.md`. Ready to begin Phase A prep (fork reconciliation + Railway branch-tracking config) whenever you are. Optional: `/plan-ceo-review` if you want a second angle on the 20-service cutover scope.
