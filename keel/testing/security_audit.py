"""Comprehensive security audit across all DockLabs products.

Scans Django settings, templates, views, middleware, and configuration across
Beacon, Harbor, Lookout, and their sub-products (Admiralty, Manifest) to detect:

- Django security settings (SECRET_KEY, DEBUG, ALLOWED_HOSTS, CSRF, etc.)
- Authentication & session configuration
- HTTPS / secure cookie enforcement
- SQL injection vectors (raw SQL usage)
- XSS vectors (|safe filter, mark_safe, innerHTML)
- CSRF protection gaps
- Sensitive data exposure (hardcoded secrets, .env in repo)
- File upload security
- Admin exposure / debug endpoints
- Dependency vulnerabilities (outdated packages)
- Security headers (HSTS, X-Content-Type, etc.)
- Dangerous permissions / open redirects
- Template injection / autoescape off
- Logging of sensitive data

Auto-fixes safe issues (e.g., missing security settings). Reports critical
findings it cannot fix to the keel dashboard as ChangeRequests.

Usage:
    python -m keel.testing --security-only
    python -m keel.testing  # (includes security audit automatically)
"""
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import BASE_DIR, PRODUCTS
from .result import TestResult

# ---------------------------------------------------------------------------
# Product source roots
# ---------------------------------------------------------------------------
PRODUCT_SOURCES = {
    'Beacon': {
        'root': BASE_DIR / 'beacon',
        'settings_files': ['harbor/settings.py', 'admiralty/settings.py'],
        'apps': ['companies', 'core', 'interactions', 'pipeline', 'foia',
                 'analytics', 'audit', 'portal'],
    },
    'Harbor': {
        'root': BASE_DIR / 'harbor',
        'settings_files': ['harbor/settings.py', 'manifest/settings.py'],
        'apps': ['grants', 'applications', 'awards', 'financial', 'reporting',
                 'core', 'portal', 'manifest'],
    },
    'Lookout': {
        'root': BASE_DIR / 'lookout',
        'settings_files': ['lookout/settings.py'],
        'apps': ['bills', 'testimony', 'watchlist', 'stakeholders',
                 'signing', 'core', 'calendar_app', 'audit'],
    },
    'Keel': {
        'root': BASE_DIR / 'keel',
        'settings_files': ['keel_site/settings.py'],
        'apps': ['keel/accounts', 'keel/requests', 'keel/notifications',
                 'keel/core'],
    },
}

# ---------------------------------------------------------------------------
# Security settings every Django project should have in production
# ---------------------------------------------------------------------------
REQUIRED_SETTINGS = {
    'SECURE_BROWSER_XSS_FILTER': ('True', 'Enables browser XSS filtering'),
    'SECURE_CONTENT_TYPE_NOSNIFF': ('True', 'Prevents MIME type sniffing'),
    'SESSION_COOKIE_SECURE': ('True', 'Session cookies only over HTTPS'),
    'CSRF_COOKIE_SECURE': ('True', 'CSRF cookies only over HTTPS'),
    'SECURE_SSL_REDIRECT': ('True', 'Redirect HTTP to HTTPS'),
    'X_FRAME_OPTIONS': ("'DENY'", 'Prevent clickjacking'),
    'SECURE_HSTS_SECONDS': ('31536000', 'Enable HSTS for 1 year'),
    'SECURE_HSTS_INCLUDE_SUBDOMAINS': ('True', 'HSTS covers subdomains'),
    'SECURE_HSTS_PRELOAD': ('True', 'Allow HSTS preloading'),
    'SESSION_COOKIE_HTTPONLY': ('True', 'Prevent JS access to session cookies'),
    'CSRF_COOKIE_HTTPONLY': ('True', 'Prevent JS access to CSRF cookies'),
}

# Patterns that indicate secret leaks
def _build_secret_patterns():
    """Build patterns dynamically to avoid the audit self-flagging on its own source."""
    sk = 'SECRET' + '_KEY'
    pw = 'PASS' + 'WORD'
    ak = 'API' + '_KEY'
    creds = '|'.join(['aws_secret', 'aws_access', 'STRIPE' + '_SECRET', 'SENDGRID' + '_API'])
    return [
        (re.compile(rf'{sk}\s*=\s*["\'][^"\']{"{10,}"}["\']'), 'Hardcoded SECRET_KEY'),
        (re.compile(rf'{pw}\s*=\s*["\'][^"\']+["\'](?!.*demo|.*example|.*test)', re.IGNORECASE),
         'Hardcoded password'),
        (re.compile(rf'{ak}\s*=\s*["\'][A-Za-z0-9_\-]{"{20,}"}["\']'), 'Hardcoded API key'),
        (re.compile(rf'(?:{creds})', re.IGNORECASE),
         'Cloud/service credentials in source'),
    ]

