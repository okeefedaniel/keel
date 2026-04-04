from django.contrib import admin

from .models import Attachment, DeadLetter, MailboxAddress, Message, Thread


class ThreadInline(admin.TabularInline):
    model = Thread
    extra = 0
    fields = ('subject', 'is_read', 'is_archived', 'updated_at')
    readonly_fields = ('updated_at',)
    show_change_link = True


@admin.register(MailboxAddress)
class MailboxAddressAdmin(admin.ModelAdmin):
    list_display = ('address', 'product', 'display_name', 'is_active', 'created_at')
    list_filter = ('product', 'is_active')
    search_fields = ('address', 'display_name')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ThreadInline]


class MessageInline(admin.StackedInline):
    model = Message
    extra = 0
    fields = ('direction', 'from_address', 'subject', 'sent_at', 'delivery_status')
    readonly_fields = ('direction', 'from_address', 'subject', 'sent_at', 'delivery_status')
    show_change_link = True


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = ('subject', 'mailbox', 'is_read', 'is_archived', 'updated_at')
    list_filter = ('is_read', 'is_archived')
    search_fields = ('subject',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [MessageInline]


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ('filename', 'content_type', 'size_bytes', 'file')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('subject', 'direction', 'from_address', 'delivery_status', 'sent_at')
    list_filter = ('direction', 'delivery_status')
    search_fields = ('subject', 'from_address', 'body_text')
    readonly_fields = (
        'thread', 'direction', 'from_address', 'from_name',
        'to_addresses', 'cc_addresses', 'subject',
        'body_text', 'message_id_header', 'in_reply_to_header',
        'references_header', 'sent_at', 'created_at',
        'sent_by', 'postmark_message_id', 'delivery_detail',
    )
    inlines = [AttachmentInline]


@admin.register(DeadLetter)
class DeadLetterAdmin(admin.ModelAdmin):
    list_display = ('from_address', 'to_address', 'subject', 'reason', 'resolved', 'created_at')
    list_filter = ('reason', 'resolved')
    search_fields = ('from_address', 'to_address', 'subject')
    readonly_fields = ('raw_payload', 'created_at')
    actions = ['mark_resolved']

    @admin.action(description='Mark selected as resolved')
    def mark_resolved(self, request, queryset):
        updated = queryset.update(resolved=True)
        self.message_user(request, f'{updated} dead letter(s) marked as resolved.')
