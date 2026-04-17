# DockLabs Engineering Principles

These principles ensure consistency across the DockLabs suite (Admiralty, Beacon, Bounty, Harbor, Helm, Lookout, Manifest, Purser, Yeoman). When working on any product, verify compliance and flag deviations.

## Session & Machine Context

### How Claude accesses this codebase
- **Claude Code** (run from Mac mini or laptop): Has full filesystem access to `/Users/dok/Code/CT/`. Use this for all code reading, editing, and terminal commands.
- **claude.ai chat interface**: The `bash_tool` runs in a remote sandboxed container — it has NO access to the local filesystem regardless of which physical machine Dan is using. SSH from that container to the Mac mini is blocked by egress restrictions.

### Machine setup
- **Mac mini (dispatch)**: M4 Pro, Tailscale IP `100.122.119.51`, SSH alias `macmini`, user `dok`. Primary dev machine. All DockLabs repos at `/Users/dok/Code/CT/`.
- **Laptop**: Also has the repos, synced via GitHub. Either machine may be the source of a claude.ai message.
- **Code is synced via GitHub** — the canonical source is always the same. There is no meaningful difference between "macmini code" and "laptop code" as long as both are up to date.

### What Claude should do at the start of each session
1. **Do not assume bash_tool works on the local machine** — it never does in claude.ai.
2. **Ask Dan to confirm the session type** if it's ambiguous whether he's in Claude Code or claude.ai chat, since capabilities differ significantly.
3. **When in Claude Code**: read `keel/CLAUDE.md` and relevant app `CLAUDE.md` files before responding to code questions.
4. **When in claude.ai chat**: work from memory/context; ask Dan to paste files or use `git show` output if code review is needed.

## Authentication & Identity

### Suite SSO — Keel as the OIDC Identity Provider (Phase 2b)

- **Keel is the canonical identity provider for the suite.** Users authenticate once against `https://keel.docklabs.ai` via OAuth2 / OpenID Connect, and each DockLabs product is a registered OIDC client. The old cookie-based cross-domain SSO (shared `SESSION_COOKIE_DOMAIN=.docklabs.ai`) was a stopgap and is being decommissioned.
- **Implementation:** Keel uses `django-oauth-toolkit>=2.4`. The IdP module lives at `keel/oidc/` and mounts under `/oauth/`:
  - `/oauth/authorize/` — authorization code flow with PKCE (S256)
  - `/oauth/token/` — token endpoint, 1h access / 14d refresh, rotation enabled
  - `/oauth/userinfo/`
  - `/oauth/.well-known/openid-configuration`
  - `/oauth/.well-known/jwks.json` (RS256 public key)
- **Required Keel env vars:**
  - `KEEL_OIDC_PRIVATE_KEY` — RSA 2048 PEM (generate with `openssl genrsa 2048`). Dev mode auto-generates an ephemeral key when `DEBUG=True`.
  - `KEEL_OIDC_ISSUER` — e.g. `https://keel.docklabs.ai`
- **Custom JWT claims.** `keel.oidc.validators.KeelOIDCValidator` emits a `product_access` claim that maps product codes to roles:
  ```json
  {"product_access": {"helm": "system_admin", "harbor": "analyst", ...}}
  ```
  plus `email`, `name`, `given_name`, `family_name`, `preferred_username`, `is_state_user`, `agency_abbr`. The `product_access` scope is declared in `OAUTH2_PROVIDER['SCOPES']`.
- **Products are OIDC clients** via `allauth.socialaccount.providers.openid_connect`. Each product's `settings.py` registers a provider under the `keel` provider_id when `KEEL_OIDC_CLIENT_ID` is set:
  ```python
  INSTALLED_APPS += ['allauth.socialaccount.providers.openid_connect']
  SOCIALACCOUNT_ADAPTER = 'keel.core.sso.KeelSocialAccountAdapter'
  SOCIALACCOUNT_LOGIN_ON_GET = True  # skip allauth's "Continue?" page
  if KEEL_OIDC_CLIENT_ID:
      SOCIALACCOUNT_PROVIDERS['openid_connect'] = {
          'APPS': [{
              'provider_id': 'keel',
              'name': 'Sign in with DockLabs',
              'client_id': KEEL_OIDC_CLIENT_ID,
              'secret': KEEL_OIDC_CLIENT_SECRET,
              'settings': {
                  'server_url': f'{KEEL_OIDC_ISSUER}/oauth/.well-known/openid-configuration',
                  'token_auth_method': 'client_secret_post',
                  'oauth_pkce_enabled': True,  # Keel requires PKCE
              },
          }],
      }
  ```