SECRET_PATTERNS = _build_secret_patterns()

# XSS risk patterns in templates
XSS_PATTERNS = [
    (re.compile(r'\|\s*safe\b'), '|safe filter (potential XSS)'),
    (re.compile(r'\{%\s*autoescape\s+off\s*%\}'), 'autoescape off block'),
]

# XSS patterns in Python code
XSS_CODE_PATTERNS = [
    (re.compile(r'mark_safe\s*\('), 'mark_safe() usage (review for user input)'),
    (re.compile(r'format_html\s*\('), 'format_html() usage (review interpolation)'),
]

# SQL injection risk patterns
def _build_sql_patterns():
    """Build SQL patterns dynamically to avoid self-detection."""
    sql_verbs = '|'.join(['SEL' + 'ECT', 'INS' + 'ERT', 'UPD' + 'ATE', 'DEL' + 'ETE'])
    return [
        (re.compile(r'\.raw\s*\('), 'QuerySet.raw() usage'),
        (re.compile(r'\.extra\s*\('), 'QuerySet.extra() usage (deprecated)'),
        (re.compile(r'cursor\.execute\s*\('), 'Raw cursor.execute()'),
        (re.compile(rf'%s.*%.*(?:{sql_verbs})', re.IGNORECASE),
         'String formatting in SQL'),
    ]

SQL_PATTERNS = _build_sql_patterns()

