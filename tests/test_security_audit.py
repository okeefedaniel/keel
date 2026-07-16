"""Tests for keel.testing.security_audit.

The audit's --auto-fix writes to settings.py and the nightly opens a PR from
the result, so a false positive here becomes a nightly PR proposing a change
nobody wants. Two such cases are pinned below.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

from keel.testing.security_audit import REQUIRED_SETTINGS, _effective_settings_content


def _would_flag(root, path):
    """Settings the audit would report missing (and --auto-fix would append)."""
    content = path.read_text()
    effective = _effective_settings_content(root, path, content)
    missing = []
    for setting in REQUIRED_SETTINGS:
        if re.compile(rf'^{setting}\s*=\s*(.+?)$', re.MULTILINE).search(effective):
            continue
        if re.search(rf'{setting}.*os\.environ|if not DEBUG.*{setting}',
                     effective, re.DOTALL):
            continue
        missing.append(setting)
    return missing


class EffectiveSettingsContentTests(SimpleTestCase):

    def _write(self, root, rel, text):
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_star_import_pulls_in_the_parent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self._write(td, 'parent/settings.py', 'X_FRAME_OPTIONS = "DENY"\n')
            child = self._write(td, 'child/settings.py',
                                'from parent.settings import *\nNAME = "child"\n')
            effective = _effective_settings_content(
                Path(td), child, child.read_text())
        self.assertIn('X_FRAME_OPTIONS', effective)
        self.assertIn('NAME = "child"', effective)

    def test_inherited_settings_are_not_reported_missing(self):
        """The admiralty shape: a stub that star-imports a configured parent.

        Reading the stub alone reported all eleven settings missing, and
        --auto-fix appended every one of them.
        """
        import tempfile
        parent = '\n'.join(f'{s} = {v}' for s, (v, _d) in REQUIRED_SETTINGS.items())
        with tempfile.TemporaryDirectory() as td:
            self._write(td, 'harbor/settings.py', parent + '\n')
            child = self._write(td, 'admiralty/settings.py',
                                'from harbor.settings import *\nKEEL_PRODUCT_NAME = "admiralty"\n')
            self.assertEqual(_would_flag(Path(td), child), [])

    def test_a_bare_settings_file_is_still_flagged(self):
        # The fix must not blind the audit — a file that inherits nothing and
        # sets nothing should still report every required setting.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bare = self._write(td, 'bare/settings.py', 'DEBUG = False\n')
            self.assertEqual(len(_would_flag(Path(td), bare)), len(REQUIRED_SETTINGS))

    def test_unresolvable_import_is_skipped_not_raised(self):
        # Star-imports of site-packages or generated modules don't resolve to a
        # file in-repo. That's a missed parent, not a crash.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            child = self._write(td, 'p/settings.py',
                                'from some.external.package import *\nDEBUG = False\n')
            effective = _effective_settings_content(Path(td), child, child.read_text())
        self.assertIn('DEBUG = False', effective)

    def test_self_referential_import_terminates(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = self._write(td, 'a/settings.py', 'from a.settings import *\nDEBUG = False\n')
            effective = _effective_settings_content(Path(td), path, path.read_text())
        self.assertIn('DEBUG = False', effective)


class RequiredSettingsPolicyTests(SimpleTestCase):

    def test_ssl_redirect_expects_false(self):
        """keel/CLAUDE.md: SECURE_SSL_REDIRECT MUST be False on Railway.

        The proxy terminates TLS and healthchecks over plain HTTP, so True
        makes the healthcheck 301 and blocks the deploy. keel_site and all
        nine products set it False. The audit required True, so --auto-fix
        appended a deploy-breaking line to any file that stayed silent.
        """
        expected, _description = REQUIRED_SETTINGS['SECURE_SSL_REDIRECT']
        self.assertEqual(expected, 'False')
