"""Stamp `completed_at` on stage records that finished before the field existed.

The incoming rows of each process are ordered by the moment the previous
process handed the material over. Records completed before `completed_at`
was added carry NULL, which would sort them apart from everything else, so
they take their last-updated time as the best available approximation.
"""

from django.db import migrations
from django.db.models import F

STAGE_MODELS = [
    ("forming", "FormingTransaction"),
    ("heat_treatment", "HeatTreatmentTransaction"),
    ("finishing", "FinishingTransaction"),
]


def backfill(apps, schema_editor):
    for app_label, model_name in STAGE_MODELS:
        model = apps.get_model(app_label, model_name)
        model.objects.filter(status="completed", completed_at__isnull=True).update(
            completed_at=F("updated_at")
        )


def noop(apps, schema_editor):
    """Leave the stamps in place; clearing them would only lose information."""


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0002_productionlot_source_rolling_batch"),
        ("forming", "0006_formingtransaction_completed_at"),
        ("heat_treatment", "0006_heattreatmenttransaction_completed_at"),
        ("finishing", "0006_finishingtransaction_completed_at"),
    ]

    operations = [migrations.RunPython(backfill, noop)]