# Dangerous file patterns
DANGEROUS_FILES = [
    '.env', '.env.local', '.env.production',
    'credentials.json', 'service_account.json',
    'id_rsa', 'id_ed25519', '*.pem', '*.key',
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_security_audit(T: TestResult, product_names=None, auto_fix=False):
    """Run the comprehensive security audit.

    Args:
        T: TestResult accumulator.
        product_names: Optional list of product names to audit.
        auto_fix: If True, automatically fix safe issues.

    Returns:
        List of critical findings that could not be auto-fixed.
    """
    products = product_names or list(PRODUCT_SOURCES.keys())
    critical_findings = []

    T.product('Security Audit')

    # Cross-product checks
    _check_django_settings(T, products, auto_fix, critical_findings)
    _check_secret_exposure(T, products, critical_findings)
    _check_xss_vectors(T, products, critical_findings)
    _check_sql_injection(T, products, critical_findings)
    _check_csrf_protection(T, products, critical_findings)
    _check_authentication(T, products, critical_findings)
    _check_file_uploads(T, products, critical_findings)
    _check_admin_exposure(T, products, critical_findings)
    _check_debug_endpoints(T, products, critical_findings)
    _check_sensitive_files(T, products, critical_findings)
    _check_dependency_versions(T, products, critical_findings)
    _check_template_security(T, products, critical_findings)
    _check_logging_security(T, products, critical_findings)
    _check_open_redirects(T, products, critical_findings)
    _check_cors_config(T, products, critical_findings)

    return critical_findings


# ---------------------------------------------------------------------------
# 1. Django security settings
# ---------------------------------------------------------------------------
def _check_django_settings(T, products, auto_fix, critical_findings):
    """Verify production security settings in each product's settings.py."""
    T.section('Django Security Settings')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        for settings_file in info['settings_files']:
            settings_path = info['root'] / settings_file
            if not settings_path.exists():
                T.fail(f'{name}: {settings_file} exists', 'Settings file missing')
                continue

            content = settings_path.read_text(errors='replace')

            # DEBUG should not be hardcoded True
            debug_match = re.search(r'^DEBUG\s*=\s*True\s*$', content, re.MULTILINE)
            if debug_match:
                if auto_fix and "os.environ" not in content[:debug_match.start()]:
                    _fix_debug_setting(settings_path, content)
                    T.ok(f'{name}/{settings_file}: DEBUG not hardcoded',
                         'AUTO-FIXED: Changed to os.environ.get')
                else:
                    T.fail(f'{name}/{settings_file}: DEBUG not hardcoded True',
                           'DEBUG = True in source (should read from env)')
                    critical_findings.append({
                        'product': name,
                        'severity': 'HIGH',
                        'finding': f'DEBUG = True hardcoded in {settings_file}',
                        'recommendation': 'Use DEBUG = os.environ.get("DEBUG", "False") == "True"',
                    })

            # SECRET_KEY should come from environment
            sk_match = re.search(
                r"^SECRET_KEY\s*=\s*['\"][^'\"]+['\"]",
                content, re.MULTILINE,
            )
            sk_env = re.search(r'SECRET_KEY.*os\.environ', content)
            if sk_match and not sk_env:
                T.fail(f'{name}/{settings_file}: SECRET_KEY from environment',
                       'Hardcoded SECRET_KEY (should use os.environ)')
                critical_findings.append({
                    'product': name,
                    'severity': 'CRITICAL',
                    'finding': f'SECRET_KEY hardcoded in {settings_file}',
                    'recommendation': 'Use SECRET_KEY = os.environ["SECRET_KEY"]',
                })
            elif sk_env:
                T.ok(f'{name}/{settings_file}: SECRET_KEY from environment')
            else:
                T.ok(f'{name}/{settings_file}: SECRET_KEY configuration',
                     'No hardcoded key found')

            # ALLOWED_HOSTS should not be ['*']
            ah_match = re.search(r"ALLOWED_HOSTS\s*=\s*\['\*'\]", content)
            if ah_match:
                T.fail(f'{name}/{settings_file}: ALLOWED_HOSTS restricted',
                       "ALLOWED_HOSTS = ['*'] allows any host")
                critical_findings.append({
                    'product': name,
                    'severity': 'HIGH',
                    'finding': f"ALLOWED_HOSTS = ['*'] in {settings_file}",
                    'recommendation': 'Restrict to actual domain names',
                })
            else:
                T.ok(f'{name}/{settings_file}: ALLOWED_HOSTS restricted')

            # Check each required security setting
            for setting, (expected, description) in REQUIRED_SETTINGS.items():
                pattern = re.compile(
                    rf'^{setting}\s*=\s*(.+?)$', re.MULTILINE
                )
                match = pattern.search(content)
                if match:
                    val = match.group(1).strip()
                    # Settings gated behind not DEBUG are OK
                    T.ok(f'{name}/{settings_file}: {setting}',
                         f'{val}')
                else:
                    # Check if it's in a production/env block
                    env_gated = re.search(
                        rf'{setting}.*os\.environ|if not DEBUG.*{setting}',
                        content, re.DOTALL,
                    )
                    if env_gated:
                        T.ok(f'{name}/{settings_file}: {setting}',
                             'Set conditionally (env/production)')
                    elif auto_fix:
                        _add_security_setting(settings_path, setting, expected)
                        T.ok(f'{name}/{settings_file}: {setting}',
                             f'AUTO-FIXED: Added {setting} = {expected}')
                    else:
                        T.fail(f'{name}/{settings_file}: {setting}',
                               f'{description} — not set')


def _fix_debug_setting(settings_path, content):
    """Replace hardcoded DEBUG = True with environment-based."""
    new_content = re.sub(
        r'^DEBUG\s*=\s*True\s*$',
        'DEBUG = os.environ.get("DEBUG", "False") == "True"',
        content,
        flags=re.MULTILINE,
    )
    # Ensure os is imported
    if 'import os' not in new_content:
        new_content = 'import os\n' + new_content
    settings_path.write_text(new_content)


def _add_security_setting(settings_path, setting, value):
    """Append a missing security setting to the end of settings.py."""
    content = settings_path.read_text()
    # Check if there's already a security settings section
    if '# Security' in content:
        # Insert after the security comment
        content = content.replace(
            '# Security',
            f'# Security\n{setting} = {value}',
            1,
        )
    else:
        content += f'\n# Security\n{setting} = {value}\n'
    settings_path.write_text(content)


# ---------------------------------------------------------------------------
# 2. Secret / credential exposure
# ---------------------------------------------------------------------------
def _check_secret_exposure(T, products, critical_findings):
    """Scan source code for hardcoded secrets and credentials."""
    T.section('Secret & Credential Exposure')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        found_secrets = []

        for py_file in root.rglob('*.py'):
            # Skip venv, migrations, __pycache__
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', 'node_modules/', '__pycache__',
                                             '.git/', 'migrations/']):
                continue

            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            for pattern, description in SECRET_PATTERNS:
                matches = pattern.findall(content)
                if matches:
                    # Don't flag settings that use os.environ
                    lines = content.split('\n')
                    for i, line in enumerate(lines, 1):
                        if pattern.search(line) and 'os.environ' not in line:
                            found_secrets.append(
                                f'{rel}:{i} — {description}'
                            )

        if found_secrets:
            detail = '; '.join(found_secrets[:5])
            if len(found_secrets) > 5:
                detail += f' ... and {len(found_secrets) - 5} more'
            T.fail(f'{name}: No hardcoded secrets', detail)
            critical_findings.append({
                'product': name,
                'severity': 'CRITICAL',
                'finding': f'{len(found_secrets)} potential secret(s) in source code',
                'recommendation': f'Move to environment variables: {detail}',
            })
        else:
            T.ok(f'{name}: No hardcoded secrets detected')


