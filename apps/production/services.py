from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import log_action
from apps.inventory import services as inventory_services

from .models import OperationStatusHistory
from .process_registry import PROCESSES, process_for_record

# The lot stage a lot sits in before any process has touched it. Every
# other stage value is a process slug taken from the registry.
RAW_MATERIAL_STAGE = "raw_material"


def stage_progress(lot):
    """Return the registry's processes annotated with done/active/pending
    state for the given lot, for the horizontal process-tracker UI."""
    stage_order = [process.slug for process in PROCESSES]
    first_stage = stage_order[0]
    last_process = PROCESSES[-1]
    active_stage = first_stage if lot.current_stage == RAW_MATERIAL_STAGE else lot.current_stage

    if active_stage == last_process.slug:
        finished = lot.finished_goods.filter(status=last_process.completed_status).exists()
        active_index = len(stage_order) if finished else len(stage_order) - 1
    else:
        active_index = stage_order.index(active_stage) if active_stage in stage_order else 0

    steps = []
    for i, process in enumerate(PROCESSES):
        if i < active_index:
            state = "done"
        elif i == active_index:
            state = "active"
        else:
            state = "pending"
        steps.append({"code": process.slug, "label": process.label, "state": state})
    return steps


def ensure_can_operate(user, stage: str):
    if not user.can_operate_stage(stage):
        raise PermissionDenied(f"You are not authorized to operate the {stage} stage.")


def ensure_can_complete(user):
    if not user.can_approve():
        raise PermissionDenied("You are not authorized to complete/approve production transactions.")


# ----------------------------------------------------------------------
# Initiation
# ----------------------------------------------------------------------
def incoming_record_for(process, lot):
    """The predecessor record that handed `lot` to `process`, or None if
    this lot is not currently incoming here."""
    previous = process.previous
    if previous is None:
        return None
    if lot.pk in set(process.claimed_lot_ids()):
        return None
    path = previous.handover_lot_path
    return previous.complete_queryset(None).filter(**{path: lot}).order_by(previous.handover_ordering).first()


@transaction.atomic
def initiate_stage(process, lot, user, *, draft=False, **fields):
    """Create this process's record for `lot`, taking the Received Weight
    from the predecessor record rather than from anything the client sent.

    The Initiate screens and the demo-data generator both go through here,
    so generated history exercises exactly the path an operator does.
    """
    ensure_can_operate(user, process.slug)

    if not lot.wire_serial:
        raise ValidationError(
            "Wire Serial is missing for this lot - it cannot be initiated without a traceable Wire Serial."
        )

    existing = (
        process.model.objects.filter(lot=lot)
        .exclude(**{f"{process.status_field}__in": ["completed", "cancelled", "rejected"]})
        .first()
    )
    if existing is not None:
        return existing

    incoming = incoming_record_for(process, lot)
    if incoming is None:
        raise ValidationError(
            f"{lot.wire_serial or lot.lot_number} is not waiting at {process.label}."
        )

    record = process.model(
        lot=lot,
        input_quantity=incoming.output_weight,
        status="draft" if draft else "in_progress",
        created_by=user,
        updated_by=user,
        **fields,
    )
    record.full_clean()
    record.save()
    log_action(
        user, "create", record,
        description=f"{record.__class__.__name__} {record.transaction_number} initiated",
        metadata={"wire_serial": lot.wire_serial, "received_weight": str(incoming.output_weight)},
    )
    return record


# ----------------------------------------------------------------------
# Completion + handover to the next process
# ----------------------------------------------------------------------
@transaction.atomic
def handover(record, process, user):
    """Finish `record` at `process` and move its material onward.

    This is the only place the pipeline advances: it validates the output
    weight, stamps the completion, writes the WIP the next process will
    consume, moves the lot to `process.next` and records the audit trail.
    Which process follows comes from the registry, never from a literal.
    """
    ensure_can_complete(user)

    received = record.received_weight
    output = record.output_weight
    if output is None or output <= 0:
        raise ValidationError("Output weight must be greater than zero.")
    if received is not None and output > received:
        raise ValidationError(
            f"Output weight ({output} kg) cannot exceed the received weight ({received} kg)."
        )

    previous_status = getattr(record, process.status_field)
    lot = record.handover_lot
    next_process = process.next
    next_stage = next_process.slug if next_process else process.slug

    setattr(record, process.status_field, process.completed_status)
    record.completed_at = timezone.now()
    if hasattr(record, "updated_by"):
        record.updated_by = user
    if hasattr(record, "wastage_kg") and received is not None:
        record.wastage_kg = received - output
        if hasattr(record, "wastage_percent"):
            record.wastage_percent = (
                (record.wastage_kg / received * 100).quantize(Decimal("0.01")) if received else None
            )
    record.full_clean()
    record.save()

    if next_process is not None:
        inventory_services.add_wip(
            next_stage, lot, output, source_operation=record, user=user,
            remarks=f"Output from {process.label}, staged for {next_process.label}",
        )

    if lot is not None and lot.current_stage != next_stage:
        lot.current_stage = next_stage
        lot.save(update_fields=["current_stage", "updated_at"])

    OperationStatusHistory.objects.create(
        content_type=_content_type(record),
        object_id=record.pk,
        from_status=previous_status,
        to_status=process.completed_status,
        remarks=f"Lot advanced to {next_stage}",
        created_by=user,
        updated_by=user,
    )
    reference = getattr(record, "transaction_number", None) or getattr(record, "wire_serial", str(record.pk))
    log_action(
        user, "complete", record,
        description=f"{record.__class__.__name__} {reference} completed",
        metadata={"lot": lot.lot_number if lot else "", "next_stage": next_stage},
    )
    return record


@transaction.atomic
def complete_stage(operation, user, location=None):
    """Generic completion for an OperationBase stage: consumes the WIP this
    process was handed and then hands its output to the next process."""
    process = process_for_record(operation)
    _validate_operation(operation)
    inventory_services.consume_wip(
        process.slug, operation.lot, operation.input_quantity, location=location,
        source_operation=operation, user=user, remarks=f"Consumed at {process.label}",
    )
    return handover(operation, process, user)


def _validate_operation(operation):
    if operation.status == "completed":
        raise ValidationError("Completed transactions cannot be edited or re-completed.")
    if operation.status == "cancelled":
        raise ValidationError("Cancelled transactions cannot be completed.")
    if operation.lot.is_on_hold:
        raise ValidationError("Lot is on quality hold and cannot be processed.")
    operation.full_clean()


def _content_type(operation):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(operation.__class__)
