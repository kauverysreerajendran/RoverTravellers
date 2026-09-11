from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import TimeStampedModel, generate_business_number
from apps.master_data.models import ProductMaster

STATUS_CHOICES = [
    ("draft", "Draft"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("rejected", "Rejected"),
    ("cancelled", "Cancelled"),
]

ORDER_STATUS_CHOICES = [
    ("open", "Open"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("closed", "Closed"),
    ("cancelled", "Cancelled"),
]

LOT_STAGE_CHOICES = [
    ("raw_material", "Raw Material"),
    ("rolling", "Rolling"),
    ("forming", "Forming"),
    ("heat_treatment", "Heat Treatment"),
    ("finishing", "Finishing"),
    ("finished_goods", "Finished Goods"),
]


class ProductionOrder(TimeStampedModel):
    order_number = models.CharField(max_length=30, unique=True, db_index=True, editable=False)
    product = models.ForeignKey(ProductMaster, on_delete=models.PROTECT, related_name="production_orders")
    planned_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    uom = models.CharField(max_length=20, default="KG")
    status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default="open", db_index=True)
    due_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["order_number"]), models.Index(fields=["status"])]

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = generate_business_number("PO", ProductionOrder, "order_number")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.order_number


class ProductionLot(TimeStampedModel):
    lot_number = models.CharField(max_length=30, unique=True, db_index=True, editable=False)
    production_order = models.ForeignKey(ProductionOrder, on_delete=models.PROTECT, related_name="lots")
    current_stage = models.CharField(max_length=20, choices=LOT_STAGE_CHOICES, default="raw_material", db_index=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    is_on_hold = models.BooleanField(default=False)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["lot_number"]), models.Index(fields=["current_stage"])]

    def save(self, *args, **kwargs):
        if not self.lot_number:
            self.lot_number = generate_business_number("LOT", ProductionLot, "lot_number")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.lot_number


class OperationBase(TimeStampedModel):
    """Abstract base shared by every stage transaction (Rolling, Forming,
    Heat Treatment, Finishing). Encapsulates the common OperationInput /
    OperationOutput / OperationRejection quantities plus lifecycle fields."""

    transaction_number = models.CharField(max_length=30, unique=True, db_index=True, editable=False)
    lot = models.ForeignKey(ProductionLot, on_delete=models.PROTECT, related_name="%(class)s_operations")
    machine = models.ForeignKey("master_data.Machine", on_delete=models.PROTECT, related_name="+")
    operator = models.ForeignKey("master_data.Employee", on_delete=models.PROTECT, related_name="+")
    shift = models.ForeignKey("master_data.Shift", on_delete=models.PROTECT, related_name="+")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    input_quantity = models.DecimalField(max_digits=14, decimal_places=3)
    output_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    rejection_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    rejection_reason = models.ForeignKey(
        "master_data.ReasonCode", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    remarks = models.TextField(blank=True)

    class Meta:
        abstract = True

    def clean(self):
        if self.input_quantity is not None and self.input_quantity <= 0:
            raise ValidationError("Input quantity must be greater than zero.")
        if (self.output_quantity or 0) + (self.rejection_quantity or 0) > (self.input_quantity or 0):
            raise ValidationError("Output + rejection must not exceed input quantity.")

    def __str__(self):
        return self.transaction_number


class OperationQualityCheck(TimeStampedModel):
    RESULT_CHOICES = [("pending", "Pending"), ("pass", "Pass"), ("fail", "Fail"), ("hold", "Hold")]

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    operation = GenericForeignKey("content_type", "object_id")

    inspector = models.ForeignKey("master_data.Employee", on_delete=models.PROTECT, related_name="+")
    parameter = models.CharField(max_length=100)
    observed_value = models.CharField(max_length=100, blank=True)
    result = models.CharField(max_length=10, choices=RESULT_CHOICES, default="pending")
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.parameter} - {self.result}"


class OperationStatusHistory(TimeStampedModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    operation = GenericForeignKey("content_type", "object_id")

    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.from_status} -> {self.to_status}"
