"""URL patterns for the shared notification views.

Usage in product urls.py:
    path('notifications/', include('keel.notifications.urls')),
"""
from django.urls import path

from . import views

app_name = 'keel_notifications'

urlpatterns = [
    path('', views.notification_list, name='list'),
    path('<uuid:pk>/read/', views.mark_read, name='mark_read'),
    path('mark-all-read/', views.mark_all_read, name='mark_all_read'),
    path('preferences/', views.preferences, name='preferences'),
]
