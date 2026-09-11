from django.db import models

from apps.common.models import generate_business_number
from apps.production.models import OperationBase

HEAT_TREATMENT_TYPE_CHOICES = [
    ("annealing", "Annealing"),
    ("normalizing", "Normalizing"),
    ("hardening", "Hardening"),
    ("tempering", "Tempering"),
    ("quenching", "Quenching"),
]


class HeatTreatmentTransaction(OperationBase):
    batch_number = models.CharField(max_length=30, blank=True)
    heat_treatment_type = models.CharField(max_length=20, choices=HEAT_TREATMENT_TYPE_CHOICES, blank=True)
    temperature_celsius = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    holding_time_minutes = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    # Spec section 9.2/9.4 fields.
    tt = models.CharField("TT", max_length=50, blank=True)
    t_no = models.CharField("T No", max_length=50, blank=True)
    surface_finish = models.ForeignKey(
        "masters.SurfaceFinish", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["transaction_number"]), models.Index(fields=["status"])]

    def save(self, *args, **kwargs):
        if not self.transaction_number:
            self.transaction_number = generate_business_number("HT", HeatTreatmentTransaction, "transaction_number")
        super().save(*args, **kwargs)