- **Per-product Railway env vars:** `KEEL_OIDC_CLIENT_ID`, `KEEL_OIDC_CLIENT_SECRET`, `KEEL_OIDC_ISSUER`. Unset the first two to fall back to local auth + direct Microsoft SSO (standalone mode still works for dev).
- **Registering a new product as an OIDC client:** run a Django shell against the Keel DB and create an `oauth2_provider.models.Application` with `client_type=confidential`, `authorization_grant_type=authorization-code`, `algorithm=RS256`, `skip_authorization=True`, and `redirect_uris=https://<host>/accounts/oidc/keel/login/callback/`. Set `client_id` and `client_secret` explicitly before `.save()` so you can capture the cleartext — allauth hashes `client_secret` on save. Yeoman uses `/auth/` instead of `/accounts/`, so its redirect is `https://yeoman.docklabs.ai/auth/oidc/keel/login/callback/`.
- **Session claim handoff.** `KeelSocialAccountAdapter.pre_social_login` stashes the claims into `request.session['keel_oidc_claims']` so `ProductAccessMiddleware` reads the per-product role from the claim instead of hitting the DB. `save_user` / returning-user branches also mirror the full `product_access` dict into `ProductAccess` rows so Keel-admin role changes propagate to products on the next login.
- **Extracting OIDC claims.** allauth nests them under `extra_data['userinfo']` and `extra_data['id_token']` (NOT the top level). Use `keel.core.sso._extract_keel_claims()` which prefers userinfo, falls back to id_token, and merges `product_access` from the signed token when userinfo is missing it.
- **Login card buttons.** Every product's shared `keel/login_card.html` shows **both** "Sign in with DockLabs" (Keel OIDC) and "Sign in with Microsoft" (direct Entra) when configured. The context processor `keel.core.context_processors.site_context` injects `keel_login_url` via `reverse('openid_connect_login', {'provider_id': 'keel'})` — do NOT use the provider registry, it's unreliable for dynamic OIDC apps in allauth 65.
- **`oidc_claim_scope` mapping is REQUIRED for custom claims.** django-oauth-toolkit's `OAuth2Validator.get_oidc_claims` filters every claim through `oidc_claim_scope`: a claim is only included in the issued ID token when the scope it maps to is present in the client's requested scopes. The base mapping only covers standard OIDC profile/email/address/phone claims. `KeelOIDCValidator` extends it to register `product_access`, `is_state_user`, and `agency_abbr` under the `product_access` scope. **If you add a new custom claim, you MUST add it to `oidc_claim_scope` on the validator class, or it will be silently stripped from every token.**
- **Products MUST request the `product_access` scope.** Each product's openid_connect APP settings must include `'scope': ['openid', 'email', 'profile', 'product_access']`. Without this, Keel scrubs the claim even though the validator returns it.
- **`dokadmin`** on Keel is the canonical superuser with `system_admin` `ProductAccess` for all 10 products. Email is `dok@dok.net`. Keel uses Django's native auth (username/password), not allauth — there's no Microsoft SSO on Keel itself. Products link to the local `dokadmin` user via `preferred_username` from the JWT (see adapter notes below), not by email.
- **User linking uses `preferred_username` first, email second.** `KeelSocialAccountAdapter.pre_social_login` matches the JWT's `preferred_username` claim against the local DB's `username` field FIRST, then falls back to email. This prevents the "zombie dan/dan2/dan3" pattern where allauth creates a new user from `given_name`+`family_name` when email doesn't match a legacy account. `populate_user` also unconditionally sets `user.username = preferred_username` from the JWT, overriding allauth's default name-derived username.
- **`AutoOIDCLoginMiddleware`** intercepts unauthenticated GET/HEAD requests to `/accounts/login/` (or `/auth/login/`) carrying a `?next=` query param and 302s them into the Keel OIDC flow. This makes fleet-switcher navigation seamless: clicking Harbor from Helm bounces through Keel's `/oauth/authorize/` (which already has a session) and lands on Harbor's dashboard without showing a login form. Direct visits to `/accounts/login/` without `?next=` still render the form. Active only when `KEEL_OIDC_CLIENT_ID` is set; respects `DEMO_MODE` (demo instances skip auto-OIDC).
- **`SuiteLogoutView`** chains product logout through Keel's `/suite/logout/` endpoint so the IdP session is also cleared. Accepts both GET and POST (Django 5's LogoutView requires POST by default, but users need a way to break out of stale sessions via link click). Demo instances chain through `demo-keel.docklabs.ai` automatically based on the Host header.
- **Message suppression.** `KeelAccountAdapter.add_message` suppresses "Successfully signed in as X" and "Signed out" toasts suite-wide — SSO users don't need to see these on every product switch. Suppression works by both template path (`SUPPRESSED_MESSAGE_TEMPLATES`) and rendered text substring (`SUPPRESSED_MESSAGE_SUBSTRINGS`). If allauth changes its message path in a future version, the substring filter catches it.

### Core identity rules (apply in all modes)

