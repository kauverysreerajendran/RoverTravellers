from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.masters.models import CoilMaster, SurfaceFinish, TravellerNo, TravellerType
from apps.production.handover import HandoverRecord

# Stored values stay stable; the labels are stage-qualified so the Rolling
# table reads "Rolling Inprogress" / "Rolling Completed" at a glance.
STATUS_CHOICES = [("In Progress", "Rolling Inprogress"), ("Completed", "Rolling Completed")]


class RollingBatch(HandoverRecord, models.Model):
    """P1 - Rolling process. One batch = one wire serial, issued against a
    Traveller Type's mapped raw material and one or more coils."""

    batch_id = models.AutoField(primary_key=True)
    wire_serial = models.CharField(max_length=10, unique=True, db_index=True, editable=False)

    traveller_type = models.ForeignKey(TravellerType, on_delete=models.PROTECT, related_name="rolling_batches")
    traveller_no = models.ForeignKey(TravellerNo, on_delete=models.PROTECT, related_name="rolling_batches")
    finish = models.ForeignKey(SurfaceFinish, on_delete=models.PROTECT, related_name="rolling_batches")

    # Snapshotted from DiameterTravellerMapping at initiation time so a later
    # change to the mapping never rewrites the history of an existing batch.
    wire_diameter_mm = models.DecimalField(max_digits=6, decimal_places=2)
    f_thickness_mm = models.DecimalField(max_digits=5, decimal_places=2)
    f_width_mm = models.DecimalField(max_digits=5, decimal_places=2)

    required_box = models.PositiveIntegerField()
    wire_weight_issued_kg = models.DecimalField(max_digits=8, decimal_places=2)

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="In Progress", db_index=True)

    rolled_thickness_mm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    rolled_width_mm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    finished_weight_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    wastage_kg = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["wire_serial"]), models.Index(fields=["status"])]

    def __str__(self):
        return self.wire_serial

    # ------------------------------------------------------------------
    # Handover contract (see apps/production/handover.py). Rolling is the
    # origin process: its lot is created at initiation so the carrier
    # exists for the whole life of the batch, not only after completion.
    # ------------------------------------------------------------------
    handover_lot_path = "production_lots"

    @property
    def handover_lot(self):
        return self.production_lots.first()

    @property
    def surface_finish(self):
        return self.finish

    @property
    def received_weight(self):
        """Rolling is the origin process: it issues wire from coils rather
        than receiving a weight from a predecessor."""
        return self.wire_weight_issued_kg

    @property
    def output_weight(self):
        return self.finished_weight_kg

    def clean(self):
        if self.status == "Completed" and self.finished_weight_kg is not None:
            if self.finished_weight_kg > self.wire_weight_issued_kg:
                raise ValidationError("Finished weight cannot exceed the wire weight issued.")


class RollingBatchCoil(models.Model):
    """Which coil(s) a batch drew its wire weight from, and how much."""

    batch = models.ForeignKey(RollingBatch, on_delete=models.CASCADE, related_name="coils_used")
    coil = models.ForeignKey(CoilMaster, on_delete=models.PROTECT, related_name="rolling_batch_uses")
    weight_taken_kg = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "coil"], name="unique_batch_coil")]

    def __str__(self):
        return f"{self.batch.wire_serial} <- Coil {self.coil.coil_display_number} ({self.weight_taken_kg} kg)"