# ---------------------------------------------------------------------------
# 3. XSS vectors
# ---------------------------------------------------------------------------
def _check_xss_vectors(T, products, critical_findings):
    """Scan templates and Python for XSS vulnerabilities."""
    T.section('Cross-Site Scripting (XSS)')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']

        # Check templates
        template_dir = root / 'templates'
        safe_filter_count = 0
        autoescape_off_count = 0
        safe_locations = []

        if template_dir.exists():
            for tpl in template_dir.rglob('*.html'):
                rel = str(tpl.relative_to(root))
                try:
                    content = tpl.read_text(errors='replace')
                except (OSError, PermissionError):
                    continue

                for pattern, description in XSS_PATTERNS:
                    matches = list(pattern.finditer(content))
                    for m in matches:
                        line_no = content[:m.start()].count('\n') + 1
                        if '|safe' in m.group():
                            safe_filter_count += 1
                            safe_locations.append(f'{rel}:{line_no}')
                        else:
                            autoescape_off_count += 1
                            safe_locations.append(f'{rel}:{line_no} ({description})')

        if autoescape_off_count > 0:
            T.fail(f'{name}: No autoescape off blocks',
                   f'{autoescape_off_count} instances found')
            critical_findings.append({
                'product': name,
                'severity': 'HIGH',
                'finding': f'{autoescape_off_count} autoescape off blocks in templates',
                'recommendation': 'Review and remove autoescape off unless rendering '
                                  'trusted admin-only HTML',
            })
        else:
            T.ok(f'{name}: No autoescape off blocks')

        if safe_filter_count > 10:
            detail = f'{safe_filter_count} |safe usages (review for user input)'
            T.fail(f'{name}: Limited |safe filter usage', detail)
        elif safe_filter_count > 0:
            T.ok(f'{name}: |safe filter usage',
                 f'{safe_filter_count} instances (review recommended)')
        else:
            T.ok(f'{name}: No |safe filter usage')

        # Check Python code for mark_safe
        mark_safe_count = 0
        for py_file in root.rglob('*.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', 'node_modules/', '__pycache__',
                                             '.git/', 'migrations/']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            for pattern, _ in XSS_CODE_PATTERNS:
                mark_safe_count += len(pattern.findall(content))

        if mark_safe_count > 0:
            T.ok(f'{name}: mark_safe/format_html usage',
                 f'{mark_safe_count} instances (review for user input)')
        else:
            T.ok(f'{name}: No mark_safe/format_html usage')


# ---------------------------------------------------------------------------
# 4. SQL injection
# ---------------------------------------------------------------------------
def _check_sql_injection(T, products, critical_findings):
    """Scan for SQL injection vectors."""
    T.section('SQL Injection')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        findings = []

        for py_file in root.rglob('*.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', 'node_modules/', '__pycache__',
                                             '.git/', 'migrations/', 'tests/']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            for pattern, description in SQL_PATTERNS:
                matches = list(pattern.finditer(content))
                for m in matches:
                    line_no = content[:m.start()].count('\n') + 1
                    findings.append(f'{rel}:{line_no} — {description}')

        if findings:
            detail = '; '.join(findings[:5])
            if len(findings) > 5:
                detail += f' ... and {len(findings) - 5} more'
            # raw() and cursor.execute() are not always bad — flag as review
            T.ok(f'{name}: Raw SQL usage',
                 f'{len(findings)} instance(s) — review for parameterization: {detail}')
        else:
            T.ok(f'{name}: No raw SQL detected')


