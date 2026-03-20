"""ASGI config for keel.docklabs.ai."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'keel_site.settings')

application = get_asgi_application()
