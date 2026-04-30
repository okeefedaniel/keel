"""Default URL include for the canary endpoint.

Mount at the product's preferred path::

    # product/urls.py
    path('api/v1/metrics/', include('keel.ops.urls')),
"""
from django.urls import path

from keel.ops.views import metrics

app_name = 'keel_ops'

urlpatterns = [
    path('', metrics, name='canary'),
]
