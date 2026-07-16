"""Tests for keel.testing.ui_audit.

The audit asserted the pre-v0.56.3 design system (Poppins, the --ct-* palette,
docklabs.css) and greped each product's base.html without following
{% extends %}, so it reported the shared layout doing its job as 28 defects and
flagged product-specific classes like sig-panel as Bootstrap 3 remnants. These
pin the three fixes so the rules can't regress to the stale shape.
"""
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from keel.testing import ui_audit


class ClassTokenMatcherTests(SimpleTestCase):
    """_class_token_re matches a class NAME, not any substring of one."""

    def setUp(self):
        self.panel = ui_audit._class_token_re('panel')

    def test_real_bootstrap3_panel_is_matched(self):
        self.assertTrue(self.panel.search('<div class="panel">'))
        self.assertTrue(self.panel.search('<div class="panel panel-default">'))
        self.assertTrue(self.panel.search('<div class="panel-heading">'))

    def test_product_specific_panel_classes_are_not_matched(self):
        # The false positives: `-` is a word boundary, so a naive \bpanel\b
        # flagged both of Harbor's product classes as BS3 remnants.
        self.assertIsNone(self.panel.search('<div class="sig-panel">'))
        self.assertIsNone(self.panel.search('<div class="wizard-panel d-none">'))


class ExtendsChainTests(SimpleTestCase):
    """_chain_content follows {% extends %} so inherited markup counts."""

    def _write(self, root, rel, text):
        p = Path(root) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_parent_content_is_included(self):
        with tempfile.TemporaryDirectory() as td:
            self._write(td, 'templates/keel/layouts/app.html',
                        '<html lang="en"><a class="skip-link">skip</a>'
                        '{% block content %}{% endblock %}</html>')
            leaf = self._write(td, 'templates/base.html',
                               '{% extends "keel/layouts/app.html" %}'
                               '{% block content %}hi{% endblock %}')
            content = ui_audit._chain_content(leaf, [Path(td) / 'templates'])
            # The skip link and lang attr live only in the parent.
            self.assertIn('skip-link', content)
            self.assertIn('lang="en"', content)

    def test_a_leaf_with_no_parent_returns_just_itself(self):
        with tempfile.TemporaryDirectory() as td:
            leaf = self._write(td, 'templates/base.html', '<html>bare</html>')
            content = ui_audit._chain_content(leaf, [Path(td) / 'templates'])
            self.assertEqual(content.strip(), '<html>bare</html>')

    def test_self_referential_extends_terminates(self):
        with tempfile.TemporaryDirectory() as td:
            leaf = self._write(td, 'templates/base.html',
                               '{% extends "base.html" %}loop')
            # Must not infinite-loop; the seen-set breaks the cycle.
            content = ui_audit._chain_content(leaf, [Path(td) / 'templates'])
            self.assertIn('loop', content)


class CanonicalDesignSystemTests(SimpleTestCase):
    """CANONICAL is the v3 editorial stack, not the retired Poppins/--ct- one."""

    def test_font_stack_is_the_v3_editorial_stack(self):
        fonts = ui_audit.CANONICAL['fonts']
        self.assertEqual(fonts['--font-display'], 'Fraunces')
        self.assertEqual(fonts['--font-sans'], 'Instrument Sans')
        self.assertEqual(fonts['--font-mono'], 'JetBrains Mono')

    def test_poppins_is_not_required_anywhere_in_canonical(self):
        # Poppins was removed from authenticated chrome in v0.56.3; requiring it
        # here is what turned the intended state into 5 failures.
        self.assertNotIn('Poppins', repr(ui_audit.CANONICAL))
