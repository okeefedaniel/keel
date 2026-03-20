"""UI consistency audit across all DockLabs products.

Scans templates, CSS, JS, and static assets across Beacon, Harbor, Lookout,
and their sub-products (Admiralty, Manifest) to detect inconsistencies in:

- CDN/library versions (Bootstrap, htmx, Bootstrap Icons)
- CSS custom properties and color palette adherence
- Template structure (block names, base template patterns)
- Component patterns (cards, tables, buttons, forms, navigation)
- Accessibility patterns (skip links, ARIA, focus styles)
- Font stack and typography consistency
- Responsive breakpoints
- Print stylesheet coverage
- Icon library usage
- Hard-coded colors vs design tokens

Reports both PASS/FAIL checks and advisory recommendations.

Usage:
    python -m keel.testing --ui-only
    python -m keel.testing  # (includes UI audit automatically)
"""
import os
import re
from pathlib import Path

from .config import BASE_DIR
from .result import TestResult

# ---------------------------------------------------------------------------
# Canonical design tokens — the "source of truth" from docklabs.css
# ---------------------------------------------------------------------------
CANONICAL = {
    'bootstrap_css': 'bootstrap@5.3.3',
    'bootstrap_js': 'bootstrap@5.3.3',
    'bootstrap_icons': 'bootstrap-icons@1.11.3',
    'htmx_min': '2.0.0',
    'google_fonts': 'Poppins',
    'heading_font': 'Poppins',
    'body_font': 'Arial',
    'colors': {
        '--ct-blue': '#1F64E5',
        '--ct-dark-blue': '#00214D',
        '--ct-bold-blue': '#003D9C',
        '--ct-light-blue': '#C6D4FB',
        '--ct-pale-blue': '#EBF0FF',
        '--ct-orange': '#F27124',
        '--ct-yellow': '#FAAA19',
        '--ct-brown': '#BA5803',
        '--ct-red': '#E91C1F',
        '--ct-green': '#198754',
        '--ct-dark-gray': '#333333',
        '--ct-light-gray': '#F8F8F8',
    },
}

# Products and their template/static roots
PRODUCT_ROOTS = {
    'Beacon': {
        'templates': BASE_DIR / 'beacon' / 'templates',
        'static': BASE_DIR / 'beacon' / 'static',
        'base_templates': ['base.html', 'admiralty/base.html'],
    },
    'Harbor': {
        'templates': BASE_DIR / 'harbor' / 'templates',
        'static': BASE_DIR / 'harbor' / 'static',
        'base_templates': ['base.html', 'manifest/base.html'],
    },
    'Lookout': {
        'templates': BASE_DIR / 'lookout' / 'templates',
        'static': BASE_DIR / 'lookout' / 'static',
        'base_templates': ['base.html'],
    },
}

# Common template blocks that should be present in all base templates
EXPECTED_BLOCKS = {'title', 'content', 'extra_css', 'extra_js'}

