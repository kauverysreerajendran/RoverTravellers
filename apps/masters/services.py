from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    CoilMaster,
    DiameterMaster,
    RackPlacement,
    RackSlot,
    RackZone,
    WireSerialMaster,
    row_letter,
)


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


# ---------------------------------------------------------------------------
# Storage rack zones. A zone belongs to the process that places material on
# it, looked up by `process.slug` at run time - no stage name appears here.
# Placement and release are row-locked: two operators completing at the same
# moment must not be handed the same empty slot.
# ---------------------------------------------------------------------------


def zone_for_process(process):
    """The active zone material is placed on when `process` completes (or,
    for the terminal process, receives). None when the process has no
    storage zone, which is the normal case for most of the line."""
    if process is None:
        return None
    slug = getattr(process, "slug", process)
    return RackZone.objects.filter(process_slug=slug, is_active=True).order_by("code").first()


def slots_queryset(zone):
    return RackSlot.objects.filter(zone=zone, rack__is_active=True).select_related("rack", "zone")


def next_free_slot(zone, *, lock=False):
    """The first empty slot in rack -> row -> column order, so a zone fills
    predictably from FR-01-A1 onwards rather than at random."""
    if zone is None:
        return None
    qs = slots_queryset(zone).filter(lot__isnull=True).order_by("rack__position", "row", "column")
    if lock:
        qs = qs.select_for_update(of=("self",))
    return qs.first()


def open_placement(zone, lot):
    """The placement row for material currently sitting in `zone`."""
    if zone is None or lot is None:
        return None
    return (
        RackPlacement.objects.filter(slot__zone=zone, lot=lot, released_at__isnull=True)
        .select_related("slot", "slot__rack", "placed_by")
        .order_by("-placed_at")
        .first()
    )


def slot_for_lot(zone, lot):
    """The slot `lot` occupies in `zone`, or None."""
    if zone is None or lot is None:
        return None
    return slots_queryset(zone).filter(lot=lot).first()


@transaction.atomic
def place_lot(zone, lot, user, slot=None):
    """Put `lot` on `zone`, on `slot` when the operator picked one and on
    the next free slot otherwise.

    Idempotent: a lot already sitting in this zone keeps its slot rather
    than taking a second one (the database forbids two slots per zone for
    one lot anyway), so re-running a backfill or double-submitting a
    completion cannot lose track of where the material is.
    """
    if zone is None:
        raise ValidationError("No storage zone was given to place this material on.")
    if lot is None:
        raise ValidationError("Material cannot be placed on a rack without a lot to trace it by.")

    existing = slot_for_lot(zone, lot)
    if existing is not None:
        return existing

    if slot is not None:
        slot = RackSlot.objects.select_for_update().select_related("rack", "zone").get(pk=slot.pk)
        if slot.zone_id != zone.pk:
            raise ValidationError(f"{slot.label} is not a slot in {zone.name}.")
        if slot.lot_id is not None:
            raise ValidationError(f"{slot.label} is already occupied. Pick another slot in {zone.name}.")
    else:
        slot = next_free_slot(zone, lock=True)
    if slot is None:
        raise ValidationError(f"No empty slot in {zone.name}")

    placed_at = timezone.now()
    slot.lot = lot
    slot.placed_at = placed_at
    slot.placed_by = user
    slot.save(update_fields=["lot", "placed_at", "placed_by"])
    RackPlacement.objects.create(slot=slot, lot=lot, placed_at=placed_at, placed_by=user)
    return slot


