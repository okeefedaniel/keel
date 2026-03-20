"""URL configuration for keel.docklabs.ai."""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path


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

    # Keel admin modules
    path('keel/accounts/', include('keel.accounts.urls')),
    path('keel/requests/', include('keel.requests.urls')),
    path('keel/notifications/', include('keel.notifications.urls')),

    # Invitation acceptance (clean URL)
    path('invite/<str:token>/', include([])),  # handled by keel.accounts.urls

    # Django admin (fallback)
    path('admin/', admin.site.urls),
]
