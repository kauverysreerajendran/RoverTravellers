from django.db import models

from apps.common.models import generate_business_number
from apps.production.models import OperationBase


class FormingTransaction(OperationBase):
    forming_operation = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["transaction_number"]), models.Index(fields=["status"])]

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            self.transaction_number = generate_business_number("FRM", FormingTransaction, "transaction_number")
        super().save(*args, **kwargs)