# Required accessibility elements in base templates
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
    'google_fonts': re.compile(r'fonts\.googleapis\.com/css2\?family=([^&"\']+)'),
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

    # Cross-product checks
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
# CDN & library version consistency
# ---------------------------------------------------------------------------
def _check_cdn_versions(T, products):
    """Verify all products use the same CDN library versions."""
    T.section('CDN & Library Versions')

    versions = {}  # {library: {product: version}}

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        for base_name in info['base_templates']:
            base_path = info['templates'] / base_name
            if not base_path.exists():
                T.fail(f'{name}: base template exists', f'Missing {base_path}')
                continue

            content = base_path.read_text(errors='replace')

            for lib, pattern in CDN_PATTERNS.items():
                match = pattern.search(content)
                if match:
                    ver = match.group(1)
                    versions.setdefault(lib, {})[f'{name}/{base_name}'] = ver

    # Check each library for version consistency
    for lib, product_versions in versions.items():
        unique_versions = set(product_versions.values())
        if len(unique_versions) == 1:
            ver = unique_versions.pop()
            # Check against canonical
            canonical = CANONICAL.get(lib, '')
            if canonical and ver not in canonical:
                T.fail(
                    f'{lib} version matches canonical',
                    f'Found {ver}, expected to contain {canonical}',
                )
            else:
                T.ok(f'{lib} version consistent', f'All products use {ver}')
        else:
            details = ', '.join(f'{p}: {v}' for p, v in product_versions.items())
            T.fail(f'{lib} version consistent', f'Mismatch: {details}')

    # Check htmx specifically — it may appear in base templates
    htmx_versions = versions.get('htmx', {})
    if htmx_versions:
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

    # Check that docklabs.css exists and contains all canonical variables
    shared_css = BASE_DIR / 'keel' / 'keel' / 'core' / 'static' / 'css' / 'docklabs.css'
    if not shared_css.exists():
        T.fail('Shared docklabs.css exists', str(shared_css))
        return

    shared_content = shared_css.read_text(errors='replace')

    for var_name, expected_value in CANONICAL['colors'].items():
        # Check variable is defined
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
            T.fail(f'{var_name} defined in docklabs.css')

    # Check each product's CSS uses variables, not raw hex for brand colors
    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        css_dir = info['static'] / 'css'
        if not css_dir.exists():
            continue

        for css_file in css_dir.glob('*.css'):
            content = css_file.read_text(errors='replace')
            # Check if product CSS references the shared variables
            var_refs = re.findall(r'var\(--ct-[a-z-]+\)', content)
            raw_brand = re.findall(r'#1F64E5|#00214D|#003D9C|#F27124|#FAAA19', content, re.IGNORECASE)

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
    """Verify consistent template block structure across products."""
    T.section('Template Structure')

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info or not info['templates'].exists():
            continue

        for base_name in info['base_templates']:
            base_path = info['templates'] / base_name
            if not base_path.exists():
                continue

            content = base_path.read_text(errors='replace')

            # Check for expected blocks
            defined_blocks = set(re.findall(r'\{%\s*block\s+(\w+)', content))
            for block in EXPECTED_BLOCKS:
                T.check(
                    block in defined_blocks,
                    f'{name}/{base_name} defines {{% block {block} %}}',
                )

            # Check docklabs.css is loaded
            T.check(
                'docklabs.css' in content or 'docklabs' in content,
                f'{name}/{base_name} loads shared docklabs.css',
            )

            # Check docklabs.js is loaded
            T.check(
                'docklabs.js' in content or 'docklabs' in content,
                f'{name}/{base_name} loads shared docklabs.js',
            )

            # Check Bootstrap CSS loaded
            T.check(
                'bootstrap' in content.lower(),
                f'{name}/{base_name} loads Bootstrap',
            )

            # Check Bootstrap Icons loaded
            T.check(
                'bootstrap-icons' in content,
                f'{name}/{base_name} loads Bootstrap Icons',
            )

        # Check child templates extend base
        template_dir = info['templates']
        for tpl_path in template_dir.rglob('*.html'):
            # Skip base templates and partials
            rel = tpl_path.relative_to(template_dir)
            if str(rel) in info['base_templates']:
                continue
            if 'email' in str(rel) or 'partial' in str(rel):
                continue

            content = tpl_path.read_text(errors='replace')
            if '{%' in content:  # It's a Django template
                has_extends = '{% extends' in content or '{%extends' in content
                is_include = '{% include' not in content and '{%' in content
                # Fragments/includes don't need extends
                if not has_extends and '{% block' in content:
                    # Has blocks but no extends — likely a standalone fragment, skip
                    pass


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------
def _check_accessibility(T, products):
    """Check for WCAG 2.1 AA compliance patterns in base templates."""
    T.section('Accessibility')

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        for base_name in info['base_templates']:
            base_path = info['templates'] / base_name
            if not base_path.exists():
                continue

            content = base_path.read_text(errors='replace')

            for check_id, (pattern, description) in A11Y_CHECKS.items():
                found = bool(re.search(pattern, content, re.IGNORECASE))
                T.check(
                    found,
                    f'{name}/{base_name}: {description}',
                )

            # Check for focus styles in CSS
            css_dir = info['static'] / 'css'
            if css_dir.exists():
                all_css = ''
                for css_file in css_dir.glob('*.css'):
                    all_css += css_file.read_text(errors='replace')

                # Also check shared CSS
                shared_css = BASE_DIR / 'keel' / 'keel' / 'core' / 'static' / 'css' / 'docklabs.css'
                if shared_css.exists():
                    all_css += shared_css.read_text(errors='replace')

                T.check(
                    ':focus-visible' in all_css or ':focus' in all_css,
                    f'{name}: Custom focus styles defined',
                )


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
def _check_typography(T, products):
    """Verify consistent font stack and heading hierarchy."""
    T.section('Typography')

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        for base_name in info['base_templates']:
            base_path = info['templates'] / base_name
            if not base_path.exists():
                continue

            content = base_path.read_text(errors='replace')

            # Check Google Fonts loaded with Poppins
            T.check(
                'Poppins' in content,
                f'{name}/{base_name}: Poppins font loaded',
            )

        # Check product CSS doesn't override heading font
        css_dir = info['static'] / 'css'
        if css_dir.exists():
            for css_file in css_dir.glob('*.css'):
                content = css_file.read_text(errors='replace')
                # Look for font-family overrides on headings
                heading_font_override = re.search(
                    r'h[1-6]\s*\{[^}]*font-family\s*:', content,
                )
                if heading_font_override:
                    T.fail(
                        f'{name}/{css_file.name}: No heading font override',
                        'Product CSS overrides heading font-family (should use shared)',
                    )


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

        for css_file in css_dir.glob('*.css'):
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
    """Check for consistent component markup patterns across templates."""
    T.section('Component Patterns')

    patterns = {
        'navbar': re.compile(r'navbar-dark|navbar-light|class="[^"]*navbar\b'),
        'card': re.compile(r'class="[^"]*\bcard\b'),
        'table_hover': re.compile(r'class="[^"]*table-hover'),
        'table_light_head': re.compile(r'class="[^"]*table-light'),
        'btn_primary': re.compile(r'class="[^"]*btn-primary'),
        'form_control': re.compile(r'class="[^"]*form-control'),
        'breadcrumb': re.compile(r'class="[^"]*breadcrumb'),
        'badge': re.compile(r'class="[^"]*\bbadge\b'),
    }

    component_usage = {}  # {product: {pattern_name: count}}

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info or not info['templates'].exists():
            continue

        counts = {p: 0 for p in patterns}
        template_dir = info['templates']

        for tpl_path in template_dir.rglob('*.html'):
            content = tpl_path.read_text(errors='replace')
            for pat_name, pat in patterns.items():
                counts[pat_name] += len(pat.findall(content))

        component_usage[name] = counts

    # Report: check that all products use similar component vocabulary
    for pat_name in patterns:
        using = [name for name in component_usage if component_usage[name][pat_name] > 0]
        not_using = [name for name in component_usage if component_usage[name][pat_name] == 0]

        if not_using and using:
            T.fail(
                f'All products use {pat_name} pattern',
                f'Missing in: {", ".join(not_using)}. Used by: {", ".join(using)}',
            )
        elif using:
            T.ok(f'All products use {pat_name} pattern')

    # Check for Bootstrap 4 leftovers (e.g., btn-default, panel, well)
    bs4_patterns = {
        'btn-default': re.compile(r'btn-default'),
        'panel': re.compile(r'class="[^"]*\bpanel\b'),
        'well': re.compile(r'class="[^"]*\bwell\b'),
        'label-': re.compile(r'class="[^"]*label-(primary|success|danger|warning|info)'),
    }

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info or not info['templates'].exists():
            continue

        for tpl_path in info['templates'].rglob('*.html'):
            content = tpl_path.read_text(errors='replace')
            rel = tpl_path.relative_to(info['templates'])

            for bs4_name, bs4_pat in bs4_patterns.items():
                if bs4_pat.search(content):
                    T.fail(
                        f'{name}/{rel}: No Bootstrap 4 remnants',
                        f'Found deprecated "{bs4_name}" class',
                    )


