"""UI consistency audit across all DockLabs products.

Scans templates, CSS, JS, and static assets across all nine products to detect
drift from the shared design system in:

- CDN/library versions (Bootstrap, htmx, Bootstrap Icons)
- CSS custom properties and the v3 "Civic Institution" token palette
- Layout contract (blocks, shared CSS/JS, Bootstrap, a11y landmarks)
- Component patterns (Bootstrap 3/4 remnants)
- Accessibility patterns (skip links, viewport, lang, focus styles)
- Font stack and typography consistency
- Responsive breakpoints
- Print stylesheet coverage
- Icon library usage
- Hard-coded colors vs design tokens

Two structural rules keep this honest, both learned the hard way:

1. **Follow ``{% extends %}``.** Every product's ``base.html`` inherits from
   ``keel/layouts/app.html``, which supplies the blocks, Bootstrap, the shared
   CSS/JS, the skip link, the viewport tag and the lang attribute. Grepping a
   product's ``base.html`` in isolation reports the shared layout working as
   designed as if it were 28 defects. Assertions run against the *resolved
   chain*, so a product that genuinely ships a bare base is still caught.

2. **Assert what CLAUDE.md actually mandates.** This audit previously pinned
   Poppins, Arial and the pre-v2 ``--ct-*`` hex palette — the exact design
   system the suite deliberately migrated off in v0.56.3. A rule that fails
   when the code is right is worse than no rule: it trains people to ignore
   the report. See keel#65.

Reports both PASS/FAIL checks and advisory recommendations.

Usage:
    python -m keel.testing --ui-only
    python -m keel.testing  # (includes UI audit automatically)
"""
import re
from pathlib import Path

from .config import BASE_DIR
from .result import TestResult

# ---------------------------------------------------------------------------
# Shared design system — the source of truth lives in keel, not in products
# ---------------------------------------------------------------------------
KEEL_ROOT = BASE_DIR / 'keel' / 'keel'
KEEL_TEMPLATE_ROOT = KEEL_ROOT / 'core' / 'templates'
SHARED_LAYOUT = KEEL_TEMPLATE_ROOT / 'keel' / 'layouts' / 'app.html'
SHARED_CSS = KEEL_ROOT / 'core' / 'static' / 'css' / 'docklabs-v2.css'
SHARED_JS = KEEL_ROOT / 'core' / 'static' / 'js' / 'docklabs-v2.js'

# ---------------------------------------------------------------------------
# Canonical design tokens — the "source of truth" from docklabs-v2.css
# ---------------------------------------------------------------------------
CANONICAL = {
    'bootstrap_css': '5.3.3',
    'bootstrap_js': '5.3.3',
    'bootstrap_icons': '1.11.3',
    'htmx_min': '2.0.0',
    # v3 "Civic Institution" editorial stack. Self-hosted WOFF2, declared via
    # @font-face in docklabs-v2.css and exposed as the three vars below. Never
    # hardcode a family — always reference the var (CLAUDE.md, Typography).
    'fonts': {
        '--font-display': 'Fraunces',        # serif display / headings
        '--font-sans': 'Instrument Sans',    # body
        '--font-mono': 'JetBrains Mono',     # data / labels / eyebrows
    },
    # The v3 palette. Values read from docklabs-v2.css :root — this is the
    # subset that carries meaning (brand, surface, text, semantic), not every
    # one of the 78 declared vars.
    'colors': {
        '--ct-blue': '#0A2B4E',
        '--ct-blue-hover': '#12395F',
        '--brass': '#B8860B',
        '--brass-soft': '#F5EAD0',
        '--brass-text': '#7A5A07',
        '--bg-page': '#FAF7F2',
        '--bg-sidebar': '#FCFAF5',
        '--bg-card': '#FFFFFF',
        '--bg-hover': '#F1ECE2',
        '--bg-warm': '#F7F3EA',
        '--border': '#E8E3D9',
        '--border-light': '#F0EDE8',
        '--border-strong': '#D8D2C4',
        '--text-primary': '#1A1A1A',
        '--text-secondary': '#5B5348',
        '--text-tertiary': '#8A8275',
        '--success': '#2D5F3F',
        '--warning': '#B8860B',
        '--error': '#8B2E2A',
        '--info': '#2C5F8D',
    },
}

