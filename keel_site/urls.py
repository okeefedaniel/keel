"""URL configuration for keel.docklabs.ai."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path

from . import tools


def home(request):
    if request.user.is_authenticated:
        return redirect('keel_requests:dashboard')
    return redirect('login')


urlpatterns = [
    # Home redirects to requests dashboard
    path('', home, name='home'),
    path('dashboard/', home, name='dashboard'),

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

    # Keel admin modules
    path('keel/accounts/', include('keel.accounts.urls')),
    path('keel/requests/', include('keel.requests.urls')),
    path('keel/notifications/', include('keel.notifications.urls')),

    # Invitation acceptance (clean URL)
    path('invite/<str:token>/', include([])),  # handled by keel.accounts.urls

    # Tools (test suite, UI audit)
    path('tools/', tools.tools_dashboard, name='tools_dashboard'),
    path('tools/run/', tools.run_tool, name='tools_run'),
    path('tools/run/<str:run_id>/', tools.run_detail, name='tools_run_detail'),

    # Django admin (fallback)
    path('admin/', admin.site.urls),
]
