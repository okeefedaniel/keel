"""URL configuration for keel.signatures.

Products mount this at ``/keel/signatures/`` so Manifest can reach the
completion webhook at a predictable path suite-wide:

    urlpatterns = [
        ...
        path('keel/signatures/', include('keel.signatures.urls')),
    ]
"""
from django.urls import path

from . import views

app_name = 'keel_signatures'

urlpatterns = [
    path('webhook/', views.webhook, name='webhook'),
]
