"""URL configuration for keel.activity.

Currently exposes a single endpoint — the watcher toggle used by the
``{% follow_button %}`` template tag. Mount via include() in each product:

    urlpatterns = [
        ...
        path('activity/', include('keel.activity.urls')),
    ]
"""
from django.urls import path

from keel.activity.views import set_categories, toggle_follow

app_name = 'keel_activity'

urlpatterns = [
    path('follow/toggle/', toggle_follow, name='toggle_follow'),
    path('follow/categories/', set_categories, name='set_categories'),
]
