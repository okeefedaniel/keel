"""URL routes for keel.mentions.

Mount in your product's root urls.py:

    path('keel/mentions/', include('keel.mentions.urls')),
"""
from __future__ import annotations

from django.urls import path

from .views import mentions_search

app_name = 'keel_mentions'

urlpatterns = [
    path('search/', mentions_search, name='mentions_search'),
]