- **KeelUser is the canonical user model.** All products use `AUTH_USER_MODEL = 'keel_accounts.KeelUser'` with `keel.accounts.middleware.ProductAccessMiddleware`. All 9 products (including Admiralty) have been migrated.
- **SSO adapter:** Use `keel.core.sso.KeelAccountAdapter` and `keel.core.sso.KeelSocialAccountAdapter`. Do not create product-specific SSO adapters. `KeelAccountAdapter.get_login_redirect_url` resolves from `settings.LOGIN_REDIRECT_URL` (which MUST be `/dashboard/` — see Canonical URLs below). `KeelAccountAdapter.send_confirmation_mail` short-circuits when `keel_oidc_claims` is in the session so OIDC logins don't try to send a verification email.
- **Shared login form:** `keel.accounts.forms.LoginForm` provides a styled `AuthenticationForm` with "Username or email" / "Password" fields carrying `class="form-control"`. Every product's login URL wires this into the `authentication_form` kwarg so input fields render with Bootstrap styling. Do not fall back to Django's bare `AuthenticationForm` — the inputs render unstyled.
- **Shared auth templates:** Keel provides all auth templates in `keel/core/templates/account/` (login, signup, logout, password reset, email confirm, etc.). Products inherit these automatically via `APP_DIRS`. Product branding (icon, name, subtitle, demo mode) is driven entirely by `KEEL_PRODUCT_NAME`, `KEEL_PRODUCT_ICON`, `KEEL_PRODUCT_SUBTITLE` settings — do not create product-specific login pages.
- **Roles:** Define product-specific roles in `keel.accounts.ProductAccess`, not on the User model. `KeelUser.get_role_display()` humanizes the raw role string (e.g. `system_admin` → `System Admin`) using `ROLE_LABELS` with auto-title-case fallback. In `DEMO_MODE`, it prepends "Demo" (→ "Demo System Admin"). The shared sidebar calls `{{ user.get_role_display }}` — do not use `{{ user.role }}` directly in templates.

**Why:** Split identity prevents cross-product SSO, complicates Helm's executive dashboard, and creates maintenance burden with N copies of auth logic. OIDC also eliminates the cookie-domain fragility that kept invalidating dokadmin sessions on every `SECRET_KEY` rotation.

## Demo Mode

- **`DEMO_MODE=True`** activates demo branding and seed data across the suite.
- **Product name:** `site_context` appends " Demo" to `SITE_NAME` so the sidebar brand reads "Harbor Demo", "Beacon Demo", etc.
- **Role display:** `get_role_display()` prepends "Demo" to every role label (→ "Demo System Admin", "Demo Analyst").
- **Seed data:** `keel.core.startup.run_startup()` auto-seeds demo users and domain data when `DEMO_MODE=True` and the DB is empty. Demo sites (`demo-*.docklabs.ai`) use this; production sites (`*.docklabs.ai`) do NOT.
- **AutoOIDCLoginMiddleware** skips auto-OIDC redirect in `DEMO_MODE` so demo users can log in via the local form with demo credentials.
- **`SuiteLogoutView`** chains through `demo-keel.docklabs.ai` (not `keel.docklabs.ai`) on demo instances, auto-detected from the Host header.
- **Dashboard greeting:** Only Helm shows a "Welcome back" greeting (auto-fades after 4s, once per session). Other products show just "Dashboard" as the page header — no per-product greeting in suite mode.

## Canonical URLs

- **Every product exposes `/dashboard/` as its canonical post-login URL.** This is a hard requirement — set `LOGIN_REDIRECT_URL = '/dashboard/'` in every product's settings and mount the **real** dashboard view at `/dashboard/` (not a `RedirectView` — the browser URL bar must stay at `/dashboard/`, not bounce to `/helm/` or `/packets/` or `/foia/dashboard/`).
- For products whose dashboard view lives at a different historical path, import the view directly and mount it a second time at `/dashboard/` with `name='dashboard_alias'`:
  ```python
  # helm_site/urls.py
  from dashboard.views import DashboardView
  urlpatterns = [
      path('helm/', include('dashboard.urls')),  # legacy path
      path('dashboard/', DashboardView.as_view(), name='dashboard_alias'),
  ]
  ```
- **`KEEL_FLEET_PRODUCTS` urls must end in `/dashboard/`.** The fleet switcher sends users between products; any entry ending in `/` dumps them on the public landing page. The canonical list is baked into each product's `settings.py`:
  ```python
  KEEL_FLEET_PRODUCTS = [
      {'name': 'Helm', 'label': 'Helm', 'code': 'helm', 'url': 'https://helm.docklabs.ai/dashboard/'},
      {'name': 'Harbor', 'label': 'Harbor', 'code': 'harbor', 'url': 'https://harbor.docklabs.ai/dashboard/'},
      # ... all 9 products
  ]
  ```
- **`LandingView.authenticated_redirect`** must be a URL name that resolves to `/dashboard/` (e.g. `'dashboard_alias'` on products that use the alias pattern, or `'dashboard:index'` on Helm). A plain `'dashboard'` fails with `NoReverseMatch` on products where the URL name is namespaced.

