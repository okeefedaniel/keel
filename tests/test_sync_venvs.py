"""Tests for scripts/sync_venvs.py.

This script is the fleet's only guard against a local venv drifting from its
requirements.txt keel pin, and it reported "ok" for venvs that could not import
their own dependencies. The nightly's unit-test coverage is meaningless while
that is true, so the false-negative cases are pinned below.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

_SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'sync_venvs.py'
_spec = importlib.util.spec_from_file_location('sync_venvs', _SCRIPT)
sync_venvs = importlib.util.module_from_spec(_spec)
sys.modules['sync_venvs'] = sync_venvs
_spec.loader.exec_module(sync_venvs)


class ClassifyTests(SimpleTestCase):
    """classify() decides what counts as healthy. Only 'ok' does."""

    def _info(self, **over):
        info = {
            'purelib': '/p/.venv/lib/python3.14/site-packages',
            'platlib': '/p/.venv/lib/python3.14/site-packages',
            'version': '0.57.2',
            'file': '/p/.venv/lib/python3.14/site-packages/keel/__init__.py',
            'metadata_version': '0.57.2',
            'missing': [],
        }
        info.update(over)
        return info

    def test_healthy_venv_is_ok(self):
        self.assertEqual(sync_venvs.classify(self._info(), '0.57.2')[0], 'ok')

    def test_editable_install_is_never_ok(self):
        """The bug: keel resolving to the live source tree always looks current.

        harbor's venv held an editable keel pointing at /Users/dok/Code/CT/keel
        and nothing else — no drf_spectacular, no Django. It reported the
        checkout's version, so it could never show drift.
        """
        status, detail = sync_venvs.classify(
            self._info(version='0.57.3', file='/Users/dok/Code/CT/keel/keel/__init__.py'),
            '0.57.2')
        self.assertEqual(status, 'EDITABLE')
        self.assertIn('outside venv site-packages', detail)

    def test_editable_is_not_ok_even_when_version_matches_pin(self):
        """Version equality must not launder an editable install into 'ok'."""
        status, _ = sync_venvs.classify(
            self._info(file='/Users/dok/Code/CT/keel/keel/__init__.py'), '0.57.2')
        self.assertEqual(status, 'EDITABLE')

    def test_unprovisioned_venv_is_incomplete_not_ok(self):
        """keel on pin but the product's other deps were never installed."""
        status, detail = sync_venvs.classify(
            self._info(missing=['drf-spectacular', 'djangorestframework']), '0.57.2')
        self.assertEqual(status, 'INCOMPLETE')
        self.assertIn('drf-spectacular', detail)

    def test_import_version_disagreeing_with_metadata_is_flagged(self):
        """The admiralty case: --check said 0.57.2, `import keel` said 0.46.1."""
        status, detail = sync_venvs.classify(
            self._info(version='0.46.1', metadata_version='0.57.2'), '0.46.1')
        self.assertEqual(status, 'MISMATCH')
        self.assertIn('0.46.1', detail)
        self.assertIn('0.57.2', detail)

    def test_drift_is_reported(self):
        status, _ = sync_venvs.classify(
            self._info(version='0.56.3', metadata_version='0.56.3'), '0.57.2')
        self.assertEqual(status, 'DRIFT')

    def test_unimportable_keel_is_broken(self):
        status, _ = sync_venvs.classify(
            self._info(import_error='ModuleNotFoundError: No module named keel'), '0.57.2')
        self.assertEqual(status, 'BROKEN')

    def test_probe_failure_is_broken_not_ok(self):
        """A venv we cannot interrogate is never assumed healthy."""
        status, _ = sync_venvs.classify({'probe_error': 'boom'}, '0.57.2')
        self.assertEqual(status, 'BROKEN')


