"""URL configuration for keel.comms."""
from django.urls import path

from . import views

app_name = 'comms'

urlpatterns = [
    # Resend webhook — single endpoint for all event types (inbound mail +
    # outbound delivery status), verified by Svix signature.
    path('webhook/resend/', views.resend_webhook, name='resend_webhook'),

    # htmx UI views (staff only)
    path('<uuid:mailbox_id>/', views.comms_panel, name='panel'),
    path('<uuid:mailbox_id>/compose/', views.compose_form, name='compose'),
    path('<uuid:mailbox_id>/send/', views.send_compose, name='send'),
    path('thread/<uuid:thread_id>/', views.thread_detail, name='thread_detail'),

    # Export (FOIA compliance)
    path('export/message/<uuid:message_id>/', views.export_message, name='export_message'),
    path('export/thread/<uuid:thread_id>/', views.export_thread, name='export_thread'),

    # Search
    path('search/', views.search_messages, name='search'),
]
