from django.db import migrations, models


class Migration(migrations.Migration):
    """Generalize the Postmark-specific provider id to a vendor-neutral field.

    keel.comms now transports over Resend instead of Postmark. No product
    ships real comms data yet, but RenameField (not remove+add) keeps the
    column and any rows intact.
    """

    dependencies = [
        ('keel_comms', '0003_message_comms_msg_search_gin'),
    ]

    operations = [
        migrations.RenameField(
            model_name='message',
            old_name='postmark_message_id',
            new_name='provider_message_id',
        ),
        migrations.AlterField(
            model_name='message',
            name='provider_message_id',
            field=models.CharField(blank=True, db_index=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='deadletter',
            name='raw_payload',
            field=models.JSONField(help_text='Full inbound webhook / received-email body.'),
        ),
    ]
