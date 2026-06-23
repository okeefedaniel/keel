from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0022_auditlog_user_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='invitation',
            name='cc_email',
            field=models.EmailField(
                blank=True,
                help_text=(
                    "Optional address CC'd on the invitation email so an admin "
                    "can see exactly what the invitee received. Recorded per "
                    "batch."
                ),
                max_length=254,
            ),
        ),
    ]
