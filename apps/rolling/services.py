from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.models import log_action
from apps.masters import services as masters_services
from apps.masters.models import CoilMaster, DiameterTravellerMapping
from apps.production import services as production_services
from apps.production.process_registry import get_process

from .models import RollingBatch, RollingBatchCoil


def _create_carrier_lot(batch):
    """Every batch gets its ProductionLot at initiation, not at completion,
    so the carrier the next process initiates against exists for the whole
    life of the batch. The lot sits at the Rolling process until Rolling
    hands it over.

    ProductionLot still requires a ProductionOrder FK, so a placeholder
    order is created alongside it; nothing in the Rover process reads it.
    """
    from apps.master_data.models import MaterialMaster, ProductMaster, UnitOfMeasure
    from apps.production.models import ProductionLot, ProductionOrder

    uom, _ = UnitOfMeasure.objects.get_or_create(code="KG", defaults={"name": "Kilogram"})
    material, _ = MaterialMaster.objects.get_or_create(
        material_code="RM-ROLLING-WIRE",
        defaults={"name": "Rolled Wire (Rolling Output)", "material_type": "wip", "unit_of_measure": uom},
    )
    product, _ = ProductMaster.objects.get_or_create(
        product_code="WIP-ROLLED-WIRE",
        defaults={"name": "Rolled Wire", "unit_of_measure": uom, "raw_material": material},
    )
    order = ProductionOrder.objects.create(
        product=product, planned_quantity=batch.wire_weight_issued_kg, uom="KG", status="in_progress",
        remarks=f"Auto-created from Rolling batch {batch.wire_serial}",
    )
    return ProductionLot.objects.create(
        production_order=order, current_stage=get_process("rolling").slug,
        quantity=batch.wire_weight_issued_kg, source_rolling_batch=batch,
        remarks=f"Wire serial {batch.wire_serial}",
    )


@transaction.atomic
def initiate_rolling_batch(*, traveller_type, traveller_no, finish, required_box, wire_weight_issued_kg,
                            coil_weights, user):
    """coil_weights: list of (coil_id, weight_taken_kg) tuples, one per
    checked coil, matching the 'user enters weight per coil' behavior."""
    if not user.can_operate_stage("rolling"):
        raise PermissionDenied("You are not authorized to initiate a rolling batch.")

    if not coil_weights:
        raise ValidationError("Select at least one coil to issue wire weight from.")

    total_taken = sum((w for _, w in coil_weights), Decimal("0"))
    if total_taken != wire_weight_issued_kg:
        raise ValidationError(
            f"Selected coil weights total {total_taken} kg, which does not match "
            f"the wire weight to issue ({wire_weight_issued_kg} kg)."
        )

    try:
        mapping = DiameterTravellerMapping.objects.select_related("raw_material").get(traveller_type=traveller_type)
    except DiameterTravellerMapping.DoesNotExist:
        raise ValidationError(
            f'No raw material mapping found for traveller type "{traveller_type.name}". '
            "Contact your supervisor before proceeding."
        )

    wire_serial = masters_services.generate_wire_serial()

    batch = RollingBatch(
        wire_serial=wire_serial,
        traveller_type=traveller_type,
        traveller_no=traveller_no,
        finish=finish,
        wire_diameter_mm=mapping.raw_material.diameter_mm,
        f_thickness_mm=mapping.f_thickness_mm,
        f_width_mm=mapping.f_width_mm,
        required_box=required_box,
        wire_weight_issued_kg=wire_weight_issued_kg,
        status="In Progress",
        created_by=user,
    )
    batch.full_clean()
    batch.save()
    _create_carrier_lot(batch)

    for coil_id, weight_taken in coil_weights:
        coil = CoilMaster.objects.select_for_update().get(pk=coil_id)
        if coil.raw_material_id != mapping.raw_material_id:
            raise ValidationError(
                f"Coil {coil.coil_display_number} is diameter {coil.raw_material_id}, "
                f"but this traveller type requires {mapping.raw_material_id}."
            )
        masters_services.consume_coil(coil, weight_taken)
        RollingBatchCoil.objects.create(batch=batch, coil=coil, weight_taken_kg=weight_taken)

    log_action(
        user, "create", batch,
        description=f"Rolling batch {batch.wire_serial} initiated",
        metadata={"traveller_type": traveller_type.name, "wire_weight_issued_kg": str(wire_weight_issued_kg)},
    )
    return batch


@transaction.atomic
def complete_rolling_batch(batch, *, rolled_thickness_mm, rolled_width_mm, finished_weight_kg, user,
                           rack_slot=None):
    if not user.can_approve():
        raise PermissionDenied("You are not authorized to complete a rolling batch.")
    if batch.status == "Completed":
        raise ValidationError("This batch has already been completed.")
    if finished_weight_kg > batch.wire_weight_issued_kg:
        raise ValidationError("Output weight cannot exceed the wire weight issued.")

    batch.rolled_thickness_mm = rolled_thickness_mm
    batch.rolled_width_mm = rolled_width_mm
    batch.finished_weight_kg = finished_weight_kg
    # The rolled wire goes onto a slot of the storage zone that follows
    # Rolling; `handover` reads the operator's choice from here and falls
    # back to the next free slot when nothing was picked.
    batch._rack_slot = rack_slot

    # `handover` stamps the status, completion time and wastage, stages the
    # output as WIP for whichever process follows Rolling in the registry
    # and moves the carrier lot onto it.
    production_services.handover(batch, get_process("rolling"), user)
    return batch