@transaction.atomic
def release_lot(zone, lot, user, reason=""):
    """Take `lot` off `zone` and close its placement history. Returns the
    slot it vacated, or None when it was not on this zone - releasing
    material that was never placed is not an error, so a database seeded
    before the zones existed still moves through the line."""
    if zone is None or lot is None:
        return None

    slot = slots_queryset(zone).filter(lot=lot).select_for_update(of=("self",)).first()
    released_at = timezone.now()
    RackPlacement.objects.filter(slot__zone=zone, lot=lot, released_at__isnull=True).update(
        released_at=released_at, released_by=user.pk if user else None, released_reason=reason
    )
    if slot is None:
        return None
    slot.lot = None
    slot.placed_at = None
    slot.placed_by = None
    slot.save(update_fields=["lot", "placed_at", "placed_by"])
    return slot


def _occupant_weights(zone, lots):
    """lot pk -> the weight the placing process handed over, in two queries.

    The weight shown on a slot is the output weight of the record that put
    the material there, reached through the zone's process and its declared
    `handover_lot_path` - so this works for Rolling's batches and for
    Finished Goods stock without naming either.
    """
    process = zone.process
    if process is None or not lots:
        return {}
    path = process.handover_lot_path
    records = list(process.complete_queryset(None).filter(**{f"{path}__in": lots}))
    if not records:
        return {}
    lot_by_record = dict(
        process.model.objects.filter(pk__in=[record.pk for record in records]).values_list("pk", path)
    )
    return {
        lot_by_record[record.pk]: record.output_weight
        for record in records
        if lot_by_record.get(record.pk)
    }


def zone_summary(zone):
    """Everything the zone screen renders, computed here so the template
    does no arithmetic: each rack with its slot matrix (one cell per grid
    position, row-major), plus occupancy counts."""
    if zone is None:
        return None

    slots = list(
        slots_queryset(zone)
        .select_related("lot", "lot__source_rolling_batch", "lot__source_rolling_batch__traveller_type")
        .order_by("rack__position", "row", "column")
    )
    weights = _occupant_weights(zone, [slot.lot_id for slot in slots if slot.lot_id])

    by_rack = {}
    for slot in slots:
        by_rack.setdefault(slot.rack_id, []).append(slot)

    racks, total_slots, occupied = [], 0, 0
    for rack in zone.racks.filter(is_active=True).order_by("position"):
        rack_slots = by_rack.get(rack.rack_id, [])
        filled = sum(1 for slot in rack_slots if slot.lot_id is not None)
        matrix = [
            {
                "letter": row_letter(row),
                "cells": [_slot_cell(slot, weights) for slot in rack_slots if slot.row == row],
            }
            for row in range(1, zone.rows + 1)
        ]
        racks.append({
            "rack": rack,
            "matrix": matrix,
            "capacity": len(rack_slots),
            "occupied": filled,
            "empty": len(rack_slots) - filled,
            "pct": int(filled / len(rack_slots) * 100) if rack_slots else 0,
        })
        total_slots += len(rack_slots)
        occupied += filled

    return {
        "zone": zone,
        "racks": racks,
        "columns": list(range(1, zone.columns + 1)),
        "total_racks": len(racks),
        "total_slots": total_slots,
        "occupied": occupied,
        "empty": total_slots - occupied,
        "pct": int(occupied / total_slots * 100) if total_slots else 0,
    }


def slot_picker(zone, *, field="rack_slot", selected=None):
    """Everything the slot-picker partial needs: the zone's grid, the slot
    the form will submit unless the operator clicks another one (the next
    free slot), and the field name to post it under."""
    if zone is None:
        return None
    return {
        "field": field,
        "zone": zone,
        "summary": zone_summary(zone),
        "selected": selected or next_free_slot(zone),
    }


def _slot_cell(slot, weights):
    """One grid position, ready to render: an empty slot is a cell too."""
    lot = slot.lot
    traveller_type = lot.traveller_type if lot else None
    return {
        "slot": slot,
        "label": slot.label,
        "empty": lot is None,
        "lot": lot,
        "wire_serial": lot.wire_serial if lot else "",
        "traveller_type": traveller_type.name if traveller_type else "",
        "weight": weights.get(slot.lot_id),
        "placed_at": slot.placed_at,
    }
