"""URL patterns for FOIA export — include in any product's urls.py.

    path('keel/', include('keel.core.foia_urls')),
"""
from django.urls import path

from .foia_export import foia_export_view

app_name = 'keel_foia'

urlpatterns = [
    path('foia-export/', foia_export_view, name='foia_export'),
]