# Brand hexes that should be referenced through a token, never inlined.
BRAND_HEX_RE = re.compile(
    r'#0A2B4E|#12395F|#B8860B|#FAF7F2|#2D5F3F|#8B2E2A|#2C5F8D',
    re.IGNORECASE,
)
TOKEN_REF_RE = re.compile(r'var\(\s*--[a-z0-9-]+', re.IGNORECASE)

# Products and their template/static roots. Every DockLabs product is its own
# repo — Admiralty and Manifest are NOT sub-products of Beacon and Harbor. That
# assumption made this audit read stale, git-tracked legacy copies at
# beacon/templates/admiralty/base.html and harbor/templates/manifest/base.html
# instead of the real thing. Same root cause as keel#63.
PRODUCT_ROOTS = {
    name: {
        'templates': BASE_DIR / repo / 'templates',
        'static': BASE_DIR / repo / 'static',
        'base_templates': ['base.html'],
    }
    for name, repo in (
        ('Admiralty', 'admiralty'),
        ('Beacon', 'beacon'),
        ('Bounty', 'bounty'),
        ('Harbor', 'harbor'),
        ('Helm', 'helm'),
        ('Lookout', 'lookout'),
        ('Manifest', 'manifest'),
        ('Purser', 'purser'),
        ('Yeoman', 'yeoman'),
    )
}

# The contract an authenticated page must satisfy. Products inherit all of it
# from keel/layouts/app.html; it is asserted against the *resolved* extends
# chain, so a product that stops extending the shared layout without
# reproducing the contract still fails.
LAYOUT_CONTRACT = {
    'block_content': (r'\{%\s*block\s+content\b', '{% block content %}'),
    'block_title': (r'\{%\s*block\s+title\b', '{% block title %}'),
    'block_extra_css': (r'\{%\s*block\s+extra_css\b', '{% block extra_css %}'),
    'block_extra_js': (r'\{%\s*block\s+extra_js\b', '{% block extra_js %}'),
    'shared_css': (r'docklabs-v2\.css', 'shared docklabs-v2.css'),
    'shared_js': (r'docklabs-v2\.js', 'shared docklabs-v2.js'),
    'bootstrap': (r'bootstrap@[\d.]+/dist/css/bootstrap', 'Bootstrap CSS'),
    'bootstrap_icons': (r'bootstrap-icons@[\d.]+', 'Bootstrap Icons'),
}

# Required accessibility elements — same inheritance story as LAYOUT_CONTRACT.
A11Y_CHECKS = {
    'skip_link': (r'skip.*content|visually-hidden-focusable', 'Skip-to-content link'),
    'meta_viewport': (r'name=["\']viewport["\']', 'Viewport meta tag'),
    'lang_attr': (r'<html[^>]*lang=', 'HTML lang attribute'),
}

# Regex patterns for extracting version info
CDN_PATTERNS = {
    'bootstrap_css': re.compile(r'bootstrap@([\d.]+)/dist/css/bootstrap'),
    'bootstrap_js': re.compile(r'bootstrap@([\d.]+)/dist/js/bootstrap'),
    'bootstrap_icons': re.compile(r'bootstrap-icons@([\d.]+)'),
    'htmx': re.compile(r'htmx\.org@([\d.]+)'),
}

# Hard-coded color patterns that should use CSS variables instead
HARDCODED_COLOR_RE = re.compile(
    r'(?:color|background(?:-color)?|border(?:-color)?|fill|stroke)\s*:\s*'
    r'(#[0-9a-fA-F]{3,8})',
)

# Known product-specific colors that are OK to hard-code
PRODUCT_SPECIFIC_COLORS = {
    # Beacon FOIA zones
    '#16a34a', '#2563eb', '#d97706', '#f97316',
    # Lookout bill status scoring
    # Harbor signatures
}

# Poppins is retained *intentionally* on the public/marketing layout and the
# HTML email templates (CLAUDE.md, Typography). Product CSS that styles those
# surfaces is therefore exempt from the "headings use var(--font-display)" rule.
PUBLIC_SURFACE_SELECTORS = ('hero-section', 'stats-bar', 'landing-section')

# A heading rule and the font-family it declares, with the selector captured so
# public/marketing surfaces can be exempted.
HEADING_FONT_RE = re.compile(
    r'([^{}]*\bh[1-6]\b[^{}]*)\{([^}]*?font-family\s*:\s*([^;]+);)',
    re.DOTALL,
)

