from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.models import log_action
from apps.inventory import services as inventory_services
from apps.inventory.models import FinishedGoodsStock


@transaction.atomic
def receive_finished_goods(*, lot, product, accepted_quantity, rejected_quantity, location, rack, shelf, tray, user, remarks=""):
    if not user.can_operate_stage("finished_goods"):
        raise PermissionDenied("You are not authorized to receive finished goods.")
    if lot.current_stage != "finished_goods":
        raise ValidationError("Lot has not completed finishing yet.")

    total_quantity = accepted_quantity + rejected_quantity
    if total_quantity <= 0:
        raise ValidationError("Accepted or rejected quantity must be greater than zero.")

    inventory_services.consume_wip(
        "finished_goods", lot, total_quantity, source_operation=None, user=user,
        remarks=f"Received into finished goods for lot {lot.lot_number}",
    )

    fg_stock = FinishedGoodsStock(
        product=product,
        lot=lot,
        location=location,
        rack=rack,
        shelf=shelf,
        tray=tray,
        accepted_quantity=accepted_quantity,
        rejected_quantity=rejected_quantity,
        status="hold",
        created_by=user,
        updated_by=user,
    )
    fg_stock.full_clean()
    fg_stock.save()

    log_action(user, "create", fg_stock, description=f"Finished goods {fg_stock.fg_lot_number} received")
    return fg_stock


@transaction.atomic
def approve_finished_goods(fg_stock, user, mark_available=True):
    if not user.can_approve():
        raise PermissionDenied("You are not authorized to approve finished goods.")
    fg_stock.quality_approved = True
    fg_stock.quality_approved_by = user
    fg_stock.status = "available" if mark_available else "hold"
    fg_stock.updated_by = user
    fg_stock.full_clean()
    fg_stock.save()
    log_action(user, "approve", fg_stock, description=f"Finished goods {fg_stock.fg_lot_number} quality approved")
    return fg_stock


@transaction.atomic
def reject_finished_goods(fg_stock, user, remarks=""):
    if not user.can_approve():
        raise PermissionDenied("You are not authorized to reject finished goods.")
    fg_stock.status = "rejected"
    fg_stock.quality_approved = False
    fg_stock.updated_by = user
    fg_stock.full_clean()
    fg_stock.save()
    log_action(user, "reject", fg_stock, description=f"Finished goods {fg_stock.fg_lot_number} rejected", metadata={"remarks": remarks})
    return fg_stock


@transaction.atomic
def hold_finished_goods(fg_stock, user):
    fg_stock.status = "hold"
    fg_stock.updated_by = user
    fg_stock.save()
    log_action(user, "update", fg_stock, description=f"Finished goods {fg_stock.fg_lot_number} put on hold")
    return fg_stock
