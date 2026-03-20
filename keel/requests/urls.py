"""Change request URL configuration.

Include in your product's urls.py:

    from django.urls import include, path
    urlpatterns = [
        path('keel/requests/', include('keel.requests.urls')),
    ]
"""
from django.urls import path

from . import views

app_name = 'keel_requests'

urlpatterns = [
    # Admin console
    path('', views.dashboard, name='dashboard'),
    path('list/', views.request_list, name='request_list'),
    path('<uuid:request_id>/', views.request_detail, name='request_detail'),
    path('<uuid:request_id>/approve/', views.approve_request, name='approve_request'),
    path('<uuid:request_id>/decline/', views.decline_request, name='decline_request'),
    path('<uuid:request_id>/implemented/', views.mark_implemented, name='mark_implemented'),
    path('<uuid:request_id>/prompt/', views.get_prompt, name='get_prompt'),

    # Beta user submission
    path('submit/', views.submit_request, name='submit_request'),
]