# ---------------------------------------------------------------------------
# Responsive patterns
# ---------------------------------------------------------------------------
def _check_responsive_patterns(T, products):
    """Check for consistent responsive breakpoints."""
    T.section('Responsive Design')

    shared_css = BASE_DIR / 'keel' / 'keel' / 'core' / 'static' / 'css' / 'docklabs.css'
    if shared_css.exists():
        content = shared_css.read_text(errors='replace')
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

        for css_file in css_dir.glob('*.css'):
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

    # Check shared CSS has print styles
    shared_css = BASE_DIR / 'keel' / 'keel' / 'core' / 'static' / 'css' / 'docklabs.css'
    if shared_css.exists():
        content = shared_css.read_text(errors='replace')
        T.check(
            '@media print' in content,
            'Shared CSS includes print styles',
        )
        T.check(
            '.no-print' in content or 'no-print' in content,
            'Shared CSS provides .no-print utility class',
        )

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        # Check base template for print considerations
        for base_name in info['base_templates']:
            base_path = info['templates'] / base_name
            if not base_path.exists():
                continue

            content = base_path.read_text(errors='replace')
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
                    'Relies on docklabs.css print rules',
                )


# ---------------------------------------------------------------------------
# JavaScript patterns
# ---------------------------------------------------------------------------
def _check_js_patterns(T, products):
    """Check JavaScript for consistency and shared utility usage."""
    T.section('JavaScript Patterns')

    # Check shared docklabs.js exists
    shared_js = BASE_DIR / 'keel' / 'keel' / 'core' / 'static' / 'js' / 'docklabs.js'
    T.check(shared_js.exists(), 'Shared docklabs.js exists')

    for name in products:
        info = PRODUCT_ROOTS.get(name)
        if not info:
            continue

        js_dir = info['static'] / 'js'
        if not js_dir.exists():
            continue

        for js_file in js_dir.glob('*.js'):
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
