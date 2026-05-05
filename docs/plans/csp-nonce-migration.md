# CSP Nonce Migration — DockLabs Suite

**Owner:** Dan
**Status:** Draft — planning only, no code yet
**Origin:** Item #4 of the 2026-05-03 CSO security audit (items #1–3 shipped: keel v0.25.0, encryption KEK split, AbstractAttachment file scanner default).
**Target:** Move every product's CSP off `'unsafe-inline'` for `script-src` (and, where feasible, `style-src`) and onto a request-scoped nonce emitted by the keel `SecurityHeadersMiddleware`.
**Out of scope:** Anything that forces a breaking dependency upgrade (Bootstrap major-version bump, Mapbox SDK rewrite). The migration is additive — old products on the old policy keep working until they cut over.

---

## 0. Why this is hard, in one paragraph

The reason the CSO audit deferred this item is not the keel-side plumbing — that's a few hundred lines. It is that **a CSP nonce only covers `<script>` and `<style>` blocks; it does NOT cover inline `style="…"` attributes, inline event handlers (`onclick=`, `onload=`, …), or `href="javascript:"` URLs.** Every one of those across 9 product template trees has to either (a) carry a nonce-eligible wrapper, (b) be rewritten as a CSS class / `addEventListener`, or (c) be allowed via per-hash `'unsafe-hashes'` (CSP Level 3, brittle for runtime values). The inventory in §2 sizes that work realistically; the scope is dominated by inline `style=""` attributes (699 across the suite), and the recommendation in §3 is to **tighten `script-src` to nonce-only and accept `style-src 'unsafe-inline'` as a known residual** until the per-product CSS extraction work catches up. That single decision halves the migration cost without giving up the security win that matters most (XSS execution).

---

## 1. Current state

### 1.1 Middleware

`keel/security/middleware.py` defines `SecurityHeadersMiddleware`. It reads `settings.KEEL_CSP_POLICY` and emits the literal string as the `Content-Security-Policy` header — no template substitution, no nonce, no per-request mutation. It does NOT supply a default; products without `KEEL_CSP_POLICY` set ship with no CSP header at all (silent failure mode).

There is no `Content-Security-Policy-Report-Only` support, no violation reporting endpoint, and no per-request nonce generation anywhere in keel today.

### 1.2 Per-product CSP inventory

| Product   | Allows `unsafe-inline` (script) | Allows `unsafe-inline` (style) | Allows `unsafe-eval` | Notable extras |
|-----------|:---:|:---:|:---:|---|
| Admiralty | yes | yes | no  | baseline |
| Beacon    | yes | yes | no  | adds `unpkg.com` (script + style), `worker-src 'self' blob:`, `img-src blob:` |
| Bounty    | yes | yes | no  | baseline |
| Harbor    | yes | yes | no  | baseline; explicit "Start permissive, tighten later" comment |
| Helm      | yes | yes | no  | adds `data:` to `font-src` (unusual; review separately) |
| Lookout   | yes | yes | no  | adds `unpkg.com` to script-src |
| Manifest  | yes | yes | no  | baseline; explicit "Start permissive, tighten later" comment |
| Purser    | yes | yes | no  | baseline |
| Yeoman    | yes | yes | **yes** | Mapbox: `api.mapbox.com`, `*.tiles.mapbox.com`, `events.mapbox.com`, `worker-src 'self' blob:`, `frame-ancestors 'none'` |

