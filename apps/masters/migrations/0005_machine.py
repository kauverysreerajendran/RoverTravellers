"""Move Machine from `master_data` to `masters`, where the other master
tables live. State-only: the row data and the physical table are untouched
here - 0006 renames the table once every FK points at the new app label.
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0004_alter_travellerno_label"),
        ("master_data", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="Machine",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("is_active", models.BooleanField(db_index=True, default=True)),
                        ("code", models.CharField(max_length=20, unique=True)),
                        ("name", models.CharField(max_length=150)),
                        (
                            "stage",
                            models.CharField(
                                choices=[
                                    ("rolling", "Rolling"),
                                    ("forming", "Forming"),
                                    ("heat_treatment", "Heat Treatment"),
                                    ("finishing", "Finishing"),
                                    ("general", "General"),
                                ],
                                default="general",
                                max_length=20,
                            ),
                        ),
                        ("is_operational", models.BooleanField(default=True)),
                        (
                            "created_by",
                            models.ForeignKey(
                                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                related_name="+", to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "updated_by",
                            models.ForeignKey(
                                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                related_name="+", to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "plant",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="machines", to="master_data.plant",
                            ),
                        ),
                    ],
                    options={"ordering": ["code"], "db_table": "master_data_machine"},
                ),
            ],
        ),
    ]