**Why:** Users navigate between products constantly. A single canonical entry URL prevents 404s from fleet-switcher clicks and makes the suite feel coherent.

## UI & Frontend

- **CSS:** Use `keel/core/static/css/docklabs.css` (and the v2 successor `docklabs-v2.css`) as the shared design system. Product-specific CSS should only add product-unique components (e.g., `harbor.css` for grant cards), never override shared styles.
- **Bootstrap 5.3.3** via CDN. Do not pin different Bootstrap versions across products.
- **Bootstrap Icons 1.11.3** via CDN.
- **Google Fonts: Poppins** — consistent typeface across all products.
- **Shared components in `keel/core/templates/keel/components/`:**
  - `stat_card.html` / `stat_cards_row.html` — KPI metric cards. Every dashboard MUST use these; do not hand-roll `<div class="card border-primary">` stacks. Accepted colors: `green`, `gold`, `red`, `blue`, `purple`, `orange`, `teal`. Use `url=` to make the card clickable as a filter shortcut.
  - `sidebar.html`, `topbar.html`, `fleet_switcher.html`
  - `empty_state.html`, `deadline_card.html`, `page_tabs.html`
  - `chart.html`, `chart_scripts.html`
- **Sidebar markup:** Every `base.html` sidebar block must use the structured `.sb-item` / `.sb-icon` / `.sb-item-label` markup that `keel/layouts/app.html` expects. Do not use bare `<a>` tags — they render as an unstyled flat list.
  ```django
  <a class="sb-item{% if request.resolver_match.url_name == 'index' %} active{% endif %}" href="{% url 'dashboard:index' %}">
    <span class="sb-icon"><i class="bi bi-speedometer2"></i></span>
    <span class="sb-item-label">Dashboard</span>
  </a>
  ```
- **Authenticated pages must extend `base.html`** (which extends `keel/layouts/app.html`), not `base_public.html` (which uses the marketing `keel/layouts/public.html` and drops the sidebar). Bounty's `portal/federal_opportunities.html` was a real bug caused by this mistake.
- **Template tags:** Use `keel_tags` (sortable_th, role_badge, unread_count, dict_get) before writing product-specific versions.
- **Accessibility:** WCAG 2.1 AA minimum — skip links, focus-visible styles, semantic HTML, ARIA labels.
- **Global keyboard shortcut ⌘K / Ctrl+K** opens the shared search modal defined in `keel/layouts/app.html` (`#keelSearchModal`). The modal submits a GET to `{% block search_action_url %}/search/{% endblock %}` — products that don't yet have a search endpoint can leave the block unset (it will 404 on submit, which is honest). Don't remove the modal or the keybinding; they're part of the shared chrome.
- **Notification preferences link.** `keel.notifications` ships a preferences view at `/notifications/preferences/`. The shared sidebar user dropdown surfaces it automatically via `sidebar_user_menu_default` in `keel/layouts/app.html`, guarded with `{% url 'keel_notifications:preferences' as notif_prefs_url %}` so products missing the namespace don't crash. **Django template variables MUST NOT begin with an underscore** — the guard variable is `notif_prefs_url`, not `_notif_prefs_url`. The underscore prefix raises `TemplateSyntaxError` on every render.

**Why:** Users navigate between products; visual inconsistency erodes trust and creates confusion. The shared components exist so every product's dashboard, sidebar, and chrome look identical out of the box.

## Keel Integration (Minimum Required)

Every DockLabs product MUST include:

1. **INSTALLED_APPS:** `keel.core`, `keel.security`, `keel.notifications`
2. **Middleware (in order):**
   - `keel.security.middleware.SecurityHeadersMiddleware`
   - `keel.security.middleware.FailedLoginMonitor`
   - `keel.accounts.middleware.ProductAccessMiddleware`
   - `keel.core.middleware.AuditMiddleware` (at end)
3. **Models (extend from Keel):**
   - `AuditLog(AbstractAuditLog)`
   - `Notification(AbstractNotification)`
   - `NotificationPreference(AbstractNotificationPreference)`
   - `NotificationLog(AbstractNotificationLog)`
4. **Settings:**
   - `KEEL_PRODUCT_NAME`, `KEEL_PRODUCT_ICON`, `KEEL_PRODUCT_SUBTITLE`
   - `KEEL_AUDIT_LOG_MODEL`, `KEEL_NOTIFICATION_MODEL`
   - `KEEL_FOIA_EXPORT_MODEL` (concrete FOIAExportItem model)
   - `LOGIN_REDIRECT_URL = '/dashboard/'`
   - `KEEL_FLEET_PRODUCTS` (canonical 9-product list with `/dashboard/` urls)
   - `KEEL_OIDC_CLIENT_ID`, `KEEL_OIDC_CLIENT_SECRET`, `KEEL_OIDC_ISSUER` (production)
   - `EMAIL_BACKEND = 'keel.notifications.backends.resend_backend.ResendEmailBackend'` (production)
   - `DEFAULT_FROM_EMAIL = 'DockLabs <info@docklabs.ai>'`
   - `SECURE_SSL_REDIRECT = False` — Railway's healthcheck sends plain HTTP; the proxy handles TLS termination. Setting this `True` causes `301` healthcheck failures.
