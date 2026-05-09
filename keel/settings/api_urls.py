"""URL patterns for the keel.settings API (Keel IdP side only)."""
from django.urls import path

from . import api_views

urlpatterns = [
    path('profile/', api_views.profile_update, name='api_profile_update'),
]