Settings paths: `admiralty_site/settings.py`, `harbor/settings.py` (Beacon — yes, that's the path), `bounty/settings.py`, `harbor/settings.py`, `helm_site/settings.py`, `lookout/settings.py`, `manifest_site/settings.py`, `purser_site/settings.py`, `yeoman_project/settings.py`.

**Common baseline (8 of 9):** `default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; img-src 'self' data: https:; connect-src 'self' https://keel.docklabs.ai https://demo-keel.docklabs.ai`.

**Deviations worth flagging:**
- **Yeoman's `'unsafe-eval'`** is required by Mapbox GL JS (uses `Function()` for shader compilation). It cannot be removed without dropping Mapbox or replacing the engine. Treat as a permanent product-specific exception; document but do not gate the migration on it.
- **Beacon and Lookout's `unpkg.com`** allowance — verify which library ships from unpkg before migration; if it's a single component, move the asset to `static/` and drop the host.
- **Helm's `data:` font-src** — almost certainly unnecessary (no inline data: fonts in the templates). Strip in passing.

### 1.3 Keel itself

`keel/keel_site/settings.py` sets no `KEEL_CSP_POLICY` baseline. The keel package ships templates but is not a deployable site of its own except for Keel-the-IdP, which uses its own `keel_site` settings. Keel's IdP service runs in production and SHOULD set a CSP — its OAuth `/authorize/` page is a high-value target. Add a baseline policy for keel as part of this migration.

---

## 2. Inline-asset audit

Counts measured against each product's `templates/` tree (and shared keel templates). Methodology: ripgrep with `--type=html` against the product root; per-attribute tallies for `style="…"` and `on{event}=` attributes; inline `<script>` is "`<script>` without `src=`". Numbers are approximations meant to size the work, not exact production figures.

| Product   | .html files | Inline `<script>` | Inline `<style>` blocks | `style=""` attrs | Inline event handlers | `javascript:` URLs |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|
| Admiralty | 21  | 1   | 2 | 21  | 2  | 0 |
| Beacon    | 77  | 16  | 6 | 122 | 16 | 0 |
| Bounty    | 20  | 1   | 2 | 65  | 5  | 0 |
| Harbor    | 109 | 10  | 7 | 353 | 16 | 1 |
| Helm      | 34  | 1   | 1 | 77  | 4  | 0 |
| Lookout   | 8   | 1   | 1 | 11  | 0  | 0 |
| Manifest  | 26  | 1   | 2 | 29  | 0  | 0 |
| Purser    | 11  | 0   | 1 | 15  | 0  | 0 |
| Yeoman    | 15  | 0   | 1 | 5   | 0  | 0 |
| Keel (shared) | 2 | 1 | 0 | 1  | 1  | 0 |
| **Total** | **323** | **32** | **23** | **699** | **44** | **1** |

### Top offending files (focus the per-product PRs here first)

| Product   | Worst file 1 | Worst file 2 | Worst file 3 |
|-----------|---|---|---|
| Beacon    | `adoption_report.html` (50 attrs) | `base.html` (16 attrs) | `interaction_form.html` (8 attrs, 2 scripts) |
| Harbor    | `demo_guide.html` (30 attrs) | `signature_requested.html` (27 attrs, 1 `javascript:` URL) | `base.html` (27 attrs, 4 events) |
| Bounty    | `grant_match.html` (23 attrs, email tmpl) | `grant_digest.html` (23 attrs, email tmpl) | `tracked_opportunity_detail.html` (12 attrs, 4 events) |
| Helm      | `_alerts_column.html` (11 attrs) | `_tab_suite.html` (9 attrs) | `_product_drilldown.html` (8 attrs, 1 event) |
| Admiralty | `demo.html` (6 attrs) | `base.html` (5 attrs) | `search_results.html` (1 script, 2 events) |
| Manifest  | `base.html` (6 attrs) | `sign.html` (4 attrs) | `packet_detail.html` (3 attrs, 1 style block) |
| Lookout   | `base.html` (8 attrs) | `help.html` (1 script) | — |
| Purser    | `base_email.html` (4 attrs) | `base.html` (4 attrs) | `submission_due.html` (2 attrs) |
| Yeoman    | `base.html` (5 attrs) | `user_manual.html` (1 style block) | — |
| Keel      | `_export_button.html` (1 script, 1 event) | — | — |

### Reading the audit

- **Inline `<script>` + event handlers (76 sites total)** — this is the *XSS-relevant* surface. These are the ones the nonce migration actually buys security against. They're tractable: 32 nonce-additions to `<script>` tags + 44 `onclick=` rewrites to `addEventListener`. Estimate ≤ 1 engineering week per product *combined* for this layer.
- **Inline `<style>` blocks (23 sites)** — easy: nonce-able exactly like `<script>`. Also tractable.
- **Inline `style=""` attributes (699 sites)** — this is the long pole and the reason `style-src 'unsafe-inline'` cannot be dropped without a multi-week CSS extraction effort. Harbor (353) and Beacon (122) dominate. The bounty/email-template count (46) is locked in by email-client compatibility — email clients ignore external stylesheets, so those `style=""` attributes are non-negotiable in their *email* form, but the product-rendered HTML preview view is a separate template that can be class-based.

### Bootstrap / Popper inline-style problem

Bootstrap 5.3.3 components that depend on **Popper.js** (tooltips, popovers, dropdowns) write inline `style="position: absolute; top: …; left: …;"` attributes onto the floating element at runtime. **Nonces do not apply to inline style attributes**, only to `<style>` blocks. This means even if the *templates* were 100% free of `style=""`, runtime Popper positioning would still violate `style-src 'self'` and break every dropdown in the suite.

Options, ranked by realism:
1. **Keep `style-src 'unsafe-inline'`** as a known-acceptable residual. Get the script-src win now; revisit style-src tightening as a follow-up that requires either (a) Popper providing a nonce-able alternative (it does not, today), (b) CSP3 `'unsafe-hashes'` with a curated allowlist (browser support is narrow and the position values are dynamic), or (c) replacing Popper with a CSS-only positioning strategy (large refactor, downgrades UX). **Recommended.**
2. **Use `'unsafe-hashes'` + per-style hashes** — does not work for runtime-computed values like `top: 423.5px`. Skip.
3. **Replace Popper with CSS-only positioning** — viable only for some components; modal/offcanvas don't need Popper, but tooltip/dropdown do. Out of scope for this migration.

The §3 design therefore tightens `script-src` (the high-value win) and explicitly leaves `style-src 'unsafe-inline'` in place. The plan still nonces inline `<style>` blocks as a hygiene win, so future tightening is one keel release away when the inline-attribute count is low enough to switch.

---

## 3. Proposed implementation

### 3.1 Per-request nonce generation

New middleware `keel.security.middleware.CSPNonceMiddleware`, ordered immediately before `SecurityHeadersMiddleware`. On every request:

```python
import secrets
request.csp_nonce = secrets.token_urlsafe(16)  # 128 bits, base64url
```

`SecurityHeadersMiddleware` is amended to interpolate `{nonce}` placeholders inside `KEEL_CSP_POLICY` if present:

```python
csp = getattr(settings, 'KEEL_CSP_POLICY', None)
if csp:
    nonce = getattr(request, 'csp_nonce', None)
    if nonce and '{nonce}' in csp:
        csp = csp.replace('{nonce}', f"'nonce-{nonce}'")
    response['Content-Security-Policy'] = csp
```

`KEEL_CSP_POLICY` becomes a *template string* — products opt into nonces by writing `script-src 'self' '{nonce}' https://cdn.jsdelivr.net` instead of `'unsafe-inline'`. Products that haven't migrated yet ship a literal string with no `{nonce}` token and behave identically to today. Backwards-compatible by construction.

### 3.2 Context processor

`keel.core.context_processors.csp_nonce` exposes the nonce to templates:

```python
def csp_nonce(request):
    return {'csp_nonce': getattr(request, 'csp_nonce', '')}
```

Wire into every product's `TEMPLATES['OPTIONS']['context_processors']` next to `site_context`.

### 3.3 Template pattern

Every inline asset becomes:

```django
<script nonce="{{ csp_nonce }}">…</script>
<style  nonce="{{ csp_nonce }}">…</style>
```

There is no template-side change for `<script src="…">` (the nonce is not required for external scripts as long as the host is in the allowlist — but adding `nonce` is fine and lets us eventually drop the host allowlist).

For inline event handlers, the per-template rewrite is `onclick="doX()"` → `<button id="x-btn">…</button>` plus a small inline `<script nonce="{{ csp_nonce }}">document.getElementById('x-btn').addEventListener('click', doX)</script>` — or, where the handler already lives in `docklabs-v2.js`, a `data-action="x"` attribute matched by a delegated listener in the shared bundle.

### 3.4 Report-only bridging

`SecurityHeadersMiddleware` learns a parallel `KEEL_CSP_POLICY_REPORT_ONLY` setting. When set, the middleware emits **both** headers:

```
Content-Security-Policy: <enforced policy — old, with unsafe-inline>
Content-Security-Policy-Report-Only: <new policy — nonce-based, no unsafe-inline>
```

Browsers report violations of the report-only header to a `report-uri` endpoint without blocking page rendering. This lets us soak the new policy in production for a week per product before flipping it to enforce.

A new keel app `keel.security.csp_report` provides:
- `POST /security/csp-report/` — accepts the browser's JSON `csp-report` payload, writes a `CSPViolationReport` row (`document_uri`, `violated_directive`, `blocked_uri`, `source_file`, `line_number`, `column_number`, `script_sample`, `created_at`).
- Admin view + a simple aggregation page at `/security/csp-violations/` showing top violations by directive + file in the last N days. Staff-only.
- Throttled per-IP (browsers can spam reports under attack). 100/min/IP via existing rate-limit cache.

The report endpoint is mounted unconditionally — products opting into report-only just need to add `report-uri /security/csp-report/` to their `KEEL_CSP_POLICY_REPORT_ONLY`.

### 3.5 What the policy strings look like at the end

**Migrated baseline** (every product except Yeoman):

```
default-src 'self';
script-src  'self' '{nonce}' https://cdn.jsdelivr.net;
style-src   'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com;
font-src    'self' https://fonts.gstatic.com https://cdn.jsdelivr.net;
img-src     'self' data: https:;
connect-src 'self' https://keel.docklabs.ai https://demo-keel.docklabs.ai;
report-uri  /security/csp-report/
```

**Yeoman** keeps `'unsafe-eval'` and Mapbox hosts; everything else identical. Document in the product `settings.py` as a Mapbox-required exception.

The `'unsafe-inline'` removed from `script-src` is the entire security win. Style stays as-is. Document this decision in the keel `CLAUDE.md` "Security" section so reviewers don't re-flag it.

---

## 4. Rollout order

### 4.1 Sequencing principle

Smallest template tree first → trial pattern → fan out. Products with heavy inline content go last so the cleanup playbook is mature by the time we hit the dense ones. Yeoman defers because its Mapbox `'unsafe-eval'` requirement adds an unrelated variable.

### 4.2 The order

| # | Product   | Why this slot |
|---|-----------|---|
| 1 | **Lookout**   | 8 templates, 1 script, 0 events, 11 style attrs. Smallest blast radius. Pilot the keel-side middleware + per-product wiring against this. |
| 2 | **Purser**    | 11 templates, 0 inline scripts, 0 events. Clean follow-up confirming the pattern. |
| 3 | **Manifest**  | 26 templates, 1 script. Raises the bar slightly; signing flow has UX-critical bits to canary. |
| 4 | **Admiralty** | 21 templates but only 2 events. Lets us validate the `onclick → addEventListener` rewrite recipe. |
| 5 | **Bounty**    | 20 templates; 1 script, 5 events; email templates handled separately. |
| 6 | **Helm**      | 34 templates, 4 events, dashboard-density. First "real" product test of nonce-ing dynamic dashboards. |
| 7 | **Beacon**    | 77 templates, 16 scripts, 16 events. Heavy. By now the recipe is solid. |
| 8 | **Yeoman**    | Last, because its Mapbox carve-out is its own conversation; do it after the suite-wide pattern is settled to avoid debating the carve-out under deadline pressure. |
| 9 | **Harbor**    | 109 templates, 16 events, 1 `javascript:` URL. The biggest tree gets the most-mature playbook. |

### 4.3 Per-product cutover sequence

For each product, the cutover is a four-step ladder. Each step is its own PR.

1. **Wire the keel middleware + context processor.** Land `KEEL_CSP_POLICY_REPORT_ONLY` (mirror of current policy with `'unsafe-inline'` swapped to `'{nonce}'` for script-src). Production runs the existing enforced policy AND reports violations against the new one. Page rendering is unaffected. Soak ≥ 7 days; monitor `/security/csp-violations/`.
2. **Rewrite inline scripts and event handlers.** Add `nonce="{{ csp_nonce }}"` to every `<script>` block; convert `onclick=` etc. to delegated listeners in `docklabs-v2.js` (preferred) or per-template inline scripts. Each rewrite re-soaks for 24h. Goal: violation count for the product trends to zero.
3. **Flip script-src to enforce.** Move the nonce-based policy from `KEEL_CSP_POLICY_REPORT_ONLY` to `KEEL_CSP_POLICY`. Drop `'unsafe-inline'` from script-src. Keep style-src as-is. Watch `/security/csp-violations/` for one more week; if any violation appears, revert in seconds (one settings edit).
4. **(Optional, deferred per product)** Begin extracting `style=""` attributes to CSS classes in product CSS. This is a slow background task, not a gate on the security win. When a product's style-attr count drops below ~20, evaluate whether `style-src` can be tightened too.

---

## 5. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Bootstrap/Popper writes runtime inline `style="…"` on tooltips, popovers, dropdowns. Tightening `style-src` would break every floating UI element across the suite. | **High** if attempted | Do NOT tighten `style-src` in this migration. Document as known residual. Revisit only when Popper or Bootstrap provides nonce-aware floating styles, or when `'unsafe-hashes'` is universally supported. |
| `docklabs-v2.js` may itself create elements with `.innerHTML = "<style>…</style>"` or `el.style.setProperty(...)`. The latter is fine; the former generates a non-noncedstyle block that violates CSP. | Medium | Audit `docklabs-v2.js` before step 3 of the per-product cutover. Replace any `innerHTML` style/script injection with `document.createElement` + `Object.assign(el.style, …)` or with a nonced clone. |
| Inline scripts inside email templates (Bounty's `grant_match.html`, `grant_digest.html`; Purser's `base_email.html`). Email clients ignore CSP, but these templates are also rendered in-product as previews. | Low | Keep `style=""` in the *email* render path; the CSP-relevant render is the in-product preview, which can use a class-based variant. Confirm both renders share a base template only at the layout level. |
| Third-party widgets — analytics, chat, embed scripts — added per product later. They typically inject their own inline scripts/styles. | Medium | Any new third-party `<script>` must either ship with a nonce (rare for SaaS embed snippets) or have its host explicitly added to `script-src` plus `'unsafe-hashes'` for the inline shim. PR template should ask "does this widget violate the CSP?" before merge. |
| Mapbox `'unsafe-eval'` in Yeoman is tribal-knowledge; future contributors may try to remove it. | Low | Add an inline comment in `yeoman_project/settings.py` explaining the carve-out + linking to this doc. |
| CSP report endpoint becomes a DoS amplifier under attack (a malicious site can trigger thousands of report POSTs from a real user's browser). | Medium | Per-IP rate limit (100/min) on `/security/csp-report/`. Drop reports above the limit silently; emit one log line per minute per IP. |
| Browser-reported violations include false positives from extensions injecting scripts. | Low | Filter `violated_directive=script-src` reports where `source_file` starts with `chrome-extension://`, `moz-extension://`, etc. before persisting. |
| The shared `report-uri` directive is deprecated; modern browsers want `report-to`. The two semantics differ. | Low | Emit BOTH in the report-only header (`report-uri /security/csp-report/; report-to csp-endpoint`). Define a `Reporting-Endpoints` header pointing the `csp-endpoint` group at the same URL. Future cleanup once `report-uri` is gone. |
| A product is bumped to keel ≥ X.Y but its `KEEL_CSP_POLICY` still contains `'unsafe-inline'` for script-src, silently undoing the migration. | Low | After step 3 lands for a product, add a `keel.security.checks` Django system check (`E001`-style) that warns when both `'unsafe-inline'` and `'{nonce}'` appear in the same directive. Surfaces in `manage.py check --deploy`. |

---

## 6. Acceptance criteria

A product is considered "migrated" when ALL of the following hold:

1. `KEEL_CSP_POLICY` (the enforced header) no longer contains `'unsafe-inline'` in `script-src`.
2. The same policy contains `'{nonce}'` in `script-src`.
3. Every `<script>` and `<style>` block in the product's templates carries `nonce="{{ csp_nonce }}"`.
4. No inline event-handler attributes (`onclick=`, `onload=`, etc.) remain in the product's templates. (`grep -rE 'on[a-z]+=' templates/` returns zero hits other than `onsubmit=` on `<form>` elements that use Django form validation — call those out explicitly if any survive.)
5. `/security/csp-violations/` shows **zero** new violations attributable to this product for the 7 calendar days preceding the enforce flip. The metric source is `CSPViolationReport` row count grouped by `document_uri` host; the dashboard already filters chrome-extension noise per the risk register.
6. `manage.py check --deploy` returns no CSP-related warnings.
7. The product's `CLAUDE.md` (or `keel/CLAUDE.md` if shared) has a one-line entry under "Security" stating the product is on the nonce-based policy and listing any product-specific exceptions.

`style-src` tightening is explicitly NOT a criterion for this migration. The `'unsafe-inline'` allowance for `style-src` remains until a separate follow-up addresses Bootstrap/Popper's runtime inline styling.

---

## 7. Out of scope

- **No breaking dependency upgrades.** Bootstrap stays on 5.3.3. Mapbox GL JS stays on whatever Yeoman currently pins. No Popper replacement. The migration must work with the libraries already in production.
- **`style-src` tightening.** See risk register and §3.5.
- **CSP for unauthenticated marketing pages** that don't go through `SecurityHeadersMiddleware` (none exist in the suite today, but `keel/layouts/public.html`-served pages should be re-verified).
- **Non-browser API endpoints** (`/api/v1/…`). These return JSON; CSP is meaningless for them but harmless if the header is sent.
- **Extending CSP to cover `frame-ancestors`, `form-action`, `base-uri`, `upgrade-insecure-requests`, `require-trusted-types-for`** — all valuable, all worth a separate audit pass after this one lands. Yeoman's `frame-ancestors 'none'` is already there and stays.
- **Subresource Integrity** on the CDN-served Bootstrap and Bootstrap Icons assets — also valuable, also separate.

---

## 8. Open questions for review

1. Is the decision to *not* tightening `style-src` in this migration acceptable, given that the audit framing asked for "nonce-based CSP" suite-wide? Recommendation in §3.5 is yes; flag for explicit approval.
2. Should the violation report endpoint be on each product (own DB, own dashboard) or a single shared keel.docklabs.ai endpoint that aggregates? Per-product is simpler and aligns with the standalone-deployability principle; aggregation is a Helm-style follow-up.
3. Is 7 days of report-only soak the right number? It catches weekly-batch jobs and weekend traffic; less than that risks missing a long-tail template. More than that delays the security win.
4. Bounty and Purser email templates are rendered in TWO contexts (email send + in-product preview). Confirm the in-product preview goes through `SecurityHeadersMiddleware` (it should — every Django response does) and that the CSP doesn't actually break the preview render. Worth a one-line manual test before step 3.

---

## 9. Next step

Land the keel-side plumbing first (nonce middleware, context processor, report endpoint, `SecurityHeadersMiddleware` interpolation, `KEEL_CSP_POLICY_REPORT_ONLY` setting). That's a single keel PR — call it `feat(security): CSP nonce middleware + report-only support` — bumping keel to 0.28.0 (or whatever follows current main). No product behavior changes from the keel PR alone.

The first product PR follows immediately against **Lookout** (8 templates, lowest inline content):

> `lookout: enable CSP report-only with nonce-based policy`

That PR pins keel to the new release, adds `KEEL_CSP_POLICY_REPORT_ONLY` + the `csp_nonce` context processor, and starts the 7-day soak. Subsequent PRs walk down the table in §4.2.

When the Lookout PR opens, link it back to this doc from the PR body so the broader rollout context is one click away.