5. **URLs:** Include `keel.requests.urls` for feedback/support requests, `keel.foia.urls` for FOIA export. Must define a `path('dashboard/', …, name='dashboard_alias')` if the real dashboard view lives elsewhere.
6. **Context processor:** `keel.core.context_processors.site_context`

**Why:** This is the baseline that gives us audit trails, security monitoring, notifications, consistent branding, and a working suite-wide SSO.

## Workflows & Status Tracking

- **Any model with a `status` field MUST use `keel.core.workflow.WorkflowEngine`** with declarative `Transition` definitions. No ad-hoc status updates in views.
- **Use `AbstractStatusHistory`** to create an immutable transition log for every status-bearing model.
- **Use `WorkflowModelMixin`** on the model itself so it exposes `transition()`, `can_transition()`, `get_available_transitions()`.
- **Use `WorkQueueMixin`** for models that need work queue assignment and routing.

**Why:** Ad-hoc status management in views bypasses role checks, skips audit logging, and makes the transition rules invisible. Harbor's 4 declarative workflows are the reference implementation.

## Communications (keel.comms)

- **Use `keel.comms` for all email communications** that are entity-routed (tied to a grant, request, case, etc.). Do not build product-specific email sending.
- **MailboxAddress** provides deterministic routing addresses (e.g., `harbor+grant-4821@mail.docklabs.ai`). Link to product entities via `CommsMailboxMixin` (GenericForeignKey).
- **Thread/Message models** handle RFC 5322 threading with Message-ID/In-Reply-To/References headers.
- **Postmark integration** for delivery tracking (pending, sent, delivered, bounced, failed).
- **Built-in PostgreSQL FTS** on Message for full-text search.
- **Settings:** `COMMS_MAIL_DOMAIN`, `COMMS_POSTMARK_SERVER_TOKEN`.

**Why:** Communications are the most commonly FOIA-requested category. Centralizing them in Keel ensures every product's correspondence is searchable, auditable, and FOIA-exportable without product-specific email plumbing.

## Search (keel.search)

- **Use `keel.search.SearchEngine`** for all search functionality. Subclass it with your model, `search_fields` dict, and `trigram_fields`.
- **Three-tier search:** instant typeahead (<30ms) with prefix/FTS/trigram fallback, full ranked search with `SearchRank`, and extensible filters.
- **AI chat search:** Subclass `SearchChat` for natural language search with Claude-powered keyword extraction and streaming SSE responses.
- **Reusable views:** `instant_search_view()` for typeahead JSON, `chat_stream_view()` for SSE AI chat.
- **Global ⌘K modal submits to `/search/`** — products should wire an endpoint matching this convention when they adopt search.
- **PostgreSQL required:** GIN indexes on `search_vector` fields. Not compatible with SQLite for search features.

**Why:** Consistent search UX across products. Centralized AI integration via `keel.core.ai` settings.

## Calendar Integration (keel.calendar)

- **Use `keel.calendar` for all calendar sync.** Do not integrate directly with Google/Microsoft APIs.
- **Register event types** with `CalendarEventType` in `AppConfig.ready()`.
- **Service API:** `push_event()`, `update_event()`, `cancel_event()`, `check_availability()`.
- **Provider-agnostic:** Google Calendar and Microsoft Outlook providers. Resolution order: explicit > event_type > `KEEL_CALENDAR_PROVIDER` setting.
- **Optional persistence:** Configure `KEEL_CALENDAR_EVENT_MODEL` and `KEEL_CALENDAR_SYNC_LOG_MODEL` for audit trails.
- **iCal export:** `generate_ical()` and `generate_single_ical()` for download/feed.

**Why:** Multiple products need calendar features (hearings, deadlines, reviews). Centralizing prevents N provider integrations and ensures consistent event formatting.

## Notifications

- **Register notification types** using `keel.notifications.registry` for every significant event.
- **Use `notify()` from `keel.notifications.dispatch`** — never create Notification objects directly.
- **Default channels:** in-app + email. Let users control via NotificationPreference.
- **Use `link_template`** from the notification catalog for consistent deep-linking across products.
- **Preferences page:** `keel.notifications` provides `/notifications/preferences/` (URL name `keel_notifications:preferences`). The shared sidebar user dropdown already links to it — do not build a product-specific preferences page.

**Why:** Consistent notification UX across products; Helm aggregates notifications and needs a standard structure.

## AI Integration

