"""URL patterns for the shared settings page.

Mount in product `urls.py`:

    path('settings/', include('keel.settings.urls')),
"""
from django.urls import path

from . import views

app_name = 'keel_settings'

urlpatterns = [
    path('', views.settings_index, name='index'),
    path('<slug:slug>/', views.settings_panel, name='panel'),
]
