from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import TimeStampedModel
from apps.master_data.models import Location, MaterialMaster, ProductMaster, Rack, ReasonCode, Shelf, Tray
from apps.production.handover import HandoverRecord
from apps.production.models import LOT_STAGE_CHOICES, ProductionLot

STOCK_STATUS_CHOICES = [
    ("available", "Available"),
    ("hold", "Hold"),
    ("rejected", "Rejected"),
]


class RawMaterialStock(TimeStampedModel):
    material = models.ForeignKey(MaterialMaster, on_delete=models.PROTECT, related_name="stock_records")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="raw_material_stock")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    status = models.CharField(max_length=10, choices=STOCK_STATUS_CHOICES, default="available")

    class Meta:
        unique_together = ("material", "location", "status")
        indexes = [models.Index(fields=["material"])]

    def __str__(self):
        return f"{self.material.material_code} @ {self.location.code}: {self.quantity}"

    def clean(self):
        if self.quantity < 0:
            raise ValidationError("Stock quantity cannot be negative.")


class WIPStock(TimeStampedModel):
    stage = models.CharField(max_length=20, choices=LOT_STAGE_CHOICES, db_index=True)
    lot = models.ForeignKey(ProductionLot, on_delete=models.PROTECT, related_name="wip_stock")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="wip_stock")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    status = models.CharField(max_length=10, choices=STOCK_STATUS_CHOICES, default="available")

    class Meta:
        unique_together = ("stage", "lot", "location", "status")
        indexes = [models.Index(fields=["stage"]), models.Index(fields=["lot"])]

    def __str__(self):
        return f"{self.lot.lot_number} [{self.stage}]: {self.quantity}"

    def clean(self):
        if self.quantity < 0:
            raise ValidationError("Stock quantity cannot be negative.")


class FinishedGoodsStock(HandoverRecord, TimeStampedModel):
    fg_lot_number = models.CharField(max_length=30, unique=True, db_index=True, editable=False)
    product = models.ForeignKey(ProductMaster, on_delete=models.PROTECT, related_name="fg_stock")
    lot = models.ForeignKey(ProductionLot, on_delete=models.PROTECT, related_name="finished_goods")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="fg_stock")
    rack = models.ForeignKey(Rack, on_delete=models.SET_NULL, null=True, blank=True, related_name="fg_stock")
    shelf = models.ForeignKey(Shelf, on_delete=models.SET_NULL, null=True, blank=True, related_name="fg_stock")
    tray = models.ForeignKey(Tray, on_delete=models.SET_NULL, null=True, blank=True, related_name="fg_stock")
    accepted_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    rejected_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    quality_approved = models.BooleanField(default=False)
    quality_approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=10, choices=STOCK_STATUS_CHOICES, default="hold")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["fg_lot_number"]), models.Index(fields=["status"])]

    def save(self, *args, **kwargs):
        if not self.fg_lot_number:
            from apps.common.models import generate_business_number

            self.fg_lot_number = generate_business_number("FG", FinishedGoodsStock, "fg_lot_number")
        super().save(*args, **kwargs)

    def clean(self):
        if self.status == "available" and not self.quality_approved:
            raise ValidationError("Finished goods cannot be marked available without quality approval.")

    @property
    def received_quantity(self):
        """Weight handed over by Finishing - what was booked in here,
        accepted plus rejected. Displayed as "Received Weight"."""
        return (self.accepted_quantity or Decimal("0")) + (self.rejected_quantity or Decimal("0"))

    # Handover contract. Finished Goods is the terminal process, so its
    # output weight is what it accepted and nothing consumes it onward.
    @property
    def received_weight(self):
        return self.received_quantity

    @property
    def output_weight(self):
        return self.accepted_quantity

    @property
    def completed_at(self):
        return self.updated_at

    def __str__(self):
        return self.fg_lot_number


class StockTransaction(TimeStampedModel):
    STOCK_TYPE_CHOICES = [("raw_material", "Raw Material"), ("wip", "WIP"), ("finished_goods", "Finished Goods")]
    MOVEMENT_CHOICES = [
        ("receipt", "Receipt"),
        ("issue", "Issue"),
        ("production_consumption", "Production Consumption"),
        ("production_output", "Production Output"),
        ("transfer_in", "Transfer In"),
        ("transfer_out", "Transfer Out"),
        ("adjustment", "Adjustment"),
        ("rejection", "Rejection"),
    ]

    stock_type = models.CharField(max_length=20, choices=STOCK_TYPE_CHOICES, db_index=True)
    movement_type = models.CharField(max_length=25, choices=MOVEMENT_CHOICES, db_index=True)
    material = models.ForeignKey(MaterialMaster, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey(ProductMaster, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    lot = models.ForeignKey(ProductionLot, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    balance_after = models.DecimalField(max_digits=14, decimal_places=3)
    reference_number = models.CharField(max_length=40, blank=True, db_index=True)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.UUIDField(null=True, blank=True)
    source_operation = GenericForeignKey("content_type", "object_id")
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["stock_type"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["reference_number"]),
        ]

    def __str__(self):
        return f"{self.movement_type} {self.quantity} ({self.stock_type})"


class StockAdjustment(TimeStampedModel):
    adjustment_number = models.CharField(max_length=30, unique=True, db_index=True, editable=False)
    stock_type = models.CharField(max_length=20, choices=StockTransaction.STOCK_TYPE_CHOICES)
    material = models.ForeignKey(MaterialMaster, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    lot = models.ForeignKey(ProductionLot, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    quantity_before = models.DecimalField(max_digits=14, decimal_places=3)
    quantity_after = models.DecimalField(max_digits=14, decimal_places=3)
    reason = models.ForeignKey(ReasonCode, on_delete=models.PROTECT, related_name="+")
    remarks = models.TextField(blank=True)
    approved_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.adjustment_number:
            from apps.common.models import generate_business_number

            self.adjustment_number = generate_business_number("ADJ", StockAdjustment, "adjustment_number")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.adjustment_number


class StockTransfer(TimeStampedModel):
    STATUS_CHOICES = [("pending", "Pending"), ("completed", "Completed"), ("cancelled", "Cancelled")]

    transfer_number = models.CharField(max_length=30, unique=True, db_index=True, editable=False)
    stock_type = models.CharField(max_length=20, choices=StockTransaction.STOCK_TYPE_CHOICES)
    material = models.ForeignKey(MaterialMaster, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    lot = models.ForeignKey(ProductionLot, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    from_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="transfers_out")
    to_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="transfers_in")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="pending")
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.transfer_number:
            from apps.common.models import generate_business_number

            self.transfer_number = generate_business_number("TRF", StockTransfer, "transfer_number")
        super().save(*args, **kwargs)

    def clean(self):
        if self.from_location_id and self.to_location_id and self.from_location_id == self.to_location_id:
            raise ValidationError("From and to locations must differ.")

    def __str__(self):
        return self.transfer_number
