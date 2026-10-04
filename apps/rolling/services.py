import math
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.models import log_action
from apps.masters import services as masters_services
from apps.masters.models import CoilMaster, DiameterTravellerMapping, TravellerNo, TravellerType
from apps.production import services as production_services
from apps.production.process_registry import PROCESSES, get_process

from .models import RollingBatch, RollingBatchCoil

# Nothing in Rolling defines "Required M" yet, so the Stock Check reads it
# as metres of round wire and weighs it at the density of steel. Every
# metres -> kg conversion goes through `required_kg_from_metres` so the
# assumption lives in exactly one place.
STEEL_DENSITY_G_PER_CM3 = Decimal("7.85")
NO_MAPPING_MESSAGE = "No raw material mapping configured for this Traveller Type"


def _kg_per_metre(diameter_mm):
    """1 mm² of cross-section over 1 m is 1 cm³, so
    kg/m = π/4 · d² [mm²] · ρ [g/cm³] / 1000."""
    area_mm2 = Decimal(str(math.pi)) / 4 * Decimal(diameter_mm) ** 2
    return area_mm2 * STEEL_DENSITY_G_PER_CM3 / 1000


def required_kg_from_metres(diameter_mm, metres):
    """Weight of `metres` of round wire of `diameter_mm`, in kg (2 dp)."""
    kg = _kg_per_metre(diameter_mm) * Decimal(metres)
    return kg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def metres_from_kg(diameter_mm, kg):
    """Whole metres of round wire of `diameter_mm` that `kg` makes, rounded
    down so the Stock Check never promises wire that is not there."""
    per_metre = _kg_per_metre(diameter_mm)
    if not per_metre:
        return Decimal("0")
    return (Decimal(kg) / per_metre).quantize(Decimal("1"), rounding=ROUND_DOWN)


def check_stock(traveller_type_id, traveller_no_id, required_m):
    """Read-only answer to "is there enough wire for this job?".

    Resolves the traveller type to its mapped raw material and totals the
    In Stock coils under it against the required quantity. It never locks,
    reserves or consumes anything and never claims a wire serial: stock can
    still change before the batch is submitted, so `initiate_rolling_batch`
    remains the final authority.

    Returns a dict whose `status` is "available", "insufficient" or
    "no_mapping". Raises ValidationError for missing or invalid inputs.
    """
    errors = {}
    traveller_type = TravellerType.objects.filter(pk=_as_int(traveller_type_id), is_active=True).first()
    if traveller_type is None:
        errors["traveller_type_id"] = "Select a valid Traveller Type."
    traveller_no = TravellerNo.objects.filter(pk=_as_int(traveller_no_id), is_active=True).first()
    if traveller_no is None:
        errors["traveller_no_id"] = "Select a valid Traveller No."
    try:
        required_m = Decimal(str(required_m))
        if not required_m.is_finite() or required_m <= 0:
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        errors["required_m"] = "Enter a Required M greater than zero."
    if errors:
        raise ValidationError(errors)

    result = {
        "traveller_type": {
            "id": traveller_type.pk, "seq_no": traveller_type.seq_no, "name": traveller_type.name,
        },
        "traveller_no": {"id": traveller_no.pk, "code": traveller_no.code},
        "required_m": required_m,
        "raw_material": None,
        "f_thickness_mm": None,
        "f_width_mm": None,
        "required_kg": None,
        "total_available_kg": None,
        "shortfall_kg": None,
        "coils": [],
        # Where this traveller's material is right now, so the modal can
        # send the operator to that stage instead of always to Rolling.
        "current": current_position(traveller_type, traveller_no),
    }

    mapping = (
        DiameterTravellerMapping.objects.select_related("raw_material")
        .filter(traveller_type=traveller_type).first()
    )
    if mapping is None:
        result.update(status="no_mapping", available=False, message=NO_MAPPING_MESSAGE)
        return result

    raw_material = mapping.raw_material
    coils = list(masters_services.in_stock_coils(raw_material.pk))
    total = sum((coil.weight_kg for coil in coils), Decimal("0"))
    required_kg = required_kg_from_metres(raw_material.diameter_mm, required_m)
    available = total >= required_kg

    result.update(
        status="available" if available else "insufficient",
        available=available,
        message="Stock Available" if available else "Stock Not Available",
        raw_material={"raw_material_id": raw_material.pk, "diameter_mm": raw_material.diameter_mm},
        f_thickness_mm=mapping.f_thickness_mm,
        f_width_mm=mapping.f_width_mm,
        required_kg=required_kg,
        total_available_kg=total,
        available_m=metres_from_kg(raw_material.diameter_mm, total),
        shortfall_kg=Decimal("0.00") if available else required_kg - total,
        coils=coils,
    )
    return result


# How many of a traveller's lots the Stock Check lists individually; the
# per-stage counts always cover all of them.
OVERVIEW_LOT_LIMIT = 25


