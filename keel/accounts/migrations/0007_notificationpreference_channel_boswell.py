from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0006_add_beta_tester_to_invitation'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationpreference',
            name='channel_boswell',
            field=models.BooleanField(default=False),
        ),
    ]
