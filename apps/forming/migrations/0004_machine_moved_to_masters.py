"""Repoint the machine FK at `masters.Machine`. Same table, same column -
only the app label the FK resolves through changes (see masters.0005_machine).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("forming", "0003_formingtransaction_operation_date_and_more"),
        ("masters", "0005_machine"),
    ]

    operations = [
        migrations.AlterField(
            model_name="formingtransaction",
            name="machine",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="+", to="masters.machine"
            ),
        ),
    ]