EXTENDS_RE = re.compile(r'\{%\s*extends\s+["\']([^"\']+)["\']\s*%\}')


# ---------------------------------------------------------------------------
# Template inheritance
# ---------------------------------------------------------------------------
def _find_template(name, search_roots):
    """Resolve a Django template name against an ordered list of roots."""
    for root in search_roots:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def _resolve_chain(path, search_roots):
    """Return every template in ``path``'s ``{% extends %}`` chain.

    Products' base.html is a thin override of ``keel/layouts/app.html``; the
    markup that satisfies the layout contract lives in the parent. Asserting
    against the leaf alone reports the shared layout doing its job as a defect.
    """
    chain = []
    seen = set()
    current = path
    while current is not None and current.exists() and current not in seen:
        seen.add(current)
        chain.append(current)
        match = EXTENDS_RE.search(current.read_text(errors='replace'))
        if not match:
            break
        current = _find_template(match.group(1), search_roots)
    return chain


def _chain_content(path, search_roots):
    """Concatenated source of ``path`` and everything it extends."""
    return '\n'.join(
        p.read_text(errors='replace') for p in _resolve_chain(path, search_roots)
    )


def _search_roots(info):
    """Template search path for a product: its own templates, then keel's."""
    return [info['templates'], KEEL_TEMPLATE_ROOT]


def _iter_base_templates(products):
    """Yield (name, info, base_name, path, resolved_content) per base template."""
    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue
        for base_name in info['base_templates']:
            base_path = info['templates'] / base_name
            if not base_path.exists():
                continue
            yield (
                name, info, base_name, base_path,
                _chain_content(base_path, _search_roots(info)),
            )