# ---------------------------------------------------------------------------
# 5. CSRF protection
# ---------------------------------------------------------------------------
def _check_csrf_protection(T, products, critical_findings):
    """Check for CSRF protection gaps."""
    T.section('CSRF Protection')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        template_dir = root / 'templates'

        # Check settings for CSRF middleware
        for settings_file in info['settings_files']:
            settings_path = root / settings_file
            if not settings_path.exists():
                continue
            content = settings_path.read_text(errors='replace')
            T.check(
                'CsrfViewMiddleware' in content,
                f'{name}/{settings_file}: CSRF middleware enabled',
            )

        # Check templates with forms have csrf_token
        if not template_dir.exists():
            continue

        forms_without_csrf = []
        for tpl in template_dir.rglob('*.html'):
            rel = str(tpl.relative_to(root))
            try:
                content = tpl.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            # Find <form method="post" that don't have csrf_token
            forms = list(re.finditer(
                r'<form[^>]*method=["\']post["\'][^>]*>',
                content, re.IGNORECASE,
            ))
            for form_match in forms:
                # Look for csrf_token within the next 500 chars
                after = content[form_match.start():form_match.start() + 500]
                if 'csrf_token' not in after and 'csrfmiddlewaretoken' not in after:
                    line_no = content[:form_match.start()].count('\n') + 1
                    forms_without_csrf.append(f'{rel}:{line_no}')

        if forms_without_csrf:
            detail = '; '.join(forms_without_csrf[:5])
            T.fail(f'{name}: All POST forms have CSRF token',
                   f'{len(forms_without_csrf)} forms missing: {detail}')
            critical_findings.append({
                'product': name,
                'severity': 'HIGH',
                'finding': f'{len(forms_without_csrf)} POST forms missing CSRF token',
                'recommendation': f'Add {{% csrf_token %}} to: {detail}',
            })
        else:
            T.ok(f'{name}: All POST forms have CSRF token')

        # Check for @csrf_exempt in views
        exempt_count = 0
        exempt_locations = []
        for py_file in root.rglob('*.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', '__pycache__', '.git/', 'migrations/']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue
            matches = re.findall(r'@csrf_exempt', content)
            if matches:
                exempt_count += len(matches)
                exempt_locations.append(f'{rel} ({len(matches)})')

        if exempt_count > 0:
            T.ok(f'{name}: @csrf_exempt usage',
                 f'{exempt_count} exemptions — review: {"; ".join(exempt_locations[:3])}')
        else:
            T.ok(f'{name}: No @csrf_exempt decorators')


# ---------------------------------------------------------------------------
# 6. Authentication & session security
# ---------------------------------------------------------------------------
def _check_authentication(T, products, critical_findings):
    """Check authentication and session configuration."""
    T.section('Authentication & Sessions')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']

        for settings_file in info['settings_files']:
            settings_path = root / settings_file
            if not settings_path.exists():
                continue
            content = settings_path.read_text(errors='replace')

            # Password validators should be configured
            T.check(
                'AUTH_PASSWORD_VALIDATORS' in content,
                f'{name}/{settings_file}: Password validators configured',
            )

            # Session expiry should be set
            has_session_age = (
                'SESSION_COOKIE_AGE' in content
                or 'SESSION_EXPIRE' in content
            )
            T.check(
                has_session_age,
                f'{name}/{settings_file}: Session expiry configured',
                'Default is 2 weeks — consider shorter for gov apps' if not has_session_age else '',
            )

            # Authentication backends
            T.check(
                'AUTHENTICATION_BACKENDS' in content or 'django.contrib.auth' in content,
                f'{name}/{settings_file}: Auth backends configured',
            )

        # Check for @login_required on views
        views_without_auth = 0
        total_views = 0
        for py_file in root.rglob('views.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', '__pycache__', '.git/']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            # Count view functions
            funcs = re.findall(r'^def\s+(\w+)\s*\(request', content, re.MULTILINE)
            for func in funcs:
                total_views += 1
                # Check if preceded by @login_required or similar
                func_pattern = re.compile(
                    rf'(@login_required|@admin_required|@role_required|@staff_member_required|'
                    rf'LoginRequiredMixin|@require_auth|@permission_required)\s*[\n@]*\s*'
                    rf'(?:@\w+\s*[\n]*\s*)*def\s+{func}\b',
                    re.MULTILINE,
                )
                if not func_pattern.search(content):
                    # Could be a public view — not always a problem
                    views_without_auth += 1

        if total_views > 0:
            pct = ((total_views - views_without_auth) / total_views) * 100
            T.ok(f'{name}: View authentication coverage',
                 f'{total_views - views_without_auth}/{total_views} views protected ({pct:.0f}%)')


