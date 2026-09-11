from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.master_data.models import Location

from .models import RawMaterialStock, StockTransaction, WIPStock


def _default_location(stage: str) -> Location:
    location_type = {"raw_material": "store", "finished_goods": "fg"}.get(stage, "wip")
    location = Location.active.filter(location_type=location_type).first()
    if location is None:
        location = Location.active.first()
    if location is None:
        raise ValidationError("No location master data configured.")
    return location


@transaction.atomic
def consume_raw_material(material, quantity: Decimal, location=None, source_operation=None, user=None, remarks=""):
    """Deduct raw material stock. Raises ValidationError if insufficient stock."""
    location = location or _default_location("raw_material")
    stock = (
        RawMaterialStock.objects.select_for_update()
        .filter(material=material, location=location, status="available")
        .first()
    )
    available = stock.quantity if stock else Decimal("0")
    if available < quantity:
        raise ValidationError(
            f"Insufficient raw material stock for {material}. Available: {available}, required: {quantity}."
        )
    stock.quantity -= quantity
    stock.full_clean()
    stock.save()
    return _log_transaction(
        stock_type="raw_material",
        movement_type="production_consumption",
        material=material,
        location=location,
        quantity=-quantity,
        balance_after=stock.quantity,
        source_operation=source_operation,
        user=user,
        remarks=remarks,
    )


@transaction.atomic
def receive_raw_material(material, quantity: Decimal, location=None, source_operation=None, user=None, remarks=""):
    location = location or _default_location("raw_material")
    stock, _ = RawMaterialStock.objects.select_for_update().get_or_create(
        material=material, location=location, status="available", defaults={"quantity": Decimal("0")}
    )
    stock.quantity += quantity
    stock.full_clean()
    stock.save()
    return _log_transaction(
        stock_type="raw_material",
        movement_type="receipt",
        material=material,
        location=location,
        quantity=quantity,
        balance_after=stock.quantity,
        source_operation=source_operation,
        user=user,
        remarks=remarks,
    )


@transaction.atomic
def consume_wip(stage: str, lot, quantity: Decimal, location=None, source_operation=None, user=None, remarks=""):
    location = location or _default_location(stage)
    stock = (
        WIPStock.objects.select_for_update()
        .filter(stage=stage, lot=lot, location=location, status="available")
        .first()
    )
    available = stock.quantity if stock else Decimal("0")
    if available < quantity:
        raise ValidationError(
            f"Insufficient WIP stock for lot {lot.lot_number} at stage {stage}. "
            f"Available: {available}, required: {quantity}."
        )
    stock.quantity -= quantity
    stock.full_clean()
    stock.save()
    return _log_transaction(
        stock_type="wip",
        movement_type="production_consumption",
        lot=lot,
        location=location,
        quantity=-quantity,
        balance_after=stock.quantity,
        source_operation=source_operation,
        user=user,
        remarks=remarks,
    )


@transaction.atomic
def add_wip(stage: str, lot, quantity: Decimal, location=None, source_operation=None, user=None, remarks=""):
    location = location or _default_location(stage)
    stock, _ = WIPStock.objects.select_for_update().get_or_create(
        stage=stage, lot=lot, location=location, status="available", defaults={"quantity": Decimal("0")}
    )
    stock.quantity += quantity
    stock.full_clean()
    stock.save()
    return _log_transaction(
        stock_type="wip",
        movement_type="production_output",
        lot=lot,
        location=location,
        quantity=quantity,
        balance_after=stock.quantity,
        source_operation=source_operation,
        user=user,
        remarks=remarks,
    )


def _log_transaction(**kwargs):
    source_operation = kwargs.pop("source_operation", None)
    user = kwargs.pop("user", None)
    txn = StockTransaction(**kwargs, created_by=user, updated_by=user)
    if source_operation is not None:
        txn.source_operation = source_operation
        txn.reference_number = getattr(source_operation, "transaction_number", "") or getattr(
            source_operation, "fg_lot_number", ""
        )
    txn.save()
    return txn


