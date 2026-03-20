"""Product registry and test configuration for the DockLabs suite."""
import os
from dataclasses import dataclass, field
from pathlib import Path

# Base directory — all repos are siblings
BASE_DIR = Path(os.environ.get(
    'DOCKLABS_BASE_DIR',
    os.path.expanduser('~/SynologyDrive/Work/CT/Web'),
))

DEMO_PASSWORD = 'demo2026!'


@dataclass
class Product:
    """A DockLabs product to test."""
    name: str
    repo_dir: str  # relative to BASE_DIR
    settings_module: str
    live_url: str
    demo_roles: list = field(default_factory=list)
    public_urls: list = field(default_factory=list)
    auth_urls: dict = field(default_factory=dict)  # role -> [urls]
    workflows: list = field(default_factory=list)  # workflow test function names
    has_django_tests: bool = True
    venv_python: str = 'venv/bin/python'

    @property
    def path(self) -> Path:
        return BASE_DIR / self.repo_dir


PRODUCTS = {
    'lookout': Product(
        name='Lookout',
        repo_dir='lookout',
        settings_module='lookout.settings',
        live_url='https://lookout.docklabs.ai',
        demo_roles=['admin', 'legislative_aid', 'stakeholder'],
        public_urls=[
            '/',
            '/auth/login/',
        ],
        auth_urls={
            'admin': [
                '/dashboard/',
                '/bills/',
                '/testimony/',
                '/watchlist/',
                '/signing/',
                '/stakeholders/',
                '/calendar/',
                '/audit/',
                '/auth/notifications/',
                '/auth/profile/',
            ],
            'legislative_aid': [
                '/dashboard/',
                '/bills/',
                '/testimony/',
                '/watchlist/',
                '/auth/notifications/',
            ],
            'stakeholder': [
                '/dashboard/',
                '/bills/',
                '/auth/notifications/',
            ],
        },
        workflows=['test_bill_browsing', 'test_testimony_workflow', 'test_watchlist'],
    ),
    'beacon': Product(
        name='Beacon',
        repo_dir='beacon',
        settings_module='beacon.settings',
        live_url='https://beacon.docklabs.ai',
        demo_roles=[
            'admin', 'agency_admin', 'relationship_manager',
            'foia_officer', 'foia_attorney', 'analyst',
        ],
        public_urls=[
            '/login/',
        ],
        auth_urls={
            'admin': [
                '/dashboard/',
                '/companies/',
                '/interactions/',
                '/pipeline/',
                '/foia/',
                '/analytics/',
                '/audit/',
                '/auth/notifications/',
                '/auth/profile/',
            ],
            'relationship_manager': [
                '/dashboard/',
                '/companies/',
                '/interactions/',
                '/pipeline/',
                '/auth/notifications/',
            ],
            'foia_officer': [
                '/dashboard/',
                '/foia/',
                '/auth/notifications/',
            ],
            'analyst': [
                '/dashboard/',
                '/companies/',
                '/auth/notifications/',
            ],
        },
        workflows=['test_company_crud', 'test_foia_workflow'],
    ),
    'admiralty': Product(
        name='Admiralty',
        repo_dir='beacon',
        settings_module='admiralty.settings',
        live_url='https://admiralty.docklabs.ai',
        demo_roles=['admin', 'foia_officer', 'foia_attorney'],
        public_urls=[
            '/login/',
        ],
        auth_urls={
            'admin': [
                '/dashboard/',
                '/foia/',
                '/auth/notifications/',
            ],
            'foia_officer': [
                '/dashboard/',
                '/foia/',
            ],
        },
        workflows=['test_foia_standalone'],
    ),
    'harbor': Product(
        name='Harbor',
        repo_dir='harbor',
        settings_module='harbor.settings',
        live_url='https://harbor.docklabs.ai',
        demo_roles=[
            'admin', 'agency_admin', 'program_officer',
            'fiscal_officer', 'reviewer', 'applicant',
        ],
        public_urls=[
            '/',
            '/opportunities/',
            '/about/',
            '/help/',
            '/auth/login/',
            '/auth/register/',
        ],
        auth_urls={
            'admin': [
                '/dashboard/',
                '/applications/',
                '/awards/',
                '/reporting/',
                '/financial/drawdowns/',
                '/financial/transactions/',
                '/grants/',
                '/auth/notifications/',
                '/auth/profile/',
            ],
            'program_officer': [
                '/dashboard/',
                '/applications/',
                '/awards/',
                '/reporting/',
                '/auth/notifications/',
            ],
            'fiscal_officer': [
                '/dashboard/',
                '/financial/drawdowns/',
                '/financial/transactions/',
                '/auth/notifications/',
            ],
            'applicant': [
                '/applications/my/',
                '/awards/my/',
                '/auth/notifications/',
                '/auth/profile/',
            ],
            'reviewer': [
                '/dashboard/',
                '/applications/',
                '/auth/notifications/',
            ],
        },
        workflows=[
            'test_applicant_workflow',
            'test_staff_review_workflow',
            'test_award_workflow',
        ],
    ),
    'manifest': Product(
        name='Manifest',
        repo_dir='harbor',
        settings_module='manifest.settings',
        live_url='https://manifest.docklabs.ai',
        demo_roles=['admin'],
        public_urls=[
            '/auth/login/',
        ],
        auth_urls={
            'admin': [
                '/dashboard/',
                '/packets/',
                '/templates/',
                '/auth/notifications/',
            ],
        },
        workflows=['test_signing_flow'],
    ),
}
