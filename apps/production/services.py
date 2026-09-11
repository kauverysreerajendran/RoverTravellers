from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.models import log_action
from apps.inventory import services as inventory_services

from .models import OperationStatusHistory

# Maps a stage to the WIP stage-name its completed output should be staged into.
NEXT_WIP_STAGE = {
    "forming": "heat_treatment",
    "heat_treatment": "finishing",
    "finishing": "finished_goods",
}

# The five visible steps of the manufacturing process tracker/stepper.
STEPPER_STAGES = [
    ("rolling", "Rolling"),
    ("forming", "Forming"),
    ("heat_treatment", "Heat Treatment"),
    ("finishing", "Finishing"),
    ("finished_goods", "Finished Goods"),
]


def stage_progress(lot):
    """Return the 5 stepper stages annotated with done/active/pending state
    for the given lot, for the horizontal process-tracker UI."""
    stage_order = [code for code, _ in STEPPER_STAGES]
    active_stage = "rolling" if lot.current_stage == "raw_material" else lot.current_stage

    if active_stage == "finished_goods":
        has_available_fg = lot.finished_goods.filter(status="available").exists()
        active_index = len(stage_order) - 1 if not has_available_fg else len(stage_order)
    else:
        active_index = stage_order.index(active_stage) if active_stage in stage_order else 0

    steps = []
    for i, (code, label) in enumerate(STEPPER_STAGES):
        if i < active_index:
            state = "done"
        elif i == active_index:
            state = "active"
        else:
            state = "pending"
        steps.append({"code": code, "label": label, "state": state})
    return steps


def ensure_can_operate(user, stage: str):
    if not user.can_operate_stage(stage):
        raise PermissionDenied(f"You are not authorized to operate the {stage} stage.")


def ensure_can_complete(user):
    if not user.can_approve():
        raise PermissionDenied("You are not authorized to complete/approve production transactions.")


@transaction.atomic
def complete_rolling(operation, user, material, location=None):
    ensure_can_complete(user)
    _validate_operation(operation)
    inventory_services.consume_raw_material(
        material, operation.input_quantity, location=location, source_operation=operation, user=user,
        remarks=f"Consumed for rolling {operation.transaction_number}",
    )
    if operation.output_quantity > 0:
        inventory_services.add_wip(
            "forming", operation.lot, operation.output_quantity, source_operation=operation, user=user,
            remarks=f"Rolling output {operation.transaction_number}",
        )
    _finalize(operation, user, next_stage="forming")


@transaction.atomic
def complete_stage(operation, user, current_stage: str, location=None):
    """Generic completion for Forming / Heat Treatment / Finishing: consumes
    WIP staged for `current_stage` and, unless this is the final stage,
    stages output into the next stage's WIP pool."""
    ensure_can_complete(user)
    _validate_operation(operation)
    inventory_services.consume_wip(
        current_stage, operation.lot, operation.input_quantity, location=location,
        source_operation=operation, user=user, remarks=f"Consumed at {current_stage}",
    )
    next_stage = NEXT_WIP_STAGE.get(current_stage)
    if next_stage and operation.output_quantity > 0:
        inventory_services.add_wip(
            next_stage, operation.lot, operation.output_quantity, source_operation=operation, user=user,
            remarks=f"Output from {current_stage}",
        )
    lot_next_stage = next_stage or "finished_goods"
    _finalize(operation, user, next_stage=lot_next_stage)


def _validate_operation(operation):
    if operation.status == "completed":
        raise ValidationError("Completed transactions cannot be edited or re-completed.")
    if operation.status == "cancelled":
        raise ValidationError("Cancelled transactions cannot be completed.")
    if operation.lot.is_on_hold:
        raise ValidationError("Lot is on quality hold and cannot be processed.")
    operation.full_clean()


def _finalize(operation, user, next_stage):
    previous_status = operation.status
    operation.status = "completed"
    operation.updated_by = user
    operation.save()

    operation.lot.current_stage = next_stage
    operation.lot.save(update_fields=["current_stage", "updated_at"])

    OperationStatusHistory.objects.create(
        content_type=_content_type(operation),
        object_id=operation.pk,
        from_status=previous_status,
        to_status="completed",
        remarks=f"Lot advanced to {next_stage}",
        created_by=user,
        updated_by=user,
    )
    log_action(
        user, "complete", operation,
        description=f"{operation.__class__.__name__} {operation.transaction_number} completed",
        metadata={"lot": operation.lot.lot_number, "next_stage": next_stage},
    )


def _content_type(operation):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(operation.__class__)
