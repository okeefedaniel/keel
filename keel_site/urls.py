"""URL configuration for keel.docklabs.ai."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path

from keel.requests.views import api_ingest
from . import dashboard, notifications_admin, tools


def home(request):
    if request.user.is_authenticated:
        return redirect('platform_dashboard')
    return redirect('login')


urlpatterns = [
    # Home → platform dashboard
    path('', home, name='home'),
    path('dashboard/', dashboard.platform_dashboard, name='platform_dashboard'),
    path('api/activity/', dashboard.activity_feed_api, name='activity_feed_api'),

    # Public API (cross-origin, API-key authenticated)
    path('api/requests/ingest/', api_ingest, name='api_ingest'),
    path('api/notifications/config/', notifications_admin.api_notification_config, name='api_notification_config'),

    # Auth
    path('accounts/login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/password/', auth_views.PasswordChangeView.as_view(
        template_name='password_change.html',
        success_url='/accounts/password/done/',
    ), name='password_change'),
    path('accounts/password/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='password_change_done.html',
    ), name='password_change_done'),

    # Password reset (forgot password)
    path('accounts/password/reset/', auth_views.PasswordResetView.as_view(
        template_name='password_reset.html',
        email_template_name='password_reset_email.html',
        subject_template_name='password_reset_subject.txt',
        success_url='/accounts/password/reset/sent/',
    ), name='password_reset'),
    path('accounts/password/reset/sent/', auth_views.PasswordResetDoneView.as_view(
        template_name='password_reset_sent.html',
    ), name='password_reset_done'),
    path('accounts/password/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='password_reset_confirm.html',
        success_url='/accounts/password/reset/complete/',
    ), name='password_reset_confirm'),
    path('accounts/password/reset/complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='password_reset_complete.html',
    ), name='password_reset_complete'),

    # Keel admin modules
    path('keel/accounts/', include('keel.accounts.urls')),
    path('keel/requests/', include('keel.requests.urls')),
    path('keel/notifications/', include('keel.notifications.urls')),

    # Invitation acceptance (clean URL)
    path('invite/<str:token>/', include([])),  # handled by keel.accounts.urls

    # Notification flow & routing
    path('notifications/flow/', notifications_admin.notification_flow, name='notification_flow'),
    path('notifications/flow/update/', notifications_admin.update_notification_type, name='notification_update'),

    # Tools (test suite, UI audit)
    path('tools/', tools.tools_dashboard, name='tools_dashboard'),
    path('tools/run/', tools.run_tool, name='tools_run'),
    path('tools/run/<str:run_id>/', tools.run_detail, name='tools_run_detail'),

    # Django admin (fallback)
    path('admin/', admin.site.urls),
]
