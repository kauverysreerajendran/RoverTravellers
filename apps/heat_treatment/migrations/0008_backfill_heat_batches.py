"""Give every existing Heat Treatment transaction a Heat Batch.

Before the batch grouping, a furnace load was recorded as a free-text
`batch_number` repeated on each transaction. Every distinct non-empty one
becomes a `HeatBatch` here and its transactions are linked to it, so the
history reads the same way through the new tables.

Legacy numbers (HT-2604-001) do not match the new B001 format: they are
preserved as they were written rather than renumbered, because they are
what the shop floor recorded. Validation applies to batches made from
here on.
"""

from django.db import migrations

# The batch numbering the business asked for: B001, B002, ... The pattern
# is stored as master data so it can change without a deployment; this
# only puts the first row there. The process it belongs to is resolved
# from the registry, never spelled out.
DEFAULT_REGEX = r"^B\d{3}$"
DEFAULT_PREFIX = "B"
DEFAULT_PAD = 3


def _process_slug():
    from apps.production.process_registry import process_for_app_label

    process = process_for_app_label("heat_treatment")
    return process.slug if process else ""


def seed_format_and_backfill(apps, schema_editor):
    BatchNoFormat = apps.get_model("masters", "BatchNoFormat")
    HeatBatch = apps.get_model("heat_treatment", "HeatBatch")
    HeatTreatmentTransaction = apps.get_model("heat_treatment", "HeatTreatmentTransaction")

    slug = _process_slug()
    if slug and not BatchNoFormat.objects.filter(process_slug=slug).exists():
        BatchNoFormat.objects.create(
            process_slug=slug, regex=DEFAULT_REGEX, prefix=DEFAULT_PREFIX, pad=DEFAULT_PAD, is_active=True
        )

    import secrets

    numbers = (
        HeatTreatmentTransaction.objects.exclude(batch_number="")
        .exclude(batch_number__isnull=True)
        .values_list("batch_number", flat=True)
        .distinct()
    )
    for batch_number in numbers:
        batch, _ = HeatBatch.objects.get_or_create(
            batch_no=batch_number.strip().upper(),
            defaults={"status": "in_progress", "qr_token": secrets.token_urlsafe(16)[:22]},
        )
        rows = HeatTreatmentTransaction.objects.filter(batch_number=batch_number)
        rows.update(heat_batch=batch)
        # A load whose work has all finished is a finished load.
        if not rows.exclude(status__in=["completed", "cancelled", "rejected"]).exists():
            last = rows.order_by("-completed_at").first()
            HeatBatch.objects.filter(pk=batch.pk).update(
                status="completed", completed_at=last.completed_at if last else None
            )


def unlink(apps, schema_editor):
    HeatTreatmentTransaction = apps.get_model("heat_treatment", "HeatTreatmentTransaction")
    HeatTreatmentTransaction.objects.update(heat_batch=None)
    apps.get_model("heat_treatment", "HeatBatch").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("heat_treatment", "0007_heatbatch_heattreatmenttransaction_heat_batch"),
        ("masters", "0008_batchnoformat"),
    ]

    operations = [migrations.RunPython(seed_format_and_backfill, unlink)]
