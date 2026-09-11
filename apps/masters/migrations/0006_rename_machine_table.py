"""Rename the physical table to match its new app: master_data_machine ->
masters_machine. Postgres carries foreign-key constraints across a table
rename, so no data moves and no constraint is rebuilt.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0005_machine"),
        ("master_data", "0002_delete_machine"),
    ]

    operations = [
        migrations.AlterModelTable(name="machine", table=None),
    ]