def traveller_overview(traveller_type_id, traveller_no_id=None):
    """What the Stock Check shows as soon as a traveller is picked, before
    anything is checked. Read-only.

    - stock: the mapped raw material's In Stock total in kg and metres, so
      the operator can see what Required M the stock allows;
    - history: the last and average wire weight issued for this traveller
      type, in kg and metres, as a guide to a normal Required M;
    - stages / lots: where this traveller's existing material is now, one
      entry per process in registry order.

    `traveller_no_id` is optional and narrows stages/lots to one traveller no.
    """
    traveller_type = TravellerType.objects.filter(pk=_as_int(traveller_type_id), is_active=True).first()
    if traveller_type is None:
        raise ValidationError({"traveller_type_id": "Select a valid Traveller Type."})
    traveller_no = None
    if traveller_no_id not in (None, ""):
        traveller_no = TravellerNo.objects.filter(pk=_as_int(traveller_no_id), is_active=True).first()
        if traveller_no is None:
            raise ValidationError({"traveller_no_id": "Select a valid Traveller No."})

    result = {
        "traveller_type": {"id": traveller_type.pk, "seq_no": traveller_type.seq_no, "name": traveller_type.name},
        "traveller_no": traveller_no and {"id": traveller_no.pk, "code": traveller_no.code},
        "raw_material": None,
        "stock": None,
        "history": None,
    }

    mapping = (
        DiameterTravellerMapping.objects.select_related("raw_material")
        .filter(traveller_type=traveller_type).first()
    )
    if mapping is not None:
        diameter = mapping.raw_material.diameter_mm
        coils = list(masters_services.in_stock_coils(mapping.raw_material_id))
        total = sum((coil.weight_kg for coil in coils), Decimal("0"))
        result["raw_material"] = {"raw_material_id": mapping.raw_material_id, "diameter_mm": diameter}
        result["f_thickness_mm"] = mapping.f_thickness_mm
        result["f_width_mm"] = mapping.f_width_mm
        result["stock"] = {
            "total_kg": total, "total_m": metres_from_kg(diameter, total), "coil_count": len(coils),
        }
        batches = RollingBatch.objects.filter(traveller_type=traveller_type)
        count = batches.count()
        if count:
            last = batches.order_by("-created_at").values_list("wire_weight_issued_kg", flat=True).first()
            average = (
                sum(batches.values_list("wire_weight_issued_kg", flat=True), Decimal("0")) / count
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            result["history"] = {
                "batch_count": count,
                "last_kg": last, "last_m": metres_from_kg(diameter, last),
                "average_kg": average, "average_m": metres_from_kg(diameter, average),
            }

    from apps.production.models import ProductionLot

    lots = ProductionLot.objects.filter(source_rolling_batch__traveller_type=traveller_type)
    if traveller_no is not None:
        lots = lots.filter(source_rolling_batch__traveller_no=traveller_no)
    lots = list(lots.select_related("source_rolling_batch__traveller_no").order_by("-created_at"))
    positions = lot_positions(lots)

    result["stages"] = [
        {
            "process": process,
            "count": sum(1 for lot in lots if positions[lot.pk]["process"] is process),
            "open": any(
                positions[lot.pk]["process"] is process and positions[lot.pk]["state"] != "completed" for lot in lots
            ),
        }
        for process in PROCESSES
    ]
    result["lot_count"] = len(lots)
    result["lots"] = [
        {"lot": lot, "wire_serial": lot.wire_serial, "traveller_no": lot.traveller_no.code, **positions[lot.pk]}
        for lot in lots[:OVERVIEW_LOT_LIMIT]
    ]
    return result


def current_position(traveller_type, traveller_no):
    """The stage the given traveller type + no is at right now, or None.

    Picks the newest lot of this traveller that is still open work
    somewhere in the line (waiting or in progress at a stage). Returns
    {"process", "state", "wire_serial", "lot"}; None when nothing of this
    traveller is in the line (never rolled, or every lot has finished at
    the terminal process), in which case the next step is a new Rolling
    batch.
    """
    from apps.production.models import ProductionLot

    lots = list(
        ProductionLot.objects.filter(
            source_rolling_batch__traveller_type=traveller_type,
            source_rolling_batch__traveller_no=traveller_no,
        ).order_by("-created_at")
    )
    if not lots:
        return None
    positions = lot_positions(lots)
    for lot in lots:
        position = positions[lot.pk]
        if position["process"] is not None and position["state"] != "completed":
            return {**position, "wire_serial": lot.wire_serial, "lot": lot}
    return None


def lot_positions(lots):
    """lot pk -> {"process", "state"} for where each lot is right now.

    A lot's `current_stage` is the process whose Main Table holds it (the
    handover moves it on at completion). Its state there is read from that
    process's own record for the lot, through the registry, so no process is
    named here: no record yet -> "waiting" (incoming), an open status ->
    "in_progress", anything else -> "completed" (the terminal process keeps
    its finished lots). One query per stage, not per lot.
    """
    by_stage = {}
    for lot in lots:
        by_stage.setdefault(lot.current_stage, []).append(lot)

    positions = {}
    for slug, stage_lots in by_stage.items():
        process = get_process(slug)
        if process is None:
            for lot in stage_lots:
                positions[lot.pk] = {"process": None, "state": "waiting"}
            continue
        path = process.handover_lot_path
        statuses = dict(
            process.model.objects.filter(**{f"{path}__in": stage_lots})
            .values_list(path, process.status_field)
        )
        for lot in stage_lots:
            status = statuses.get(lot.pk)
            if status is None:
                state = "waiting"
            elif not process.open_statuses or status in process.open_statuses:
                state = "in_progress"
            else:
                state = "completed"
            positions[lot.pk] = {"process": process, "state": state}
    return positions


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
