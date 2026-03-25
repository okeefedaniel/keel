"""Product registry and test configuration for the DockLabs suite.

Every product lists:
- demo_roles: user accounts to test (must exist in product DB via seed command)
- public_urls: pages accessible without login
- auth_urls: {role: [urls]} for per-role page access
- workflows: workflow test keys exercised in workflows.py
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

# Base directory — all repos are siblings
BASE_DIR = Path(os.environ.get(
    'DOCKLABS_BASE_DIR',
    os.path.expanduser('~/SynologyDrive/Work/CT/Web'),
))

DEMO_PASSWORD = os.environ.get('DEMO_PASSWORD', 'demo2026!')


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
    workflows: list = field(default_factory=list)  # workflow test keys
    has_django_tests: bool = True
    venv_python: str = 'venv/bin/python'

    @property
    def path(self) -> Path:
        return BASE_DIR / self.repo_dir


# =========================================================================
# All authenticated URLs (list/dashboard views — no URL parameters)
# grouped by minimum role required
# =========================================================================

_BEACON_COMMON = [
    '/dashboard/',
    '/auth/notifications/',
    '/auth/profile/',
]

_BEACON_STAFF = [
    '/companies/',
    '/companies/contacts/',
    '/companies/moderation/',
    '/interactions/',
    '/pipeline/',
    '/notes/',
    '/imports/',
    '/auth/users/',
    '/auth/analytics/',
    '/auth/adoption/',
    '/auth/audit/',
]

_BEACON_FOIA = [
    '/foia/',
    '/foia/dashboard/',
    '/foia/review/',
    '/foia/exemptions/',
    '/foia/documents/',
]

_ADMIRALTY_ALL = [
    '/foia/',
    '/foia/dashboard/',
    '/foia/documents/',
]

_ADMIRALTY_STAFF = [
    '/foia/review/',
    '/foia/exemptions/',
    '/foia/documents/',
]

_HARBOR_PUBLIC = [
    '/',
    '/opportunities/',
    '/federal-opportunities/',
    '/about/',
    '/help/',
    '/manual/',
    '/privacy/',
    '/terms/',
    '/support/',
]

_HARBOR_COMMON = [
    '/dashboard/',
    '/auth/notifications/',
    '/auth/profile/',
    '/auth/calendar/',
]

_HARBOR_APPLICANT = [
    '/applications/my/',
    '/awards/my/',
    '/signatures/my/',
]

_HARBOR_STAFF = [
    '/applications/',
    '/awards/',
    '/grants/',
    '/reporting/',
    '/financial/drawdowns/',
    '/financial/transactions/',
    '/closeout/',
    '/signatures/packets/',
    '/signatures/flows/',
    '/reviews/',
    '/auth/users/',
    '/auth/analytics/',
    '/auth/organization-claims/',
    '/applications/my-assignments/',
]

_LOOKOUT_PUBLIC = [
    '/',
    '/about/',
    '/help/',
    '/support/',
]

_LOOKOUT_COMMON = [
    '/dashboard/',
    '/bills/',
    '/notifications/',
    '/profile/',
]

_LOOKOUT_USER = [
    '/watchlist/',
    '/testimony/',
    '/tracking/',
    '/tracking/archives/',
    '/tracking/engagement/',
    '/stakeholders/',
    '/stakeholders/legislators/',
    '/calendar/',
    '/discover/',
    '/watchlist/scores/',
]

_LOOKOUT_STAFF = [
    '/audit-log/',
    '/testimony/templates/',
]

_BOUNTY_PUBLIC = [
    '/',
    '/opportunities/',
]

_BOUNTY_COMMON = [
    '/dashboard/',
    '/tracked/',
    '/matching/preferences/',
    '/matching/recommendations/',
]

_BOUNTY_STAFF = [
    '/matching/state-preferences/',
    '/integration/harbor/settings/',
]


PRODUCTS = {
    'lookout': Product(
        name='Lookout',
        repo_dir='lookout',
        settings_module='lookout.settings',
        live_url='https://lookout.docklabs.ai',
        demo_roles=['admin', 'legislative_aid', 'stakeholder'],
        public_urls=_LOOKOUT_PUBLIC + ['/auth/login/'],
        auth_urls={
            'admin': _LOOKOUT_COMMON + _LOOKOUT_USER + _LOOKOUT_STAFF,
            'legislative_aid': _LOOKOUT_COMMON + _LOOKOUT_USER,
            'stakeholder': _LOOKOUT_COMMON + ['/bills/'],
        },
        workflows=[
            'test_bill_browsing',
            'test_testimony_workflow',
            'test_watchlist',
            'test_tracking_workflow',
            'test_collaborator_flow',
        ],
    ),
    'beacon': Product(
        name='Beacon',
        repo_dir='beacon',
        settings_module='beacon.settings',
        live_url='https://beacon.docklabs.ai',
        demo_roles=[
            'admin', 'agency_admin', 'relationship_manager',
            'foia_officer', 'foia_attorney', 'analyst', 'executive',
        ],
        public_urls=['/login/'],
        auth_urls={
            'admin': _BEACON_COMMON + _BEACON_STAFF + _BEACON_FOIA,
            'agency_admin': _BEACON_COMMON + _BEACON_STAFF,
            'relationship_manager': _BEACON_COMMON + [
                '/companies/', '/companies/contacts/',
                '/interactions/', '/pipeline/', '/notes/',
            ],
            'foia_officer': _BEACON_COMMON + _BEACON_FOIA,
            'foia_attorney': _BEACON_COMMON + _BEACON_FOIA,
            'analyst': _BEACON_COMMON + ['/companies/', '/companies/contacts/'],
            'executive': _BEACON_COMMON + ['/dashboard/'],
        },
        workflows=[
            'test_company_crud',
            'test_foia_workflow',
            'test_interaction_crud',
            'test_pipeline_crud',
            'test_zone_permissions',
        ],
    ),
    'admiralty': Product(
        name='Admiralty',
        repo_dir='beacon',
        settings_module='admiralty.settings',
        live_url='https://admiralty.docklabs.ai',
        demo_roles=['admin', 'foia_officer', 'foia_attorney'],
        public_urls=['/', '/accounts/login/'],
        auth_urls={
            'admin': _ADMIRALTY_ALL + _ADMIRALTY_STAFF,
            'foia_officer': _ADMIRALTY_ALL + ['/foia/review/'],
            'foia_attorney': _ADMIRALTY_ALL + ['/foia/review/'],
        },
        workflows=[
            'test_foia_standalone',
            'test_foia_document_upload',
            'test_foia_full_lifecycle',
        ],
    ),
    'harbor': Product(
        name='Harbor',
        repo_dir='harbor',
        settings_module='harbor.settings',
        live_url='https://harbor.docklabs.ai',
        demo_roles=[
            'admin', 'agency_admin', 'program_officer',
            'fiscal_officer', 'federal_fund_coordinator',
            'reviewer', 'applicant', 'auditor',
        ],
        public_urls=_HARBOR_PUBLIC + ['/auth/login/', '/auth/register/'],
        auth_urls={
            'admin': _HARBOR_COMMON + _HARBOR_STAFF + _HARBOR_APPLICANT,
            'agency_admin': _HARBOR_COMMON + _HARBOR_STAFF,
            'program_officer': _HARBOR_COMMON + [
                '/applications/', '/awards/', '/grants/',
                '/reporting/', '/reviews/', '/auth/notifications/',
            ],
            'fiscal_officer': _HARBOR_COMMON + [
                '/financial/drawdowns/', '/financial/transactions/',
                '/auth/notifications/',
            ],
            'federal_fund_coordinator': _HARBOR_COMMON + [
                '/grants/', '/grants/federal/tracked/',
                '/auth/notifications/',
            ],
            'reviewer': _HARBOR_COMMON + ['/applications/', '/reviews/'],
            'applicant': _HARBOR_COMMON + _HARBOR_APPLICANT,
            'auditor': _HARBOR_COMMON + ['/awards/', '/reporting/'],
        },
        workflows=[
            'test_applicant_workflow',
            'test_staff_review_workflow',
            'test_award_workflow',
            'test_drawdown_workflow',
            'test_reporting_workflow',
            'test_closeout_workflow',
            'test_signature_flow',
        ],
    ),
    'manifest': Product(
        name='Manifest',
        repo_dir='harbor',
        settings_module='manifest.settings',
        live_url='https://manifest.docklabs.ai',
        demo_roles=['admin', 'staff', 'signer'],
        public_urls=['/accounts/login/'],
        auth_urls={
            'admin': [
                '/packets/',
                '/flows/',
                '/roles/',
                '/builder/',
                '/my/',
                '/my/signatures/',
            ],
            'staff': [
                '/packets/',
                '/flows/',
                '/my/',
                '/my/signatures/',
            ],
            'signer': [
                '/my/',
                '/my/signatures/',
            ],
        },
        workflows=['test_signing_flow', 'test_decline_flow'],
    ),
    'bounty': Product(
        name='Bounty',
        repo_dir='bounty',
        settings_module='bounty.settings',
        live_url='https://bounty.docklabs.ai',
        demo_roles=['admin', 'coordinator', 'analyst', 'viewer'],
        public_urls=_BOUNTY_PUBLIC + ['/auth/login/'],
        auth_urls={
            'admin': _BOUNTY_COMMON + _BOUNTY_STAFF,
            'coordinator': _BOUNTY_COMMON + _BOUNTY_STAFF,
            'analyst': _BOUNTY_COMMON,
            'viewer': ['/dashboard/', '/tracked/', '/matching/recommendations/'],
        },
        workflows=[
            'test_opportunity_tracking',
            'test_matching_preferences',
            'test_collaborator_flow',
        ],
    ),
}