@transaction.atomic
def transfer_stock(stock_transfer, user=None):
    if stock_transfer.status != "pending":
        raise ValidationError("Only pending transfers can be completed.")

    if stock_transfer.stock_type == "raw_material":
        source = (
            RawMaterialStock.objects.select_for_update()
            .filter(material=stock_transfer.material, location=stock_transfer.from_location, status="available")
            .first()
        )
        available = source.quantity if source else Decimal("0")
        if available < stock_transfer.quantity:
            raise ValidationError("Insufficient stock at source location for transfer.")
        source.quantity -= stock_transfer.quantity
        source.save()
        dest, _ = RawMaterialStock.objects.select_for_update().get_or_create(
            material=stock_transfer.material,
            location=stock_transfer.to_location,
            status="available",
            defaults={"quantity": Decimal("0")},
        )
        dest.quantity += stock_transfer.quantity
        dest.save()
        _log_transaction(
            stock_type="raw_material", movement_type="transfer_out", material=stock_transfer.material,
            location=stock_transfer.from_location, quantity=-stock_transfer.quantity, balance_after=source.quantity,
            source_operation=stock_transfer, user=user,
        )
        _log_transaction(
            stock_type="raw_material", movement_type="transfer_in", material=stock_transfer.material,
            location=stock_transfer.to_location, quantity=stock_transfer.quantity, balance_after=dest.quantity,
            source_operation=stock_transfer, user=user,
        )
    else:
        source = (
            WIPStock.objects.select_for_update()
            .filter(stage=stock_transfer.lot.current_stage, lot=stock_transfer.lot,
                     location=stock_transfer.from_location, status="available")
            .first()
        )
        available = source.quantity if source else Decimal("0")
        if available < stock_transfer.quantity:
            raise ValidationError("Insufficient WIP stock at source location for transfer.")
        source.quantity -= stock_transfer.quantity
        source.save()
        dest, _ = WIPStock.objects.select_for_update().get_or_create(
            stage=stock_transfer.lot.current_stage, lot=stock_transfer.lot,
            location=stock_transfer.to_location, status="available", defaults={"quantity": Decimal("0")},
        )
        dest.quantity += stock_transfer.quantity
        dest.save()
        _log_transaction(
            stock_type="wip", movement_type="transfer_out", lot=stock_transfer.lot,
            location=stock_transfer.from_location, quantity=-stock_transfer.quantity, balance_after=source.quantity,
            source_operation=stock_transfer, user=user,
        )
        _log_transaction(
            stock_type="wip", movement_type="transfer_in", lot=stock_transfer.lot,
            location=stock_transfer.to_location, quantity=stock_transfer.quantity, balance_after=dest.quantity,
            source_operation=stock_transfer, user=user,
        )

    stock_transfer.status = "completed"
    stock_transfer.save()
    return stock_transfer


@transaction.atomic
def apply_adjustment(stock_adjustment, user=None):
    if stock_adjustment.stock_type == "raw_material":
        stock, _ = RawMaterialStock.objects.select_for_update().get_or_create(
            material=stock_adjustment.material, location=stock_adjustment.location, status="available",
            defaults={"quantity": Decimal("0")},
        )
    else:
        stock, _ = WIPStock.objects.select_for_update().get_or_create(
            stage=stock_adjustment.lot.current_stage, lot=stock_adjustment.lot,
            location=stock_adjustment.location, status="available", defaults={"quantity": Decimal("0")},
        )
    stock_adjustment.quantity_before = stock.quantity
    delta = stock_adjustment.quantity_after - stock.quantity
    if stock_adjustment.quantity_after < 0:
        raise ValidationError("Resulting stock quantity cannot be negative.")
    stock.quantity = stock_adjustment.quantity_after
    stock.save()
    stock_adjustment.approved_by = user
    stock_adjustment.save()
    _log_transaction(
        stock_type=stock_adjustment.stock_type,
        movement_type="adjustment",
        material=stock_adjustment.material,
        lot=stock_adjustment.lot,
        location=stock_adjustment.location,
        quantity=delta,
        balance_after=stock.quantity,
        source_operation=stock_adjustment,
        user=user,
        remarks=stock_adjustment.remarks,
    )
    return stock_adjustment
