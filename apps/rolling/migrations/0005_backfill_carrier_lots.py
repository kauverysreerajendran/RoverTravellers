"""Give every existing Rolling batch its carrier ProductionLot.

Carrier lots used to be created when a batch was *completed*. They are now
created when it is *initiated*, so that the lot the next process initiates
against exists for the whole life of the batch. Without this backfill, a
batch that was already In Progress when this migration ran would have no
lot to hand over and could never be completed.
"""

from django.db import migrations


def create_missing_carrier_lots(apps, schema_editor):
    RollingBatch = apps.get_model("rolling", "RollingBatch")
    ProductionLot = apps.get_model("production", "ProductionLot")
    ProductionOrder = apps.get_model("production", "ProductionOrder")
    ProductMaster = apps.get_model("master_data", "ProductMaster")
    MaterialMaster = apps.get_model("master_data", "MaterialMaster")
    UnitOfMeasure = apps.get_model("master_data", "UnitOfMeasure")

    orphans = list(RollingBatch.objects.filter(production_lots__isnull=True))
    if not orphans:
        return

    uom, _ = UnitOfMeasure.objects.get_or_create(code="KG", defaults={"name": "Kilogram"})
    material, _ = MaterialMaster.objects.get_or_create(
        material_code="RM-ROLLING-WIRE",
        defaults={"name": "Rolled Wire (Rolling Output)", "material_type": "wip", "unit_of_measure": uom},
    )
    product, _ = ProductMaster.objects.get_or_create(
        product_code="WIP-ROLLED-WIRE",
        defaults={"name": "Rolled Wire", "unit_of_measure": uom, "raw_material": material},
    )

    # A completed batch has already handed its material to the next process;
    # an open one is still at Rolling.
    for index, batch in enumerate(orphans, start=1):
        completed = batch.status == "Completed"
        quantity = (batch.finished_weight_kg if completed else None) or batch.wire_weight_issued_kg
        order = ProductionOrder.objects.create(
            order_number=f"PO-BACKFILL-{index:05d}",
            product=product, planned_quantity=quantity, uom="KG", status="in_progress",
            remarks=f"Backfilled for Rolling batch {batch.wire_serial}",
        )
        ProductionLot.objects.create(
            lot_number=f"LOT-BACKFILL-{index:05d}",
            production_order=order,
            current_stage="forming" if completed else "rolling",
            quantity=quantity,
            source_rolling_batch=batch,
            remarks=f"Wire serial {batch.wire_serial}",
        )


def noop(apps, schema_editor):
    """Backfilled lots are indistinguishable from real ones once created;
    deleting them on reverse would destroy traceability."""


class Migration(migrations.Migration):
    dependencies = [
        ("rolling", "0004_alter_rollingbatch_f_thickness_mm_and_more"),
        ("production", "0002_productionlot_source_rolling_batch"),
        ("master_data", "0001_initial"),
    ]

    operations = [migrations.RunPython(create_missing_carrier_lots, noop)]
