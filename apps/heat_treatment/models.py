import secrets
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import generate_business_number
from apps.production.models import OperationBase

# Length of the token a printed QR label carries.
QR_TOKEN_LENGTH = 22

HEAT_TREATMENT_TYPE_CHOICES = [
    ("annealing", "Annealing"),
    ("normalizing", "Normalizing"),
    ("hardening", "Hardening"),
    ("tempering", "Tempering"),
    ("quenching", "Quenching"),
]


def generate_qr_token() -> str:
    """The token a printed label carries. Random rather than the row id, so
    a label cannot be guessed from another one and the id never leaks."""
    return secrets.token_urlsafe(16)[:QR_TOKEN_LENGTH]


class HeatBatchManager(models.Manager):
    def next_batch_no(self):
        """The number the next batch would take: one past the highest that
        exists, formatted by the active BatchNoFormat."""
        fmt = self.model.batch_format()
        if fmt is None:
            return ""
        highest = 0
        for batch_no in self.values_list("batch_no", flat=True):
            # Numbers carried over from before this format existed (a
            # legacy HT-2604-001) are not part of its sequence.
            if not fmt.matches(batch_no):
                continue
            number = fmt.number_of(batch_no)
            if number and number > highest:
                highest = number
        return fmt.format_number(highest + 1)


class HeatBatch(models.Model):
    """A furnace load: the Heat Treatment transactions that went in together.

    Each lot still gets its own HeatTreatmentTransaction - that is what
    carries the handover to the next process, one wire serial at a time -
    and this groups them, so the shop floor can work in batches (one batch
    number, one label, one QR) without changing how material moves.
    """

    STATUS_CHOICES = [("in_progress", "In Progress"), ("completed", "Completed")]

    heat_batch_id = models.AutoField(primary_key=True)
    batch_no = models.CharField(max_length=20, unique=True, db_index=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="in_progress", db_index=True)
    qr_token = models.CharField(
        max_length=32, unique=True, db_index=True, default=generate_qr_token, editable=False,
        help_text="Opaque token the printed QR label points at.",
    )
    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = HeatBatchManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Heat Batch"
        verbose_name_plural = "Heat Batches"

    def __str__(self):
        return self.batch_no

    # ------------------------------------------------------------------
    @staticmethod
    def process():
        """The process these batches belong to, resolved from the app this
        model lives in rather than from a slug written down here."""
        from apps.production.process_registry import process_for_app_label

        return process_for_app_label(HeatBatch._meta.app_label)

    @staticmethod
    def batch_format():
        from apps.masters.models import BatchNoFormat

        return BatchNoFormat.for_process(HeatBatch.process())

    def clean(self):
        fmt = self.batch_format()
        if fmt is None:
            raise ValidationError(
                "No batch number format is configured for this process. "
                "Seed masters (BatchNoFormat) before creating a batch."
            )
        self.batch_no = fmt.normalize(self.batch_no)
        if not fmt.matches(self.batch_no):
            raise ValidationError(
                {"batch_no": f'"{self.batch_no}" is not a valid batch number. Expected the form {fmt.format_number(1)}.'}
            )

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = generate_qr_token()
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # What is in the batch. All of it reads through the transactions, so a
    # lot added or removed is reflected without anything to keep in sync.
    # ------------------------------------------------------------------
    @property
    def open_transactions(self):
        return self.transactions.exclude(status__in=["completed", "cancelled", "rejected"])

    @property
    def lots(self):
        from apps.production.models import ProductionLot

        return ProductionLot.objects.filter(pk__in=self.transactions.values_list("lot_id", flat=True))

    @property
    def traveller_types(self):
        seen, types = set(), []
        for transaction in self.transactions.all():
            traveller_type = transaction.traveller_type
            if traveller_type and traveller_type.pk not in seen:
                seen.add(traveller_type.pk)
                types.append(traveller_type)
        return types

    @property
    def wire_serials(self):
        return [t.wire_serial for t in self.transactions.all() if t.wire_serial]

    @property
    def received_weight_total(self):
        return sum((t.received_weight or Decimal("0") for t in self.transactions.all()), Decimal("0"))

    @property
    def output_weight_total(self):
        return sum((t.output_weight or Decimal("0") for t in self.transactions.all()), Decimal("0"))

    @property
    def is_complete(self):
        """Complete when it holds work and none of it is still open."""
        return self.transactions.exists() and not self.open_transactions.exists()


class HeatTreatmentTransaction(OperationBase):
    heat_batch = models.ForeignKey(
        HeatBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions"
    )
    # Kept in step with `heat_batch.batch_no` by `save()`: the registry
    # column, the search fields and the reports all read this name, so the
    # batch grouping arrives without breaking anything that came before.
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
        # The Initiate screen no longer asks for a surface finish: it is the
        # material's own property, so it comes from the lot rather than from
        # the operator. The column stays, and the Complete Table still shows
        # it, but nothing re-enters it by hand.
        if self.surface_finish_id is None and self.lot_id:
            self.surface_finish = self.lot.surface_finish
        if self.heat_batch_id:
            self.batch_number = self.heat_batch.batch_no
        super().save(*args, **kwargs)