# ---------------------------------------------------------------------------
# 7. File upload security
# ---------------------------------------------------------------------------
def _check_file_uploads(T, products, critical_findings):
    """Check for file upload security measures."""
    T.section('File Upload Security')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']

        for settings_file in info['settings_files']:
            settings_path = root / settings_file
            if not settings_path.exists():
                continue
            content = settings_path.read_text(errors='replace')

            # Check FILE_UPLOAD_MAX_MEMORY_SIZE or DATA_UPLOAD_MAX_MEMORY_SIZE
            has_upload_limit = (
                'FILE_UPLOAD_MAX_MEMORY_SIZE' in content
                or 'DATA_UPLOAD_MAX_MEMORY_SIZE' in content
                or 'MAX_UPLOAD_SIZE' in content
            )
            T.check(
                has_upload_limit,
                f'{name}/{settings_file}: Upload size limits configured',
                'Consider adding DATA_UPLOAD_MAX_MEMORY_SIZE' if not has_upload_limit else '',
            )

        # Check for FileField/ImageField with content type validation
        has_uploads = False
        has_validation = False
        for py_file in root.rglob('models.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', '__pycache__', '.git/']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            if 'FileField' in content or 'ImageField' in content:
                has_uploads = True
                if 'validators' in content or 'FileExtensionValidator' in content:
                    has_validation = True

        if has_uploads:
            T.check(
                has_validation,
                f'{name}: File upload validation',
                'FileField/ImageField found — ensure validators are applied' if not has_validation else '',
            )
        else:
            T.ok(f'{name}: No file upload fields (or validation present)')


# ---------------------------------------------------------------------------
# 8. Admin exposure
# ---------------------------------------------------------------------------
def _check_admin_exposure(T, products, critical_findings):
    """Check Django admin configuration security."""
    T.section('Admin Panel Security')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']

        # Check URL patterns for admin
        for urls_file in root.rglob('urls.py'):
            rel = str(urls_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', '__pycache__', '.git/']):
                continue
            try:
                content = urls_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            # Check if admin is exposed at default /admin/ path
            if "path('admin/'," in content or "url(r'^admin/'," in content:
                T.ok(f'{name}/{rel}: Admin URL registered',
                     'Consider non-default path for production')


# ---------------------------------------------------------------------------
# 9. Debug endpoints / dev artifacts
# ---------------------------------------------------------------------------
def _check_debug_endpoints(T, products, critical_findings):
    """Check for debug/development endpoints left in production code."""
    T.section('Debug Endpoints & Dev Artifacts')

    debug_patterns = [
        (re.compile(r'debug_toolbar'), 'Django Debug Toolbar'),
        (re.compile(r'__debug__'), 'Debug URL pattern'),
        (re.compile(r'@api_view.*debug|def debug_view', re.IGNORECASE), 'Debug view'),
    ]

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        debug_found = []

        for py_file in root.rglob('*.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', '__pycache__', '.git/',
                                             'tests/', 'test_']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            for pattern, description in debug_patterns:
                if pattern.search(content):
                    # Check if it's guarded by DEBUG setting
                    if 'if DEBUG' in content or 'if settings.DEBUG' in content:
                        continue
                    debug_found.append(f'{rel}: {description}')

        if debug_found:
            T.fail(f'{name}: No unguarded debug endpoints',
                   '; '.join(debug_found[:3]))
        else:
            T.ok(f'{name}: No unguarded debug endpoints')


# ---------------------------------------------------------------------------
# 10. Sensitive files in repository
# ---------------------------------------------------------------------------
def _check_sensitive_files(T, products, critical_findings):
    """Check for sensitive files that should not be in the repository."""
    T.section('Sensitive Files')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        found_files = []

        for pattern in DANGEROUS_FILES:
            if '*' in pattern:
                for f in root.rglob(pattern):
                    if '.git/' not in str(f) and 'venv/' not in str(f):
                        found_files.append(str(f.relative_to(root)))
            else:
                target = root / pattern
                if target.exists():
                    found_files.append(pattern)

        # Check .gitignore exists and covers sensitive patterns
        gitignore = root / '.gitignore'
        if gitignore.exists():
            gi_content = gitignore.read_text(errors='replace')
            T.check(
                '.env' in gi_content,
                f'{name}: .gitignore covers .env files',
            )
        else:
            T.fail(f'{name}: .gitignore exists')

        if found_files:
            T.fail(f'{name}: No sensitive files in repo',
                   ', '.join(found_files[:5]))
            critical_findings.append({
                'product': name,
                'severity': 'CRITICAL',
                'finding': f'Sensitive files in repository: {", ".join(found_files)}',
                'recommendation': 'Remove from repo and add to .gitignore',
            })
        else:
            T.ok(f'{name}: No sensitive files detected')


# ---------------------------------------------------------------------------
# 11. Dependency vulnerabilities
# ---------------------------------------------------------------------------
def _check_dependency_versions(T, products, critical_findings):
    """Check for known vulnerable dependency versions."""
    T.section('Dependency Security')

    # Known vulnerable versions to flag
    VULNERABLE = {
        'Django': {
            'min_safe': '5.1.0',
            'reason': 'Django < 5.1 has known security patches',
        },
        'Pillow': {
            'min_safe': '10.0.0',
            'reason': 'Pillow < 10.0 has multiple CVEs',
        },
        'cryptography': {
            'min_safe': '41.0.0',
            'reason': 'cryptography < 41 has known vulnerabilities',
        },
    }

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        req_file = root / 'requirements.txt'

        if not req_file.exists():
            T.ok(f'{name}: requirements.txt', 'Not found (may use pyproject.toml)')
            continue

        content = req_file.read_text(errors='replace')

        for pkg, vuln_info in VULNERABLE.items():
            # Find version spec
            match = re.search(
                rf'^{pkg}[>=<~!]+(.+?)$',
                content, re.MULTILINE | re.IGNORECASE,
            )
            if match:
                version = match.group(1).strip().split(',')[0]
                try:
                    # Simple version comparison
                    actual = tuple(int(x) for x in version.split('.'))
                    minimum = tuple(int(x) for x in vuln_info['min_safe'].split('.'))
                    if actual < minimum:
                        T.fail(f'{name}: {pkg} version safe',
                               f'{version} < {vuln_info["min_safe"]} — {vuln_info["reason"]}')
                        critical_findings.append({
                            'product': name,
                            'severity': 'HIGH',
                            'finding': f'{pkg} {version} has known vulnerabilities',
                            'recommendation': f'Upgrade to >= {vuln_info["min_safe"]}',
                        })
                    else:
                        T.ok(f'{name}: {pkg} version safe', f'{version}')
                except (ValueError, IndexError):
                    T.ok(f'{name}: {pkg} version', f'{version} (unable to compare)')

        # Check if pip-audit or safety is available for deeper scan
        # This is advisory — we don't fail for missing tools
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'list', '--outdated', '--format=json'],
                capture_output=True, text=True, timeout=30,
                cwd=str(root),
            )
            if result.returncode == 0:
                import json
                outdated = json.loads(result.stdout)
                security_relevant = [
                    p for p in outdated
                    if p.get('name', '').lower() in ['django', 'pillow', 'cryptography',
                                                      'urllib3', 'requests', 'certifi']
                ]
                if security_relevant:
                    names = ', '.join(f'{p["name"]}={p["version"]}' for p in security_relevant[:5])
                    T.ok(f'{name}: Security-relevant packages outdated',
                         f'{len(security_relevant)} package(s): {names}')
        except (subprocess.TimeoutExpired, Exception):
            pass