def _class_token_re(token):
    """Match ``token`` as a standalone class name, not as a substring.

    ``class="[^"]*\\bpanel\\b`` matches ``sig-panel`` and ``wizard-panel``
    because ``-`` is a word boundary — which is how Harbor's two product-specific
    panel classes got reported as Bootstrap 3 remnants. Require the token to
    *start* at a class-name boundary, while still catching real BS3 subclasses
    like ``panel-heading``.
    """
    return re.compile(
        r'class="[^"]*(?<![\w-])' + re.escape(token) + r'(?![\w])',
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def run_ui_audit(T: TestResult, product_names=None):
    """Run the full UI consistency audit.

    Args:
        T: TestResult accumulator.
        product_names: Optional list; defaults to all products.
    """
    products = product_names or list(PRODUCT_ROOTS.keys())

    T.product('UI Audit')

    _check_shared_layout(T)
    _check_cdn_versions(T, products)
    _check_css_variables(T, products)
    _check_template_structure(T, products)
    _check_accessibility(T, products)
    _check_typography(T, products)
    _check_icon_usage(T, products)
    _check_hardcoded_colors(T, products)
    _check_component_patterns(T, products)
    _check_responsive_patterns(T, products)
    _check_print_styles(T, products)
    _check_js_patterns(T, products)


# ---------------------------------------------------------------------------
# Shared layout — the contract lives here now, so check it here
# ---------------------------------------------------------------------------
def _check_shared_layout(T):
    """Assert keel's own app layout satisfies the contract it promises."""
    T.section('Shared Layout')

    if not SHARED_LAYOUT.exists():
        T.fail('Shared app layout exists', str(SHARED_LAYOUT))
        return
    T.ok('Shared app layout exists')

    content = SHARED_LAYOUT.read_text(errors='replace')

    for _key, (pattern, description) in LAYOUT_CONTRACT.items():
        T.check(
            bool(re.search(pattern, content)),
            f'keel/layouts/app.html provides {description}',
        )

    for _key, (pattern, description) in A11Y_CHECKS.items():
        T.check(
            bool(re.search(pattern, content, re.IGNORECASE)),
            f'keel/layouts/app.html provides {description}',
        )

    # v3 fonts are self-hosted; the layout preloads the latin subsets so the
    # first paint isn't a FOUT. Poppins must not come back to app chrome.
    T.check(
        'fraunces' in content.lower() and 'instrument-sans' in content.lower(),
        'keel/layouts/app.html preloads self-hosted v3 fonts',
    )

    T.check(SHARED_CSS.exists(), 'Shared docklabs-v2.css exists')
    T.check(SHARED_JS.exists(), 'Shared docklabs-v2.js exists')


# ---------------------------------------------------------------------------
# CDN & library version consistency
# ---------------------------------------------------------------------------
def _check_cdn_versions(T, products):
    """Verify all products use the same CDN library versions."""
    T.section('CDN & Library Versions')

    versions = {}  # {library: {product: version}}

    for name, _info, base_name, _path, content in _iter_base_templates(products):
        for lib, pattern in CDN_PATTERNS.items():
            match = pattern.search(content)
            if match:
                versions.setdefault(lib, {})[f'{name}/{base_name}'] = match.group(1)

    # Check each library for version consistency
    for lib, product_versions in versions.items():
        unique_versions = set(product_versions.values())
        if len(unique_versions) == 1:
            ver = unique_versions.pop()
            canonical = CANONICAL.get(lib, '')
            # Previously `ver not in canonical`, which is backwards: it asked
            # whether the found version contains the canonical string, so an
            # exact match on a longer string always failed.
            if canonical and canonical not in ver:
                T.fail(
                    f'{lib} version matches canonical',
                    f'Found {ver}, expected {canonical}',
                )
            else:
                T.ok(f'{lib} version consistent', f'All products use {ver}')
        else:
            details = ', '.join(f'{p}: {v}' for p, v in product_versions.items())
            T.fail(f'{lib} version consistent', f'Mismatch: {details}')

    # Check htmx specifically — it may appear in base templates
    htmx_versions = versions.get('htmx', {})
    for product_tpl, ver in htmx_versions.items():
        # Compare major.minor against minimum
        try:
            parts = [int(x) for x in ver.split('.')]
            canonical_parts = [int(x) for x in CANONICAL['htmx_min'].split('.')]
            if parts[:2] >= canonical_parts[:2]:
                T.ok(f'htmx version adequate ({product_tpl})', f'v{ver}')
            else:
                T.fail(
                    f'htmx version adequate ({product_tpl})',
                    f'v{ver} < minimum v{CANONICAL["htmx_min"]}',
                )
        except (ValueError, IndexError):
            T.fail(f'htmx version parseable ({product_tpl})', f'Got: {ver}')


# ---------------------------------------------------------------------------
# CSS custom properties (design tokens)
# ---------------------------------------------------------------------------
def _check_css_variables(T, products):
    """Verify shared CSS variables are defined and used consistently."""
    T.section('CSS Design Tokens')

    if not SHARED_CSS.exists():
        T.fail('Shared docklabs-v2.css exists', str(SHARED_CSS))
        return

    shared_content = SHARED_CSS.read_text(errors='replace')

    for var_name, expected_value in CANONICAL['colors'].items():
        pattern = re.compile(re.escape(var_name) + r'\s*:\s*([^;]+);')
        match = pattern.search(shared_content)
        if match:
            actual = match.group(1).strip().upper()
            expected = expected_value.upper()
            T.check(
                actual == expected,
                f'{var_name} defined correctly',
                f'Expected {expected}, got {actual}' if actual != expected else '',
            )
        else:
            T.fail(f'{var_name} defined in docklabs-v2.css')

    for var_name, family in CANONICAL['fonts'].items():
        pattern = re.compile(re.escape(var_name) + r'\s*:\s*([^;]+);')
        match = pattern.search(shared_content)
        if match:
            T.check(
                family.lower() in match.group(1).lower(),
                f'{var_name} resolves to {family}',
                f'Got: {match.group(1).strip()}' if family.lower() not in match.group(1).lower() else '',
            )
        else:
            T.fail(f'{var_name} defined in docklabs-v2.css')

    # Check each product's CSS uses variables, not raw hex for brand colors
    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        css_dir = info['static'] / 'css'
        if not css_dir.exists():
            continue

        for css_file in sorted(css_dir.glob('*.css')):
            content = css_file.read_text(errors='replace')
            var_refs = TOKEN_REF_RE.findall(content)
            raw_brand = BRAND_HEX_RE.findall(content)

            if raw_brand and not var_refs:
                T.fail(
                    f'{name}/{css_file.name} uses CSS variables',
                    f'Found {len(raw_brand)} hard-coded brand colors, 0 var() references',
                )
            elif raw_brand:
                T.ok(
                    f'{name}/{css_file.name} uses CSS variables',
                    f'{len(var_refs)} var() refs, {len(raw_brand)} hard-coded (review)',
                )
            else:
                T.ok(f'{name}/{css_file.name} uses CSS variables')


# ---------------------------------------------------------------------------
# Template structure consistency
# ---------------------------------------------------------------------------
def _check_template_structure(T, products):
    """Verify each product's base template satisfies the layout contract.

    Asserted against the resolved ``{% extends %}`` chain — a product inheriting
    the contract from ``keel/layouts/app.html`` passes without repeating it,
    which is the entire point of the shared layout.
    """
    T.section('Template Structure')

    for name, info, base_name, base_path, content in _iter_base_templates(products):
        chain = _resolve_chain(base_path, _search_roots(info))
        extends_shared = SHARED_LAYOUT in chain

        T.check(
            extends_shared,
            f'{name}/{base_name} extends the shared keel layout',
            '' if extends_shared else 'Does not resolve to keel/layouts/app.html',
        )

        for _key, (pattern, description) in LAYOUT_CONTRACT.items():
            T.check(
                bool(re.search(pattern, content)),
                f'{name}/{base_name} provides {description}',
                '' if extends_shared else 'Not inherited and not defined locally',
            )


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------
def _check_accessibility(T, products):
    """Check for WCAG 2.1 AA compliance patterns in base templates."""
    T.section('Accessibility')

    for name, info, base_name, _path, content in _iter_base_templates(products):
        for _check_id, (pattern, description) in A11Y_CHECKS.items():
            T.check(
                bool(re.search(pattern, content, re.IGNORECASE)),
                f'{name}/{base_name}: {description}',
            )

        # Check for focus styles in CSS
        css_dir = info['static'] / 'css'
        all_css = ''
        if css_dir.exists():
            for css_file in sorted(css_dir.glob('*.css')):
                all_css += css_file.read_text(errors='replace')
        if SHARED_CSS.exists():
            all_css += SHARED_CSS.read_text(errors='replace')

        T.check(
            ':focus-visible' in all_css or ':focus' in all_css,
            f'{name}: Custom focus styles defined',
        )


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
def _check_typography(T, products):
    """Verify the v3 editorial stack, and that nothing hardcodes a family.

    The old rule asserted ``Poppins`` was loaded. v0.56.3 removed Poppins from
    authenticated chrome in favour of self-hosted Fraunces / Instrument Sans /
    JetBrains Mono, so that rule failed precisely when a product was correct.
    Assert the inverse: app chrome must be free of Poppins, and heading rules
    must reference ``var(--font-display)`` rather than naming a family.
    """
    T.section('Typography')

    for name, _info, base_name, _path, content in _iter_base_templates(products):
        # Poppins survives only on public.html + email templates. base.html is
        # the authenticated base by convention (CLAUDE.md, UI & Frontend).
        has_poppins = 'poppins' in content.lower()
        T.check(
            not has_poppins,
            f'{name}/{base_name}: authenticated chrome free of Poppins',
            'Poppins was removed from app chrome in v0.56.3' if has_poppins else '',
        )
        uses_google_fonts = 'fonts.googleapis.com' in content
        T.check(
            not uses_google_fonts,
            f'{name}/{base_name}: fonts self-hosted, not from Google Fonts',
            'v3 fonts ship as WOFF2 via docklabs-v2.css' if uses_google_fonts else '',
        )

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        css_dir = info['static'] / 'css'
        if not css_dir.exists():
            continue

        for css_file in sorted(css_dir.glob('*.css')):
            content = css_file.read_text(errors='replace')

            offenders = []
            for match in HEADING_FONT_RE.finditer(content):
                selector, _body, family = match.groups()
                if any(s in selector for s in PUBLIC_SURFACE_SELECTORS):
                    continue  # public/marketing surface — Poppins is intentional
                if 'var(--font-' in family:
                    continue  # references the shared token, which is the rule
                offenders.append(family.strip())

            if offenders:
                T.fail(
                    f'{name}/{css_file.name}: Heading fonts use var(--font-display)',
                    f'{len(offenders)} heading rule(s) hardcode a family: '
                    f'{"; ".join(sorted(set(offenders))[:3])}',
                )
            else:
                T.ok(f'{name}/{css_file.name}: Heading fonts use var(--font-display)')


# ---------------------------------------------------------------------------
# Icon usage
# ---------------------------------------------------------------------------
def _check_icon_usage(T, products):
    """Check for consistent icon library usage."""
    T.section('Icon Library')

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info or not info['templates'].exists():
            continue

        template_dir = info['templates']
        font_awesome_count = 0
        bootstrap_icon_count = 0
        material_icon_count = 0

        for tpl_path in template_dir.rglob('*.html'):
            content = tpl_path.read_text(errors='replace')
            font_awesome_count += len(re.findall(r'class="[^"]*fa[srb]?\s+fa-', content))
            bootstrap_icon_count += len(re.findall(r'class="[^"]*bi\s+bi-', content))
            material_icon_count += len(re.findall(r'class="[^"]*material-icons', content))

        T.check(
            font_awesome_count == 0,
            f'{name}: No Font Awesome icons (use Bootstrap Icons)',
            f'Found {font_awesome_count} Font Awesome references' if font_awesome_count else '',
        )
        T.check(
            material_icon_count == 0,
            f'{name}: No Material Icons (use Bootstrap Icons)',
            f'Found {material_icon_count} Material Icons references' if material_icon_count else '',
        )
        if bootstrap_icon_count > 0:
            T.ok(f'{name}: Uses Bootstrap Icons', f'{bootstrap_icon_count} icon references')


# ---------------------------------------------------------------------------
# Hard-coded colors
# ---------------------------------------------------------------------------
def _check_hardcoded_colors(T, products):
    """Detect hard-coded hex colors in CSS that should use design tokens."""
    T.section('Color Token Usage')

    # Build a set of canonical hex values (case-insensitive)
    canonical_hex = {v.upper() for v in CANONICAL['colors'].values()}
    # Bootstrap defaults we don't flag
    bootstrap_colors = {
        '#FFFFFF', '#000000', '#FFF', '#000', '#212529', '#6C757D',
        '#198754', '#DC3545', '#FFC107', '#0D6EFD', '#0DCAF0',
        '#F8F9FA', '#E9ECEF', '#DEE2E6', '#CED4DA', '#ADB5C7',
        '#6C757D', '#495057', '#343A40', '#212529',
        '#DDD', '#CCC', '#EEE', '#333', '#666', '#999',
    }

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        css_dir = info['static'] / 'css'
        if not css_dir.exists():
            continue

        for css_file in sorted(css_dir.glob('*.css')):
            content = css_file.read_text(errors='replace')
            matches = HARDCODED_COLOR_RE.findall(content)

            non_standard = []
            for hex_color in matches:
                upper = hex_color.upper()
                if upper not in canonical_hex and upper not in bootstrap_colors and upper not in PRODUCT_SPECIFIC_COLORS:
                    non_standard.append(hex_color)

            if non_standard:
                unique = set(non_standard)
                T.fail(
                    f'{name}/{css_file.name}: Hard-coded colors use tokens',
                    f'{len(unique)} non-standard colors: {", ".join(sorted(unique)[:5])}{"..." if len(unique) > 5 else ""}',
                )
            else:
                T.ok(f'{name}/{css_file.name}: Colors use tokens or standard palette')


# ---------------------------------------------------------------------------
# Component patterns
# ---------------------------------------------------------------------------
def _check_component_patterns(T, products):
    """Flag Bootstrap 3/4 markup remnants.

    The old "all products use the navbar / breadcrumb / form_control / badge
    pattern" checks are gone. They grepped each product's templates for a class
    name and failed any product that didn't use it — but the suite is on a
    shared *sidebar* layout (so no product has a navbar of its own), Lookout
    applies ``form-control`` via widget attrs in forms.py rather than in markup,
    and Harbor's only "badge" hits are a comment, a CSS selector and a JS query.
    A vocabulary grep can't tell "styled elsewhere" from "broken", so the rule
    had no true-positive mode.
    """
    T.section('Component Patterns')

    bs_remnants = {
        'btn-default': _class_token_re('btn-default'),
        'panel': _class_token_re('panel'),
        'well': _class_token_re('well'),
        'label-': re.compile(r'class="[^"]*(?<![\w-])label-(primary|success|danger|warning|info)'),
    }

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info or not info['templates'].exists():
            continue

        flagged = False
        for tpl_path in sorted(info['templates'].rglob('*.html')):
            content = tpl_path.read_text(errors='replace')
            rel = tpl_path.relative_to(info['templates'])

            for bs_name, bs_pat in bs_remnants.items():
                if bs_pat.search(content):
                    flagged = True
                    T.fail(
                        f'{name}/{rel}: No Bootstrap 3/4 remnants',
                        f'Found deprecated "{bs_name}" class',
                    )

        if not flagged:
            T.ok(f'{name}: No Bootstrap 3/4 remnants')


# ---------------------------------------------------------------------------
# Responsive patterns
# ---------------------------------------------------------------------------
def _check_responsive_patterns(T, products):
    """Check for consistent responsive breakpoints."""
    T.section('Responsive Design')

    if SHARED_CSS.exists():
        content = SHARED_CSS.read_text(errors='replace')
        # Check standard Bootstrap breakpoints are used
        breakpoints = re.findall(r'@media\s*\([^)]*max-width:\s*([\d.]+)px', content)
        T.check(
            len(breakpoints) >= 2,
            'Shared CSS defines responsive breakpoints',
            f'Found {len(breakpoints)} breakpoints: {", ".join(breakpoints)}px',
        )

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        css_dir = info['static'] / 'css'
        if not css_dir.exists():
            continue

        for css_file in sorted(css_dir.glob('*.css')):
            content = css_file.read_text(errors='replace')

            # Check for non-standard breakpoints
            breakpoints = re.findall(r'@media\s*\([^)]*max-width:\s*([\d.]+)px', content)
            non_standard = [
                bp for bp in breakpoints
                if float(bp) not in {575.98, 767.98, 991.98, 1199.98, 1399.98}
            ]
            if non_standard:
                T.fail(
                    f'{name}/{css_file.name}: Standard breakpoints only',
                    f'Non-standard: {", ".join(non_standard)}px',
                )


# ---------------------------------------------------------------------------
# Print styles
# ---------------------------------------------------------------------------
def _check_print_styles(T, products):
    """Check for print stylesheet coverage."""
    T.section('Print Styles')

    if SHARED_CSS.exists():
        content = SHARED_CSS.read_text(errors='replace')
        T.check(
            '@media print' in content,
            'Shared CSS includes print styles',
        )
        T.check(
            '.no-print' in content or 'no-print' in content,
            'Shared CSS provides .no-print utility class',
        )

    for name, _info, base_name, _path, content in _iter_base_templates(products):
        # Check for print-specific stylesheet or media query
        has_print = (
            '@media print' in content
            or 'media="print"' in content
            or 'no-print' in content
        )
        # This is advisory, not a hard fail
        if not has_print:
            T.ok(
                f'{name}/{base_name}: Print styles via shared CSS',
                'Relies on docklabs-v2.css print rules',
            )


# ---------------------------------------------------------------------------
# JavaScript patterns
# ---------------------------------------------------------------------------
def _check_js_patterns(T, products):
    """Check JavaScript for consistency and shared utility usage."""
    T.section('JavaScript Patterns')

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        js_dir = info['static'] / 'js'
        if js_dir.exists():
            for js_file in sorted(js_dir.glob('*.js')):
                content = js_file.read_text(errors='replace')

                # Check for jQuery usage (should use vanilla JS or htmx)
                jquery_refs = len(re.findall(r'\$\(|jQuery\(|jQuery\.', content))
                if jquery_refs > 0:
                    T.fail(
                        f'{name}/{js_file.name}: No jQuery dependency',
                        f'Found {jquery_refs} jQuery references (use vanilla JS or htmx)',
                    )

                # Check for console.log statements (should be removed in prod)
                console_logs = len(re.findall(r'console\.(log|debug)\(', content))
                if console_logs > 0:
                    T.fail(
                        f'{name}/{js_file.name}: No console.log statements',
                        f'Found {console_logs} console.log/debug calls',
                    )

        # Check for inline event handlers in templates
        template_dir = info['templates']
        if template_dir.exists():
            inline_handlers = 0
            for tpl in template_dir.rglob('*.html'):
                content = tpl.read_text(errors='replace')
                # onclick= is OK for simple confirms, but onload/onmouseover are red flags
                inline_handlers += len(re.findall(r'\bon(?:load|mouseover|mouseout|keypress)=', content))

            T.check(
                inline_handlers == 0,
                f'{name}: No problematic inline event handlers',
                f'Found {inline_handlers}' if inline_handlers else '',
            )
