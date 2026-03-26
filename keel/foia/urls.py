"""FOIA export URL patterns.

Include in your product's urls.py:
    path('foia/', include('keel.foia.urls'))
"""
from django.urls import path

from . import views

app_name = 'keel_foia'

urlpatterns = [
    path('export/', views.export_to_foia, name='foia_export'),
]