class RequiredDistsTests(SimpleTestCase):

    def _req(self, td, text):
        path = Path(td) / 'requirements.txt'
        path.write_text(text)
        return path

    def test_parses_the_shapes_in_the_suite(self):
        with tempfile.TemporaryDirectory() as td:
            req = self._req(td, '\n'.join([
                '# a comment',
                '',
                'Django>=5.2,<6.1',
                'django-allauth[mfa,socialaccount]>=65.0,<66.0',
                'drf-spectacular>=0.27,<1.0',
                '-r other.txt',
                'keel @ git+https://github.com/okeefedaniel/keel.git@v0.57.2',
            ]))
            names = sync_venvs.required_dists(req)
        self.assertEqual(names, ['Django', 'django-allauth', 'drf-spectacular'])

    def test_keel_is_excluded(self):
        """keel is version-checked separately; listing it here would double-report."""
        with tempfile.TemporaryDirectory() as td:
            req = self._req(td, 'keel @ git+https://github.com/okeefedaniel/keel.git@v0.57.2\n')
            self.assertEqual(sync_venvs.required_dists(req), [])


class VenvDiscoveryTests(SimpleTestCase):
    """keel.testing.config runs each product's suite in venv/, not .venv/.

    The script only ever looked at .venv, so it reported 'ok' about a venv
    nothing tests against while venv/ was broken.
    """

    def _venv(self, root, name):
        py = Path(root) / name / 'bin' / 'python'
        py.parent.mkdir(parents=True)
        py.touch()
        return py

    def test_both_layouts_are_discovered(self):
        with tempfile.TemporaryDirectory() as td:
            self._venv(td, 'venv')
            self._venv(td, '.venv')
            found = {p.parent.parent.name for p in sync_venvs.venv_pythons(Path(td))}
        self.assertEqual(found, {'venv', '.venv'})

    def test_products_are_discovered_via_bare_venv_alone(self):
        with tempfile.TemporaryDirectory() as td:
            prod = Path(td) / 'harbor'
            prod.mkdir()
            self._venv(prod, 'venv')
            (prod / 'requirements.txt').write_text(
                'keel @ git+https://github.com/okeefedaniel/keel.git@v0.57.2\n')
            found = sync_venvs.discover(Path(td), [])
        self.assertEqual(found, [prod])


class ProbeCwdIsolationTests(SimpleTestCase):
    """The root cause: `python -c` prepends the caller's cwd to sys.path.

    Run from inside the keel checkout — the documented way to invoke this —
    `import keel` resolved to ./keel/, so every product reported the CHECKOUT's
    version rather than its own venv's. That produced uniform false readings:
    false "ok" whenever the checkout happened to match a product's pin.
    """

    def test_probe_ignores_the_callers_cwd(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            # A decoy keel source tree, exactly like the real checkout.
            decoy = Path(td) / 'keel'
            decoy.mkdir()
            (decoy / '__init__.py').write_text('__version__ = "9.9.9"\n')

            prod = Path(td) / 'harbor'
            prod.mkdir()
            (prod / 'requirements.txt').write_text('')

            old = os.getcwd()
            os.chdir(td)  # stand where the script's caller stands
            try:
                info = sync_venvs.probe(Path(sys.executable), prod)
            finally:
                os.chdir(old)

        self.assertNotEqual(
            info.get('version'), '9.9.9',
            'probe resolved keel from the caller\'s cwd, not the venv')


class SuiteRootTests(SimpleTestCase):

    def test_docklabs_base_dir_overrides_layout_assumption(self):
        """Lets the script run from a git worktree, where parents[2] is unrelated."""
        with tempfile.TemporaryDirectory() as td:
            with self.settings():  # no-op; keeps the SimpleTestCase idiom
                import os
                old = os.environ.get('DOCKLABS_BASE_DIR')
                os.environ['DOCKLABS_BASE_DIR'] = td
                try:
                    self.assertEqual(sync_venvs.suite_root(), Path(td).resolve())
                finally:
                    if old is None:
                        os.environ.pop('DOCKLABS_BASE_DIR')
                    else:
                        os.environ['DOCKLABS_BASE_DIR'] = old
