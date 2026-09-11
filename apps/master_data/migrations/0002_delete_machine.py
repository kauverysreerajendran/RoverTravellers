"""Drop `master_data.Machine` from the migration state only - the model now
lives in `masters` (see masters.0005_machine) and the table is still the
same one, so nothing is dropped from the database.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("master_data", "0001_initial"),
        ("masters", "0005_machine"),
        # Every FK must already point at masters.Machine before the old
        # model can leave the state graph.
        ("forming", "0004_machine_moved_to_masters"),
        ("heat_treatment", "0004_machine_moved_to_masters"),
        ("finishing", "0004_machine_moved_to_masters"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[migrations.DeleteModel(name="Machine")],
        ),
    ]
