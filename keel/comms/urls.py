"""URL configuration for keel.comms."""
from django.urls import path

from . import views

app_name = 'comms'

urlpatterns = [
    # Postmark webhooks (no auth — verified by token)
    path('webhook/postmark/inbound/', views.postmark_inbound_webhook, name='postmark_inbound'),
    path('webhook/postmark/delivery/', views.postmark_delivery_webhook, name='postmark_delivery'),
    path('webhook/postmark/bounce/', views.postmark_bounce_webhook, name='postmark_bounce'),

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
