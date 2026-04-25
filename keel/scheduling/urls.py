from django.urls import path

from keel.scheduling import views

app_name = 'keel_scheduling'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('<slug:slug>/', views.job_detail, name='job_detail'),
    path('<slug:slug>/update/', views.update_job, name='update_job'),
]
