"""Canonical DockLabs fleet product list.

Previously duplicated across nine product ``settings.py`` files. Any
product add/rename/URL change required a nine-file edit with high drift
risk (Helm feed endpoints, fleet switcher links, Keel SSO redirects).

Products should import ``FLEET`` and assign it:

    from keel.core.fleet import FLEET
    KEEL_FLEET_PRODUCTS = FLEET

``KEEL_FLEET_PRODUCTS`` remains the setting name the rest of the suite
reads; only the source of truth is centralised here.
"""

FLEET = [
    {'name': 'Helm',      'label': 'Helm',      'code': 'helm',
     'url': 'https://helm.docklabs.ai/dashboard/'},
    {'name': 'Harbor',    'label': 'Harbor',    'code': 'harbor',
     'url': 'https://harbor.docklabs.ai/dashboard/'},
    {'name': 'Beacon',    'label': 'Beacon',    'code': 'beacon',
     'url': 'https://beacon.docklabs.ai/dashboard/'},
    {'name': 'Lookout',   'label': 'Lookout',   'code': 'lookout',
     'url': 'https://lookout.docklabs.ai/dashboard/'},
    {'name': 'Bounty',    'label': 'Bounty',    'code': 'bounty',
     'url': 'https://bounty.docklabs.ai/dashboard/'},
    {'name': 'Admiralty', 'label': 'Admiralty', 'code': 'admiralty',
     'url': 'https://admiralty.docklabs.ai/dashboard/'},
    {'name': 'Purser',    'label': 'Purser',    'code': 'purser',
     'url': 'https://purser.docklabs.ai/dashboard/'},
    {'name': 'Manifest',  'label': 'Manifest',  'code': 'manifest',
     'url': 'https://manifest.docklabs.ai/dashboard/'},
    {'name': 'Yeoman',    'label': 'Yeoman',    'code': 'yeoman',
     'url': 'https://yeoman.docklabs.ai/dashboard/'},
]
