"""URL routes for keel.ai — mount under ``/api/v1/ai/``.

Usage in Keel's root urls.py::

    path('api/v1/ai/', include('keel.ai.urls')),
"""
from django.urls import path

from .views import ai_key_view

app_name = 'keel_ai'

urlpatterns = [
    path('key/', ai_key_view, name='key'),
]
