# DockLabs Engineering Principles

These principles ensure consistency across the DockLabs suite (Harbor, Beacon, Bounty, Lookout, Purser, Yeoman, Helm, Admiralty). When working on any product, verify compliance and flag deviations.

## Authentication & Identity

- **KeelUser is the canonical user model.** All products use `AUTH_USER_MODEL = 'keel_accounts.KeelUser'` with `keel.accounts.middleware.ProductAccessMiddleware`. All 9 products (including Admiralty) have been migrated.
- **SSO adapter:** Use `keel.core.sso.KeelAccountAdapter` and `KeelSocialAccountAdapter`. Do not create product-specific SSO adapters.
- **Login template:** Keel provides a shared `account/login.html` template (extends `keel/layouts/auth.html`, includes `keel/login_card.html`). All products use this via `template_name='account/login.html'` in their URL config. Product branding (icon, name, subtitle, SSO, demo mode) is driven entirely by `KEEL_PRODUCT_NAME`, `KEEL_PRODUCT_ICON`, `KEEL_PRODUCT_SUBTITLE` settings — do not create product-specific login pages.
- **Roles:** Define product-specific roles in `keel.accounts.ProductAccess`, not on the User model.

- **Shared auth templates:** Keel provides all auth templates in `keel/core/templates/account/` (login, signup, logout, password reset, email confirm, etc.). Products inherit these automatically via `APP_DIRS`. Only override if a product has genuinely unique auth needs (e.g., Bounty's approval signup).

**Why:** Split identity prevents cross-product SSO, complicates Helm's executive dashboard, and creates maintenance burden with N copies of auth logic.

## UI & Frontend

- **CSS:** Use `keel/core/static/css/docklabs.css` as the shared design system. Product-specific CSS should only add product-unique components (e.g., `harbor.css` for grant cards), never override shared styles.
- **Bootstrap 5.3.3** via CDN. Do not pin different Bootstrap versions across products.
- **Bootstrap Icons 1.11.3** via CDN.
- **Google Fonts: Poppins** — consistent typeface across all products.
- **Template tags:** Use `keel_tags` (sortable_th, role_badge, unread_count, dict_get) before writing product-specific versions.
- **Color palette:** CT brand accent bar, DockLabs color tokens defined in docklabs.css.
- **Accessibility:** WCAG 2.1 AA minimum — skip links, focus-visible styles, semantic HTML, ARIA labels.

**Why:** Users navigate between products; visual inconsistency erodes trust and creates confusion.

## Keel Integration (Minimum Required)

Every DockLabs product MUST include:

1. **INSTALLED_APPS:** `keel.core`, `keel.security`, `keel.notifications`
2. **Middleware (in order):**
   - `keel.security.middleware.SecurityHeadersMiddleware`
   - `keel.security.middleware.FailedLoginMonitor`
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
   - `EMAIL_BACKEND = 'keel.notifications.backends.resend_backend.ResendEmailBackend'` (production)
   - `DEFAULT_FROM_EMAIL = 'DockLabs <info@docklabs.ai>'`
5. **URLs:** Include `keel.requests.urls` for feedback/support requests, `keel.foia.urls` for FOIA export
6. **Context processor:** `keel.core.context_processors.site_context`

**Why:** This is the baseline that gives us audit trails, security monitoring, notifications, and consistent branding across all products.

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
- **Keel pin:** All products should reference the same Keel git commit in requirements. When Keel is updated, all products should be updated together. *Current status: Purser is one commit behind — needs bump from `fe3165f` to `db2b62c`.*

## Data Patterns

- **Compliance tracking:** Use `keel.compliance` (ComplianceTemplate, ComplianceObligation, ComplianceItem) instead of product-specific compliance models.
- **Fiscal periods:** Use `keel.periods` for any product dealing with fiscal years/months.
- **Archived records:** Use `AbstractArchivedRecord` with retention policies for data governance.
- **Generic relations:** `MailboxAddress`, `CalendarEvent`, and `FOIAExportItem` all use GenericForeignKey to link to product entities. Follow this pattern for new cross-cutting models.

---

## Known Deviations

- **Beacon** is missing `keel.notifications` in `INSTALLED_APPS` — needs to be added.
- **Purser** Keel pin is at `fe3165f`, one commit behind the rest of the suite at `db2b62c`.
- **KEEL_FOIA_EXPORT_MODEL** is not yet defined in any product's settings — FOIA export pipeline integration is pending.
- **keel.core.foia_urls** is only included in Harbor, Manifest, and Admiralty — other products need it added as they adopt FOIA export.

---

*Last updated: 2026-04-06.*
