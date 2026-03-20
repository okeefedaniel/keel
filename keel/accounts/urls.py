"""Keel accounts URL configuration.

Include in your product's urls.py:

    from django.urls import include, path
    urlpatterns = [
        path('keel/', include('keel.accounts.urls')),
        # Invitation acceptance lives at /invite/ for clean URLs
        path('invite/<str:token>/', 'keel.accounts.views.accept_invitation', name='accept_invitation'),
    ]
"""
from django.urls import path

from . import views

app_name = 'keel_accounts'

urlpatterns = [
    # Admin console
    path('', views.dashboard, name='dashboard'),
    path('users/', views.user_list, name='user_list'),
    path('users/<uuid:user_id>/', views.user_detail, name='user_detail'),
    path('users/<uuid:user_id>/grant/', views.grant_access, name='grant_access'),
    path('access/<uuid:access_id>/revoke/', views.revoke_access, name='revoke_access'),

    # Invitations
    path('invitations/', views.invitation_list, name='invitation_list'),
    path('invitations/send/', views.send_invitation, name='send_invitation'),
    path('invitations/<uuid:invitation_id>/revoke/', views.revoke_invitation, name='revoke_invitation'),

    # Public invitation acceptance
    path('invite/<str:token>/', views.accept_invitation, name='accept_invitation'),
]