- **Use `keel.core.ai.get_client()` and `call_claude()`** for all Anthropic API calls. Do not instantiate the client directly.
- **Use `keel.core.ai.parse_json_response()`** for structured output parsing.
- **Model setting:** `KEEL_AI_MODEL` (defaults to claude-sonnet-4-20250514).

**Why:** Centralizes API key management, model version control, and token limits.

## Collaboration & Notes

- **Internal notes:** Extend `keel.core.models.AbstractInternalNote` (provides `is_internal` visibility flag). Do not create custom note models without this pattern.
- **Comments with visibility:** Always support internal (staff-only) and external visibility.

**Why:** Harbor's comment system is the reference — government staff need to add internal-only notes that applicants can't see.

## FOIA Compliance

- **FOIA awareness is a core tenet of every product.** Any content submitted by or on behalf of an agency — interactions, notes, documents, financial records, schedules, applications, testimony, communications — must be exportable to Admiralty via the FOIA export pipeline.
- **Communications are the highest priority.** If a product adds emails, messages, letters, public comments, hearing transcripts, or any correspondence, these **must** be registered as FOIA-exportable types.
- **Keel owns the export pipeline.** `keel.foia` provides `AbstractFOIAExportItem`, `FOIAExportRegistry`, `submit_to_foia()`, and `bulk_submit_to_foia()`. Products create a concrete `FOIAExportItem` subclass.
- **Admiralty owns the FOIA workflow.** Request intake, scope, search, determination, response, and appeal all live in Admiralty, not Keel. Products only push records to the export queue.
- **Register exportable types** with `foia_export_registry.register()` in `AppConfig.ready()`. Use `FOIAReadyAppConfig` as the base class for automatic validation.
- **Add export buttons** to detail views via `FOIAExportMixin` and `{% load foia_tags %}{% foia_export_button record "type" "product" %}`.
- **Every export captures:** full content, timestamp, author identity, IP address (`request.audit_ip`), content hash (SHA256 for dedup), and associated entities.
- **Cross-database linking:** `foia_request_id_ref` is a string reference to Admiralty (no FK — products and Admiralty may use separate databases).
- **Settings required:** `KEEL_FOIA_EXPORT_MODEL = 'core.FOIAExportItem'`.
- **Validate with:** `python manage.py foia_audit` (use `--fail-on-error` in CI/CD).

**Why:** DockLabs products operate in a government transparency context. FOIA staff must be able to one-click export any agency-submitted record to Admiralty without developer intervention. Incomplete FOIA coverage is a legal liability.

## Groups & Tags on People/Entity Records

Products that maintain people-style records (contacts, stakeholders, applicants) should follow a getdex-style split between **Tags** and **Groups**:

- **Tag** = a categorical label controlled by the platform/admin (industry, region, program). Often enumerated (`TagType` choices). Shared across many entity types.
- **ContactGroup** (or analogous) = a user-defined collection of records the user curates ("Inbound", "VIPs", "Board Candidates", "Reporters"). Has a `slug`, a human-readable `name`, and an `is_system` flag for platform-managed groups that users cannot rename or delete.
- Both are M2M on the entity — a contact can carry any number of tags AND any number of groups. Neither implies an org/parent affiliation — that is the job of a `Company` / `Organization` FK.
- **Parent FK (e.g. `Contact.company`) MUST be nullable.** A contact the user knows personally, or one that arrived via external intake without an organization, belongs to no company but still lives in Beacon — typically surfaced via the "Inbound" system group. Do not invent a sentinel "Inbound" company to satisfy a NOT NULL constraint; groups are the right primitive for that.
- **System groups are seeded lazily by the code that needs them** (e.g. intake API calls `get_or_create(slug='inbound', defaults={'is_system': True, ...})`), not via migrations. This keeps the pattern portable across products and avoids data migrations every time a new intake source appears.
- Detail templates / list pages must tolerate `entity.company is None` and simply omit the company — a contact without a company is just a contact, not an "orphan." The canonical contact URL should be by primary key (`/contacts/<id>/`), not scoped under a company slug, so it works regardless of company affiliation. `get_absolute_url()` should always use the pk-based route.

**Why:** Real-world CRM-style data includes lots of people who don't neatly belong to an organization — inbound leads, journalists, personal contacts, event attendees. Forcing every contact to attach to a company creates sentinel-company pollution ("Inbound", "Unknown", "Individual") that corrupts reporting and duplicates the job groups already do well. The getdex model — contacts have many groups, many tags, and optionally an org — is a better fit.

## Cross-Product Linkage (Provenance)

When one DockLabs product creates a record in another (e.g., Yeoman creates a Contact in Beacon from a speaking-engagement request), the receiving product **MUST** capture a link back to the originating record so a user inspecting the new record can navigate to whatever drove its creation.

