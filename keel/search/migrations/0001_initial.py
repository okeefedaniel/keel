"""Enable pg_trgm extension for trigram similarity search."""
from django.db import connection, migrations


def create_pg_trgm(apps, schema_editor):
    """Enable pg_trgm on PostgreSQL only. Skipped on SQLite."""
    if connection.vendor == 'postgresql':
        schema_editor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm;')


def drop_pg_trgm(apps, schema_editor):
    if connection.vendor == 'postgresql':
        schema_editor.execute('DROP EXTENSION IF EXISTS pg_trgm;')


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.RunPython(create_pg_trgm, drop_pg_trgm),
    ]
