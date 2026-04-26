"""Canonical DockLabs fleet product list.

Previously duplicated across nine product ``settings.py`` files. Any
product add/rename/URL change required a nine-file edit with high drift
risk (Helm feed endpoints, fleet switcher links, Keel SSO redirects).

Products should import ``FLEET`` and assign it:

    from keel.core.fleet import FLEET
    KEEL_FLEET_PRODUCTS = FLEET

``KEEL_FLEET_PRODUCTS`` remains the setting name the rest of the suite
reads; only the source of truth is centralised here.

Each entry carries ``icon`` (a Bootstrap Icons class) and ``tagline``
(short capability label) so the fleet grid on every landing page can
render a real, distinct tile per product. Audit F-010.
"""

FLEET = [
    {'name': 'Helm',      'label': 'Helm',      'code': 'helm',
     'icon': 'bi-compass',         'tagline': 'Executive Dashboard',
     'url': 'https://helm.docklabs.ai/dashboard/'},
    {'name': 'Harbor',    'label': 'Harbor',    'code': 'harbor',
     'icon': 'bi-bank2',           'tagline': 'State Grants',
     'url': 'https://harbor.docklabs.ai/dashboard/'},
    {'name': 'Beacon',    'label': 'Beacon',    'code': 'beacon',
     'icon': 'bi-broadcast',       'tagline': 'CRM',
     'url': 'https://beacon.docklabs.ai/dashboard/'},
    {'name': 'Lookout',   'label': 'Lookout',   'code': 'lookout',
     'icon': 'bi-binoculars',      'tagline': 'Legislative',
     'url': 'https://lookout.docklabs.ai/dashboard/'},
    {'name': 'Bounty',    'label': 'Bounty',    'code': 'bounty',
     'icon': 'bi-globe',           'tagline': 'Federal Funds',
     'url': 'https://bounty.docklabs.ai/dashboard/'},
    {'name': 'Admiralty', 'label': 'Admiralty', 'code': 'admiralty',
     'icon': 'bi-shield-check',    'tagline': 'FOIA',
     'url': 'https://admiralty.docklabs.ai/dashboard/'},
    {'name': 'Purser',    'label': 'Purser',    'code': 'purser',
     'icon': 'bi-safe2',           'tagline': 'Finance',
     'url': 'https://purser.docklabs.ai/dashboard/'},
    {'name': 'Manifest',  'label': 'Manifest',  'code': 'manifest',
     'icon': 'bi-pen',             'tagline': 'Signing',
     'url': 'https://manifest.docklabs.ai/dashboard/'},
    {'name': 'Yeoman',    'label': 'Yeoman',    'code': 'yeoman',
     'icon': 'bi-calendar-event',  'tagline': 'Scheduling',
     'url': 'https://yeoman.docklabs.ai/dashboard/'},
]
