"""Report the Keel commit each DockLabs product is pinned to.

Usage:
    python manage.py check_suite_versions
    python manage.py check_suite_versions --siblings-dir ~/Code/CT
    python manage.py check_suite_versions --keel-repo ~/Code/CT/keel
    python manage.py check_suite_versions --fail-on-drift

Pip resolves ``keel @ git+https://.../keel.git@<ref>`` by the (package
name, version) key — it does NOT re-fetch when only the git ref changes.
So a product can push a requirements bump, see its build succeed, and
silently run yesterday's Keel wheel cached from a prior install. This
command makes the pinning visible across the suite:

- For every sibling repo with a ``requirements.txt`` pinning ``keel``,
  extract the ref, resolve it in the Keel checkout, and read the
  ``__version__`` that was shipped at that commit.
- Compare each pin to Keel HEAD and report drift.
- With ``--fail-on-drift`` exit non-zero when any product is behind
  HEAD (for use in a pre-commit / CI gate).
"""
import os
import re
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


KEEL_PIN_RE = re.compile(
    r'^\s*keel\s*@\s*git\+[^@]+@(?P<ref>[A-Za-z0-9._\-]+)',
    re.MULTILINE,
)
VERSION_RE = re.compile(r"""__version__\s*=\s*['"]([^'"]+)['"]""")


class Command(BaseCommand):
    help = 'Report the Keel commit each sibling DockLabs product is pinned to'

    def add_arguments(self, parser):
        parser.add_argument(
            '--siblings-dir',
            default=None,
            help='Directory holding sibling product repos (default: parent of --keel-repo)',
        )
        parser.add_argument(
            '--keel-repo',
            default=None,
            help='Path to the Keel git checkout (default: auto-detect from this file)',
        )
        parser.add_argument(
            '--fail-on-drift',
            action='store_true',
            help='Exit non-zero if any product pins a commit behind Keel HEAD',
        )

    def handle(self, *args, **options):
        keel_repo = self._resolve_keel_repo(options['keel_repo'])
        siblings_dir = Path(options['siblings_dir'] or keel_repo.parent).expanduser().resolve()

        if not (keel_repo / '.git').exists():
            raise CommandError(f'Not a git checkout: {keel_repo}')
        if not siblings_dir.is_dir():
            raise CommandError(f'Siblings directory not found: {siblings_dir}')

        head_sha = self._git(keel_repo, 'rev-parse', 'HEAD')
        head_short = head_sha[:7]
        head_version = self._version_at(keel_repo, head_sha)

        self.stdout.write(f'Keel repo:     {keel_repo}')
        self.stdout.write(f'Keel HEAD:     {head_short}  (v{head_version})')
        self.stdout.write(f'Siblings dir:  {siblings_dir}')
        self.stdout.write('')

        rows = []
        drifted = []
        for sibling in sorted(siblings_dir.iterdir()):
            if sibling == keel_repo or not sibling.is_dir():
                continue
            req = sibling / 'requirements.txt'
            if not req.exists():
                continue
            pin = self._extract_pin(req)
            if not pin:
                continue

            resolved_sha, error = self._resolve_ref(keel_repo, pin)
            if error:
                rows.append((sibling.name, pin, '?', '?', error))
                continue

            version = self._version_at(keel_repo, resolved_sha) or '?'
            status = 'OK' if resolved_sha == head_sha else self._behind_label(
                keel_repo, resolved_sha, head_sha,
            )
            rows.append((sibling.name, pin, resolved_sha[:7], version, status))
            if resolved_sha != head_sha:
                drifted.append(sibling.name)

        if not rows:
            self.stdout.write(self.style.WARNING('No sibling products with a keel pin were found.'))
            return

        self._print_table(rows)

        if drifted:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'{len(drifted)} product(s) drifted from Keel HEAD: '
                + ', '.join(drifted)
            ))
            if options['fail_on_drift']:
                raise CommandError('Version drift detected (--fail-on-drift).')
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('All products pinned to Keel HEAD.'))

    def _resolve_keel_repo(self, override):
        if override:
            return Path(override).expanduser().resolve()
        # keel/core/management/commands/<this file>  →  repo root is 4 up
        here = Path(__file__).resolve()
        for candidate in (here.parents[4], Path.home() / 'Code' / 'CT' / 'keel'):
            if (candidate / '.git').exists() and (candidate / 'keel' / '__init__.py').exists():
                return candidate
        raise CommandError(
            'Could not locate the Keel git checkout. Pass --keel-repo explicitly.'
        )

    def _git(self, repo, *args):
        result = subprocess.run(
            ['git', '-C', str(repo), *args],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise CommandError(f'git {args} failed: {result.stderr.strip()}')
        return result.stdout.strip()

    def _extract_pin(self, requirements_path):
        text = requirements_path.read_text(encoding='utf-8', errors='replace')
        match = KEEL_PIN_RE.search(text)
        return match.group('ref') if match else None

    def _resolve_ref(self, keel_repo, ref):
        result = subprocess.run(
            ['git', '-C', str(keel_repo), 'rev-parse', '--verify', f'{ref}^{{commit}}'],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            return None, f'unknown ref ({ref})'
        return result.stdout.strip(), None

    def _version_at(self, keel_repo, sha):
        try:
            blob = self._git(keel_repo, 'show', f'{sha}:keel/__init__.py')
        except CommandError:
            return None
        match = VERSION_RE.search(blob)
        return match.group(1) if match else None

    def _behind_label(self, keel_repo, sha, head_sha):
        # `git rev-list --count sha..head` = number of commits HEAD is ahead.
        try:
            count = self._git(keel_repo, 'rev-list', '--count', f'{sha}..{head_sha}')
            return f'{count} behind'
        except CommandError:
            return 'drift'

    def _print_table(self, rows):
        headers = ('Product', 'Pinned ref', 'Resolved', 'Version', 'Status')
        widths = [
            max(len(str(r[i])) for r in [headers, *rows])
            for i in range(len(headers))
        ]
        fmt = '  '.join(f'{{:<{w}}}' for w in widths)
        self.stdout.write(fmt.format(*headers))
        self.stdout.write(fmt.format(*('-' * w for w in widths)))
        for row in rows:
            line = fmt.format(*row)
            if row[-1] == 'OK':
                self.stdout.write(self.style.SUCCESS(line))
            elif 'behind' in str(row[-1]):
                self.stdout.write(self.style.WARNING(line))
            else:
                self.stdout.write(self.style.ERROR(line))
