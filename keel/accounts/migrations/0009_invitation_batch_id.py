from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0008_keeluser_last_logout_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='invitation',
            name='batch_id',
            field=models.UUIDField(
                null=True,
                blank=True,
                db_index=True,
                help_text='Groups invitations created in the same admin submission so that '
                          'accepting any token in the batch accepts all of them.',
            ),
        ),
    ]