- **Receiving product accepts provenance fields** on its intake API (typically `source_product`, `source_url`, `source_label`). Persist these on the created record AND drop a row in the receiving product's activity stream / interaction log that surfaces the link to users browsing that record's history.
- **Sending product passes the provenance** when calling the intake API, but treats the call as best-effort — a 4xx/5xx from the other product MUST NOT block the originating workflow. Wrap the cross-product call in a try/except and log on failure; the user's primary action (submitting a speaking request) succeeds regardless.
- **Standalone deployment must still work.** Provenance fields are always optional. A product deployed alone (with no peers calling it) functions identically; the fields stay blank. Likewise the sending product gracefully no-ops when its peer's URL/API key isn't configured (`if not BEACON_INTAKE_URL: return`).
- **No hard FKs across product DBs.** Provenance is a string slug + URL, never a database foreign key. Products may live in separate Postgres instances, and the linked record may be deleted or moved without breaking the receiver. Treat the URL like an external link.
- **Suite-mode enrichment is additive.** When products are deployed together, the activity-stream entry can render the source URL as a clickable link with the product's icon/label. When deployed alone, the same entry still reads correctly as plain text.
- **Gate the UI, not just the wire call.** Cross-product action controls (e.g. an "Add to Beacon" button on a Yeoman invitation) MUST be hidden when the peer isn't configured — don't render a button that silently no-ops or errors. Expose an `is_available()` helper in the integration service module (returns True when both the peer URL and API key are set), pass its result into the template context, and wrap the control in `{% if peer_available %}`. This way the same template works in standalone, two-product, and full-suite deployments without per-environment branches.
- **Why:** Users navigating from a Beacon contact need to answer "where did this come from?" without leaving Beacon. Without a link back, cross-product creation produces orphan records that look manually entered, which erodes trust in the data and makes audit/FOIA review harder.

## Security

- **CSP:** Configure `KEEL_CSP_POLICY` in settings. `SecurityHeadersMiddleware` adds Content-Security-Policy, Permissions-Policy, X-Content-Type-Options, and Cross-Origin-Opener-Policy headers automatically.
- **Brute-force protection:** `FailedLoginMonitor` auto-locks after N failures (default 10 in 15-min window). Configurable via settings.
- **Admin IP allowlist:** `AdminIPAllowlistMiddleware` restricts `/admin/` access via `KEEL_ADMIN_ALLOWED_IPS` (CIDR and single IP).
- **File uploads:** Use `keel.security.scanning.FileSecurityValidator` on all file upload fields.
- **Upload limits:** Honor `KEEL_MAX_UPLOAD_SIZE` and `KEEL_ALLOWED_UPLOAD_EXTENSIONS`.
- **Session security:** 1-hour session expiry, HTTPONLY cookies, SameSite=Lax.

**Why:** Government-facing products require defense in depth. Centralizing security policy prevents products from shipping with missing headers or inconsistent protections.

## Deployment & Configuration

- **Startup:** Use `keel.core.startup.run_startup()` in Railway Procfile. It runs migrate, collectstatic, configures Site objects, and optionally seeds demo users (`DEMO_MODE=true`). Pass `extra_commands` for product-specific post-startup tasks.
- **Email:** Resend backend via Keel in production, console backend in development.
- **Static files:** WhiteNoise compressed manifest storage.
- **Database:** PostgreSQL in production, SQLite in development (except for search/comms features which require PostgreSQL). Use `dj-database-url`.

### Keel version bumping — the pip cache trap

**Every meaningful change to Keel MUST bump `keel.__version__` AND `pyproject.toml` version.** Pip's `git+https://...@<commit>` resolver caches by package name+version (`keel==X.Y.Z`), not by git ref. If you push a new commit but don't bump the version, products that rebuild on Railway see `Requirement already satisfied: keel==X.Y.Z` and happily reuse the stale wheel from the previous build. Symptom: deploys "succeed" but production is still running code from hours or days ago.

```python
# keel/__init__.py
__version__ = '0.10.9'

# pyproject.toml
version = "0.10.9"
```

Bump both files in the same commit as the code change, then bump pins in all product `requirements.txt` files referencing the new git commit.

### Railway CLI access

- **The Railway CLI is installed and authenticated** (`railway` command, logged in as `inbox@okeefeweb.com`). Use it for managing env vars, checking deploy status, and triggering deployments across all 10 DockLabs services.
- **Project structure:** Each product is its own Railway project with `<product>` (production) and `<product>-demo` services in the same project, sharing a single Postgres service.
- **Useful commands:**
  - `railway link -p <project> -e production` — link to a project
  - `railway service status --all` — check all services in the linked project
  - `railway variable set KEY=VALUE --service <service> --skip-deploys` — set env vars without triggering a deploy
  - `railway variable list --service <service> --kv` — list env vars
  - `railway up --service <service> --detach` — manual deploy (for services without auto-deploy)
  - `railway ssh --service <service> -- <command>` — run a command on the remote service (e.g., `railway ssh --service admiralty-demo -- python manage.py seed_keel_users`). Use this for management commands that need to hit the live database. **Do not confuse with `railway run`**, which executes locally with remote env vars injected — it won't find `manage.py` unless you're in the right local directory.
