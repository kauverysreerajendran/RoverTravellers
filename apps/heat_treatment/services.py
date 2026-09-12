"""Working a furnace load as one batch, without changing how material moves.

Every lot in a batch still gets its own `HeatTreatmentTransaction`, still
created by `production.services.initiate_stage` and still completed by
`complete_stage`. That is deliberate: the handover to the next process is
per wire serial, so grouping the work must not group the material. These
functions are a layer over the existing ones - they validate the batch,
then call the same services the single-lot screens call, in one
transaction.

Which process this is comes from the app the models live in
(`process_for_app_label`), so no stage name appears here.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import log_action
from apps.production.process_registry import process_for_app_label
from apps.production.services import complete_stage, incoming_record_for, initiate_stage

from .models import HeatBatch

SEARCH_LIMIT = 20


def process():
    """The process these batches belong to."""
    return process_for_app_label(HeatBatch._meta.app_label)


# ----------------------------------------------------------------------
# The batch itself
# ----------------------------------------------------------------------
def get_or_create_heat_batch(batch_no, user=None):
    """The open batch with this number, creating it if it is new.

    A completed batch is history: material cannot be added to it, so
    reusing its number is refused rather than quietly reopening it.
    """
    fmt = HeatBatch.batch_format()
    if fmt is None:
        raise ValidationError(
            "No batch number format is configured for Heat Treatment. Run seed_masters first."
        )

    batch_no = fmt.normalize(batch_no)
    if not batch_no:
        raise ValidationError("Enter a batch number.")
    if not fmt.matches(batch_no):
        raise ValidationError(
            f'"{batch_no}" is not a valid batch number. Expected the form {fmt.format_number(1)}.'
        )

    existing = HeatBatch.objects.filter(batch_no=batch_no).first()
    if existing is not None:
        if existing.status == "completed":
            raise ValidationError(
                f"Batch {batch_no} is already completed. Use a new batch number "
                f"(next free: {HeatBatch.objects.next_batch_no()})."
            )
        return existing

    batch = HeatBatch(batch_no=batch_no, created_by=user)
    batch.full_clean(exclude=["qr_token"])
    batch.save()
    if user is not None:
        log_action(user, "create", batch, description=f"Heat batch {batch.batch_no} opened")
    return batch


@transaction.atomic
def initiate_heat_batch(batch, lots, user, *, operation_date=None, surface_finish=None, draft=False):
    """Put `lots` into `batch`, one transaction each.

    Each lot must be waiting at this process right now - anything else is
    refused by wire serial rather than silently skipped, so an operator who
    ticks the wrong row is told which one. Lots already in the batch are
    left alone, so the same screen can add to an open batch.
    """
    if batch.status == "completed":
        raise ValidationError(f"Batch {batch.batch_no} is completed; it cannot take more lots.")

    current = process()
    already = set(batch.transactions.values_list("lot_id", flat=True))
    records = []
    for lot in lots:
        if lot.pk in already:
            continue
        if incoming_record_for(current, lot) is None:
            raise ValidationError(
                f"{lot.wire_serial or lot.lot_number} is not waiting at {current.label}; "
                "nothing was added to the batch."
            )
        fields = {"heat_batch": batch}
        if operation_date is not None:
            fields["operation_date"] = operation_date
        if surface_finish is not None:
            fields["surface_finish"] = surface_finish
        records.append(initiate_stage(current, lot, user, draft=draft, **fields))

    if not records and not already:
        raise ValidationError("Select at least one lot to put in this batch.")
    return records


@transaction.atomic
def complete_heat_batch(batch, outputs, user):
    """Finish the whole load: every open lot gets its output weight and is
    handed to the next process on its own, then the batch closes.

    Everything is validated before anything is written, so a batch is never
    left half finished because the last row had a typo.
    """
    open_transactions = list(
        batch.open_transactions.select_related("lot", "lot__source_rolling_batch")
    )
    if not open_transactions:
        raise ValidationError(f"Batch {batch.batch_no} has nothing left to complete.")

    planned = []
    for record in open_transactions:
        output = outputs.get(record.lot_id, outputs.get(str(record.lot_id)))
        label = record.wire_serial or record.transaction_number
        if output in (None, ""):
            raise ValidationError(f"Enter an output weight for {label}.")
        try:
            output = Decimal(str(output))
        except (TypeError, ArithmeticError, ValueError):
            raise ValidationError(f"Output weight for {label} is not a number.")
        if output <= 0:
            raise ValidationError(f"Output weight for {label} must be greater than zero.")
        received = record.received_weight
        if received is not None and output > received:
            raise ValidationError(
                f"Output weight for {label} ({output} kg) cannot exceed the received weight ({received} kg)."
            )
        planned.append((record, output))

    for record, output in planned:
        record.output_quantity = output
        record.save(update_fields=["output_quantity"])
        complete_stage(record, user)

    batch.status = "completed"
    batch.completed_at = timezone.now()
    batch.save(update_fields=["status", "completed_at"])
    log_action(
        user, "complete", batch,
        description=f"Heat batch {batch.batch_no} completed",
        metadata={"lots": len(planned), "output_total": str(sum(o for _, o in planned))},
    )
    return batch


# ----------------------------------------------------------------------
# Finding a batch
# ----------------------------------------------------------------------
def search_heat_batches(q="", *, status="", limit=SEARCH_LIMIT):
    """Typeahead over batches: by number, by any wire serial in the load, or
    by any traveller type in it. Plain ORM - the data is small enough that a
    search index would be a dependency without a benefit."""
    batches = HeatBatch.objects.all()
    if status:
        batches = batches.filter(status=status)
    q = (q or "").strip()
    if q:
        batches = batches.filter(
            Q(batch_no__icontains=q)
            | Q(transactions__lot__source_rolling_batch__wire_serial__icontains=q)
            | Q(transactions__lot__source_rolling_batch__traveller_type__name__icontains=q)
        )
    return batches.distinct().order_by("-created_at")[:limit]
