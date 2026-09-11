from django.db import models

from apps.common.models import generate_business_number
from apps.production.models import OperationBase


class FinishingTransaction(OperationBase):
    finishing_operation = models.CharField(max_length=100, blank=True)
    surface_finish_spec = models.CharField(max_length=100, blank=True)

    # Spec section 10.2/10.3 fields.
    tt = models.CharField("TT", max_length=50, blank=True)
    t_no = models.CharField("T No", max_length=50, blank=True)
    batch_no = models.CharField("Batch No", max_length=50, blank=True)
    surface_finish = models.ForeignKey(
        "masters.SurfaceFinish", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    traveller_weight_kg = models.DecimalField("Traveller Weight", max_digits=8, decimal_places=2, null=True, blank=True)
    colour = models.CharField("Colour", max_length=50, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["transaction_number"]), models.Index(fields=["status"])]

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            self.transaction_number = generate_business_number("FIN", FinishingTransaction, "transaction_number")
        super().save(*args, **kwargs)
