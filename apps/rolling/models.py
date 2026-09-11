from django.db import models

from apps.common.models import generate_business_number
from apps.production.models import OperationBase


class RollingTransaction(OperationBase):
    raw_material = models.ForeignKey("master_data.MaterialMaster", on_delete=models.PROTECT, related_name="rolling_transactions")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["transaction_number"]), models.Index(fields=["status"])]

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            self.transaction_number = generate_business_number("ROL", RollingTransaction, "transaction_number")
        super().save(*args, **kwargs)
