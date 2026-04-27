from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0007_notificationpreference_channel_boswell'),
    ]

    operations = [
        migrations.AddField(
            model_name='keeluser',
            name='last_logout_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
