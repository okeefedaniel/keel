from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0013_alter_auditlog_action'),
    ]

    operations = [
        migrations.AddField(
            model_name='keeluser',
            name='timezone',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='keeluser',
            name='locale',
            field=models.CharField(blank=True, max_length=10),
        ),
    ]