- **Auto-deploy:** Most services auto-deploy on `git push` to `main`. Manifest sometimes needs `railway up --service manifest --detach` if its GitHub integration is broken.

### Railway deployment notes

- **`SECURE_SSL_REDIRECT` MUST be `False`** on Railway — the healthcheck sends plain HTTP and a `True` setting makes it 301-redirect, failing the check and blocking deploys. Preventive: Keel's settings sets it to `False`; product settings should not override.
- **Manifest may need `railway up --service manifest --detach`** if its GitHub auto-deploy integration is still broken. Most other products auto-deploy on push. Verify by checking `railway service status --all` after a push — if the deploy ID doesn't change, use `railway up`.
- **Bounty has a legacy `core_user` table** alongside the current `keel_user`. Some old FK constraints may reference `core_user`. If migrations fail with "FK violation on core_user", the recovery pattern is: (1) drop the offending FK constraint, (2) copy missing users from `core_user` to `keel_user` if needed, (3) re-add the FK pointing at `keel_user`.

## Data Patterns

- **Compliance tracking:** Use `keel.compliance` (ComplianceTemplate, ComplianceObligation, ComplianceItem) instead of product-specific compliance models.
- **Fiscal periods:** Use `keel.periods` for any product dealing with fiscal years/months.
- **Archived records:** Use `AbstractArchivedRecord` with retention policies for data governance.
- **Generic relations:** `MailboxAddress`, `CalendarEvent`, and `FOIAExportItem` all use GenericForeignKey to link to product entities. Follow this pattern for new cross-cutting models.

---

## Known Deviations

- **KEEL_FOIA_EXPORT_MODEL** is not yet defined in any product's settings — FOIA export pipeline integration is pending.
- **keel.core.foia_urls** is only included in Harbor, Manifest, and Admiralty — other products need it added as they adopt FOIA export.
- **`/search/` endpoint is not implemented on any product.** The shared ⌘K modal submits there but every product will 404 until a product-specific `keel.search`-backed view is wired up.
- **Bounty has a legacy `core_user` table** with orphan FK constraints. Most were dropped during the Phase 2b cleanup, but some product-specific tables may still reference it. See Railway deployment notes for the recovery pattern.
- **Helm feed pipeline is wired for all 8 products.** `keel.feed` provides the shared framework (`helm_feed_view` decorator + `fetch_product_feed` client). All 8 products expose `/api/v1/helm-feed/` with real-time metrics from live data. Helm's `fetch_feeds` management command pulls data into `CachedFeedSnapshot`. **Deployment:** set `HELM_FEED_API_KEY` as a shared env var on all 9 Railway services (8 products + Helm). In `DEMO_MODE`, auth is bypassed and `seed_helm` provides static demo data as a fallback. Feed endpoint files: `harbor/api/helm_feed.py` (reference), `bounty/api/helm_feed.py`, `beacon/api/helm_feed.py`, `admiralty/foia/helm_feed.py`, `manifest/signatures/helm_feed.py`, `lookout/api/helm_feed.py`, `purser/purser/helm_feed.py`, `yeoman/yeoman/helm_feed.py`.

---

## Completed cleanup (Phase 2b.5)

These items were completed during the Phase 2b OIDC rollout session:

1. ✅ **Cookie SSO decommissioned.** `KEEL_SUITE_DOMAIN` / `SESSION_COOKIE_DOMAIN` blocks removed from all 9 products.
2. ✅ **Bounty and Manifest on their own Postgres.** `DATABASE_URL` flipped from Harbor's shared DB to each project's own Postgres service (`ballast` for Bounty, `shinkansen` for Manifest).
3. ✅ **Purser auto-deploy fixed** and runtime `pip --force-reinstall` workaround removed from `start.sh`.
4. ✅ **Beacon has `keel.notifications`** in INSTALLED_APPS and URLs wired.
5. ✅ **User state consolidated.** All 10 DBs paved to a single `dokadmin` user; zombie `dan/dan2/dan3/...` users cleaned up. Adapter fixed to prevent recurrence (preferred_username linking + unconditional username assignment).
6. ✅ **`AutoOIDCLoginMiddleware`** deployed to all 9 products for seamless fleet switching.
7. ✅ **`SuiteLogoutView`** + Keel `suite_logout_endpoint` for cross-product logout chain.
8. ✅ **Message suppression** for "signed in as" and "signed out" toasts.
9. ✅ **Demo branding** — "Demo" prefix on roles and product name in `DEMO_MODE`.
10. ✅ **Dashboard greeting** only on Helm (auto-fades, once per session).

---

*Last updated: 2026-04-09.*
