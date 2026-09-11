from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CoilMaster, DiameterMaster, WireSerialMaster


def peek_next_wire_serial():
    """The serial the next batch will receive, without consuming it."""
    return WireSerialMaster.objects.filter(status="Available").order_by("sort_order").first()


@transaction.atomic
def generate_wire_serial() -> str:
    """Claims the next Available serial from the wire serial master, in
    issue order. Row-locked: without FOR UPDATE two concurrent submissions
    could be handed the same serial, corrupting batch traceability."""
    serial = (
        WireSerialMaster.objects.select_for_update(skip_locked=True)
        .filter(status="Available")
        .order_by("sort_order")
        .first()
    )
    if serial is None:
        raise ValidationError(
            "No wire serials remain in the master. Load the next prefix block "
            "(e.g. SD01-SD1000) before starting another rolling batch."
        )

    serial.status = "Used"
    serial.used_at = timezone.now()
    serial.save(update_fields=["status", "used_at"])
    return serial.serial_no


@transaction.atomic
def receive_coil(*, raw_material: DiameterMaster, weight_kg: Decimal, rack=None, supplier="", received_date=None):
    coil = CoilMaster(
        raw_material=raw_material,
        coil_display_number=CoilMaster.next_display_number(raw_material),
        weight_kg=weight_kg,
        status="In Stock",
        rack=rack,
        supplier=supplier,
        received_date=received_date,
    )
    coil.full_clean()
    coil.save()
    raw_material.recalculate_stock()
    return coil


@transaction.atomic
def consume_coil(coil: CoilMaster, weight_taken_kg: Decimal):
    coil = CoilMaster.objects.select_for_update().get(pk=coil.pk)
    if coil.status != "In Stock":
        raise ValidationError(f"Coil {coil.coil_display_number} is not available (status: {coil.status}).")
    if weight_taken_kg <= 0:
        raise ValidationError("Weight taken from a coil must be greater than zero.")
    if weight_taken_kg > coil.weight_kg:
        raise ValidationError(
            f"Cannot take {weight_taken_kg} kg from Coil {coil.coil_display_number}; "
            f"only {coil.weight_kg} kg remaining."
        )
    coil.weight_kg -= weight_taken_kg
    if coil.weight_kg == 0:
        coil.status = "Consumed"
    coil.save(update_fields=["weight_kg", "status"])
    coil.raw_material.recalculate_stock()
    return coil