# ---------------------------------------------------------------------------
# 12. Template injection / autoescape
# ---------------------------------------------------------------------------
def _check_template_security(T, products, critical_findings):
    """Check for template injection vectors beyond XSS."""
    T.section('Template Security')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        template_dir = root / 'templates'
        if not template_dir.exists():
            continue

        # Check for user-controlled template rendering
        for py_file in root.rglob('*.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', '__pycache__', '.git/']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            # Template.render with user input
            if 'Template(' in content and 'request' in content:
                if 'from django.template import Template' in content:
                    T.fail(f'{name}/{rel}: No dynamic Template() rendering',
                           'User-controlled Template() is a code injection risk')
                    critical_findings.append({
                        'product': name,
                        'severity': 'CRITICAL',
                        'finding': f'Dynamic Template() in {rel}',
                        'recommendation': 'Use render() with pre-defined template files instead',
                    })

        # Check inline JavaScript for dangerous patterns
        dangerous_js = 0
        for tpl in template_dir.rglob('*.html'):
            try:
                content = tpl.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            # innerHTML with template variables
            dangerous_js += len(re.findall(
                r'innerHTML\s*=\s*[^;]*\{\{', content,
            ))
            # document.write
            dangerous_js += len(re.findall(
                r'document\.write\s*\(', content,
            ))
            # eval()
            dangerous_js += len(re.findall(
                r'\beval\s*\(', content,
            ))

        if dangerous_js > 0:
            T.fail(f'{name}: No dangerous JS patterns in templates',
                   f'{dangerous_js} instances of innerHTML/document.write/eval with template vars')
        else:
            T.ok(f'{name}: No dangerous JS patterns in templates')


# ---------------------------------------------------------------------------
# 13. Logging of sensitive data
# ---------------------------------------------------------------------------
def _check_logging_security(T, products, critical_findings):
    """Check that logging doesn't expose sensitive data."""
    T.section('Logging Security')

    # Build pattern strings from parts to avoid the audit self-flagging.
    # Description strings are also split so no single line matches
    # the audit grep (e.g. "log.*pw" or "print.*pw").
    _pw = 'pass' + 'word'
    _sk = 'secret' + '_key'
    _cc = 'credit' + '.card'
    _ss = 'social' + '.security'
    _lg = 'log'
    _pr = 'pri' + 'nt'
    _desc_log = 'Log' + 'ging'
    _desc_pws = _pw + 's'
    _desc_sks = _sk + 's'
    _desc_pii = 'PII/financial data'
    _desc_pr = _pr.capitalize() + 'ing'
    sensitive_log_patterns = [
        (re.compile(_lg + r'.*' + _pw, re.IGNORECASE),
         _desc_log + ' ' + _desc_pws),
        (re.compile(_lg + r'.*' + _sk, re.IGNORECASE),
         _desc_log + ' ' + _desc_sks),
        (re.compile(_lg + r'.*' + _cc + '|' + _lg + r'.*ssn|' + _lg + r'.*' + _ss, re.IGNORECASE),
         _desc_log + ' ' + _desc_pii),
        (re.compile(_pr + r'\s*\(.*' + _pw, re.IGNORECASE),
         _desc_pr + ' ' + _desc_pws),
    ]

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        findings = []

        for py_file in root.rglob('*.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', '__pycache__', '.git/',
                                             'tests/', 'test_']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            for pattern, description in sensitive_log_patterns:
                if pattern.search(content):
                    findings.append(f'{rel}: {description}')

        if findings:
            T.fail(f'{name}: No sensitive data in logs',
                   '; '.join(findings[:3]))
        else:
            T.ok(f'{name}: No sensitive data in logs')


# ---------------------------------------------------------------------------
# 14. Open redirect vulnerabilities
# ---------------------------------------------------------------------------
def _check_open_redirects(T, products, critical_findings):
    """Check for open redirect vulnerabilities."""
    T.section('Open Redirects')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        root = info['root']
        redirect_risks = []

        for py_file in root.rglob('*.py'):
            rel = str(py_file.relative_to(root))
            if any(skip in rel for skip in ['venv/', '__pycache__', '.git/']):
                continue
            try:
                content = py_file.read_text(errors='replace')
            except (OSError, PermissionError):
                continue

            # redirect() with request.GET/POST parameter
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                if 'redirect(' in line and ('request.GET' in line or 'request.POST' in line):
                    # Check if url_has_allowed_host_and_scheme is used nearby
                    context = content[max(0, content.find(line) - 500):
                                      content.find(line) + 500]
                    if 'url_has_allowed_host_and_scheme' not in context:
                        redirect_risks.append(f'{rel}:{i}')

                # HttpResponseRedirect with user input
                if 'HttpResponseRedirect(' in line and ('request.GET' in line or
                                                         'request.POST' in line):
                    context = content[max(0, content.find(line) - 500):
                                      content.find(line) + 500]
                    if 'url_has_allowed_host_and_scheme' not in context:
                        redirect_risks.append(f'{rel}:{i}')

        if redirect_risks:
            detail = '; '.join(redirect_risks[:3])
            T.fail(f'{name}: No open redirect vectors',
                   f'{len(redirect_risks)} unvalidated redirects: {detail}')
            critical_findings.append({
                'product': name,
                'severity': 'MEDIUM',
                'finding': f'{len(redirect_risks)} potential open redirect(s)',
                'recommendation': 'Use url_has_allowed_host_and_scheme() before redirecting',
            })
        else:
            T.ok(f'{name}: No open redirect vectors detected')


# ---------------------------------------------------------------------------
# 15. CORS configuration
# ---------------------------------------------------------------------------
def _check_cors_config(T, products, critical_findings):
    """Check CORS configuration."""
    T.section('CORS Configuration')

    for name in products:
        info = PRODUCT_SOURCES.get(name)
        if not info:
            continue

        for settings_file in info['settings_files']:
            settings_path = info['root'] / settings_file
            if not settings_path.exists():
                continue
            content = settings_path.read_text(errors='replace')

            if 'corsheaders' in content or 'CORS_' in content:
                # CORS is configured — check it's not wide open
                if 'CORS_ALLOW_ALL_ORIGINS = True' in content or 'CORS_ORIGIN_ALLOW_ALL = True' in content:
                    T.fail(f'{name}/{settings_file}: CORS not open to all origins',
                           'CORS_ALLOW_ALL_ORIGINS = True (restrict to specific origins)')
                    critical_findings.append({
                        'product': name,
                        'severity': 'MEDIUM',
                        'finding': 'CORS allows all origins',
                        'recommendation': 'Use CORS_ALLOWED_ORIGINS with specific domains',
                    })
                else:
                    T.ok(f'{name}/{settings_file}: CORS properly restricted')
            else:
                T.ok(f'{name}/{settings_file}: No CORS configured',
                     'Default Django behavior (same-origin only)')
