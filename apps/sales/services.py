"""Sales workflows. Views stay thin; every state change goes through here so
the web admin, the API and tests share one set of rules, one audit trail
and one reminder history."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.audit.models import log_action
from apps.inventory.models import FinishedGoodsStock
from apps.masters.models import DiameterTravellerMapping, SurfaceFinish, TravellerNo, TravellerType
from apps.rolling.services import required_kg_from_metres

from . import rules
from .models import (
    LEAD_STAGE_LABELS, NEXT_ACTION_LABELS, Activity, Lead, LeadEvent, Mill, MillContact, Notification, Reminder,
    SalesOrder, StockEnquiry, TrialOrder, Visit,
)

User = get_user_model()

ADMIN_ROLES = {"super_admin", "admin", "sales_admin"}
SALES_ROLES = {"sales_executive"}


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

def is_sales_admin(user):
    return bool(user and user.is_authenticated and (user.is_superuser or user.has_role(*ADMIN_ROLES)))


def is_sales_user(user):
    return bool(user and user.is_authenticated and (is_sales_admin(user) or user.has_role(*SALES_ROLES)))


def app_role(user):
    """What the mobile app routes on: ADMIN or PRATHAP (the sales executive)."""
    if is_sales_admin(user):
        return "ADMIN"
    if is_sales_user(user):
        return "PRATHAP"
    return None


def sales_admins():
    return User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(roles__code__in=ADMIN_ROLES)
    ).distinct()


def sales_executives():
    return User.objects.filter(is_active=True, roles__code__in=SALES_ROLES).distinct()


def _audit(user, action, instance, description, **metadata):
    log_action(user, action, instance, description=description, metadata=metadata)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def notify(recipients, *, kind, title, body="", entity=None):
    rows = []
    entity_type = entity.__class__.__name__ if entity is not None else ""
    entity_id = str(entity.pk) if entity is not None else ""
    for user in {u.pk: u for u in recipients}.values():
        rows.append(Notification(recipient=user, kind=kind, title=title, body=body,
                                 entity_type=entity_type, entity_id=entity_id))
    Notification.objects.bulk_create(rows)
    return rows


def notify_admins(*, exclude=None, **kwargs):
    admins = [u for u in sales_admins() if not exclude or u.pk != exclude.pk]
    return notify(admins, **kwargs)


def reminder_notify_time():
    """Configurable "surface reminders at" time of day, HH:MM (default 08:00,
    start of day). Set SALES_REMINDER_NOTIFY_TIME=18:00 for end of day."""
    raw = str(getattr(settings, "SALES_REMINDER_NOTIFY_TIME", "08:00"))
    try:
        hour, minute = (int(p) for p in raw.split(":", 1))
        return hour, minute
    except ValueError:
        return 8, 0


def generate_due_reminder_notifications(user=None, now=None):
    """Turn due reminders into notifications once. Called lazily from the
    dashboard/notification endpoints and by the send_due_reminders command,
    so it works with or without a scheduler."""
    now = timezone.localtime(now or timezone.now())
    hour, minute = reminder_notify_time()
    today = now.date()
    qs = Reminder.objects.filter(status="pending", notified_at__isnull=True, assigned_to__isnull=False)
    if (now.hour, now.minute) >= (hour, minute):
        qs = qs.filter(reminder_date__lte=today)
    else:
        qs = qs.filter(reminder_date__lt=today)
    if user is not None:
        qs = qs.filter(assigned_to=user)
    created = 0
    for reminder in qs.select_related("mill"):
        notify([reminder.assigned_to], kind="reminder_due",
               title=f"Reminder: {reminder.title or reminder.get_reminder_type_display()}",
               body=f"{reminder.mill or ''} - due {reminder.reminder_date:%d %b %Y}".strip(" -"),
               entity=reminder)
        reminder.notified_at = now
        reminder.save(update_fields=["notified_at", "updated_at"])
        created += 1
    return created


# ---------------------------------------------------------------------------
# Reminders (never deleted: a newer one supersedes the older)
# ---------------------------------------------------------------------------

def _entity_key(entity):
    return entity.__class__.__name__, str(entity.pk)


def schedule_reminder(*, entity, reminder_type, reminder_date, user, assigned_to, mill=None, lead=None,
                      title="", default_date=None, is_overridden=False, notes=""):
    entity_type, entity_id = _entity_key(entity)
    Reminder.objects.filter(entity_type=entity_type, entity_id=entity_id, status="pending").update(
        status="superseded", updated_at=timezone.now()
    )
    reminder = Reminder.objects.create(
        reminder_type=reminder_type, entity_type=entity_type, entity_id=entity_id, mill=mill, lead=lead,
        assigned_to=assigned_to, title=title, reminder_date=reminder_date,
        default_date=default_date or reminder_date, is_overridden=is_overridden, notes=notes,
        created_by=user, updated_by=user,
    )
    _audit(user, "create", reminder, f"Reminder {reminder.get_reminder_type_display()} on {reminder_date}",
           entity_type=entity_type, entity_id=entity_id, overridden=is_overridden,
           default_date=str(reminder.default_date))
    return reminder


def close_pending_reminders(entity, user, status="cancelled"):
    entity_type, entity_id = _entity_key(entity)
    count = Reminder.objects.filter(entity_type=entity_type, entity_id=entity_id, status="pending").update(
        status=status, updated_at=timezone.now(), updated_by=user
    )
    return count


def complete_reminder(reminder, user, notes=""):
    if reminder.status != "pending":
        raise ValidationError("Only a pending reminder can be completed.")
    reminder.status = "completed"
    reminder.completed_at = timezone.now()
    if notes:
        reminder.notes = (reminder.notes + "\n" + notes).strip()
    reminder.updated_by = user
    reminder.save()
    _audit(user, "complete", reminder, "Reminder completed")
    # Repeat-order follow-up runs one month at a time: completing this
    # month's reminder schedules next month's.
    if reminder.reminder_type == "repeat_order" and reminder.lead_id and reminder.lead.status == "open" \
            and reminder.lead.stage in ("order_received", "repeat_order_followup", "repeat_order"):
        next_date = rules.add_months(timezone.localdate(), int(getattr(settings, "SALES_REPEAT_ORDER_MONTHS", 1)))
        schedule_reminder(entity=reminder.lead, reminder_type="repeat_order", reminder_date=next_date, user=user,
                          assigned_to=reminder.assigned_to, mill=reminder.mill, lead=reminder.lead,
                          title="Repeat order follow-up", default_date=next_date)
    return reminder


def reschedule_reminder(reminder, user, new_date, notes=""):
    if reminder.status != "pending":
        raise ValidationError("Only a pending reminder can be rescheduled.")
    if new_date < timezone.localdate():
        raise ValidationError("Reminder date cannot be in the past.")
    entity_model = {"Lead": Lead, "TrialOrder": TrialOrder, "SalesOrder": SalesOrder, "Activity": Activity,
                    "Visit": Visit}
    model = entity_model.get(reminder.entity_type)
    entity = model.objects.filter(pk=reminder.entity_id).first() if model else None
    if entity is None:
        raise ValidationError("The reminder's record no longer exists.")
    new = schedule_reminder(entity=entity, reminder_type=reminder.reminder_type, reminder_date=new_date, user=user,
                            assigned_to=reminder.assigned_to, mill=reminder.mill, lead=reminder.lead,
                            title=reminder.title, default_date=reminder.default_date, is_overridden=True,
                            notes=notes)
    if reminder.lead_id and reminder.entity_type == "Lead":
        Lead.objects.filter(pk=reminder.lead_id).update(reminder_date=new_date)
    return new


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

STAGE1_FIELDS = [
    "visit_date", "total_spindles", "frame_details", "make", "ring_make", "ring_profile", "speed", "count",
    "fibre_type", "existing_traveller_used", "brand", "wire_section", "surface_finish", "traveller_number",
    "frequency_of_change", "sample_quantity", "technical_remarks", "remarks",
]
# Lead fields copied to the central Mill master once a visit is recorded.
MILL_PROFILE_FIELDS = [
    "total_spindles", "frame_details", "make", "ring_make", "ring_profile", "speed", "count", "fibre_type",
    "existing_traveller_used", "brand", "wire_section", "surface_finish", "traveller_number",
    "frequency_of_change", "sample_quantity",
]


def validate_stage1_step(lead, step):
    errors = {}
    for field in rules.STAGE1_REQUIRED.get(step, []):
        if field == "mill":
            ok = bool(lead.mill_id)
        elif field == "contact":
            ok = bool(lead.contact_id)
        elif field == "next_action":
            continue
        else:
            value = getattr(lead, field)
            ok = value not in (None, "")
        if not ok:
            errors[field] = "This field is required."
    if len(lead.technical_remarks or "") > 500:
        errors["technical_remarks"] = "Maximum 500 characters."
    return errors


def sync_mill_profile(lead, user):
    mill = lead.mill
    changed = []
    for field in MILL_PROFILE_FIELDS:
        value = getattr(lead, field)
        if value not in (None, "") and getattr(mill, field) != value:
            setattr(mill, field, value)
            changed.append(field)
    if changed:
        mill.updated_by = user
        mill.save()
        _audit(user, "update", mill, "Mill profile updated from visit", fields=changed, lead=lead.number)
    return changed


def step_label(code):
    return NEXT_ACTION_LABELS.get(code, code)


def open_lead_for_mill(mill, user, *, contact=None, create=True):
    """The mill's current journey: its latest draft/open lead. A mill whose
    last lead was closed starts a fresh journey (new lead)."""
    lead = Lead.objects.filter(mill=mill, status__in=["draft", "open"]).order_by("-updated_at").first()
    if lead is not None or not create:
        return lead
    lead = Lead.objects.create(mill=mill, contact=contact, assigned_to=user, status="open",
                               stage="initial_introduction", stage1_completed=True, stage1_step=4,
                               created_by=user, updated_by=user)
    _audit(user, "create", lead, f"Lead {lead.number} created for {mill.name}", source="journey")
    return lead


def journey_started(lead):
    return lead.events.exists()


def record_step(lead, user, step, next_action, *, reminder_override=None, notes="", visit=None):
    """Record that a Sales Journey step happened on this lead and schedule
    what comes next. The lead's stage becomes `step`; `next_action` sets the
    follow-up reminder (15 days by default, monthly for repeat-order
    follow-up, none for No Further Action, which closes the lead). Older
    pending reminders are superseded, never deleted."""
    if lead.status == "closed":
        raise ValidationError("This lead is closed.")
    current = lead.stage if journey_started(lead) else None
    if not rules.can_record_step(current, step):
        raise ValidationError({"purpose": f"{step_label(step)} cannot be recorded after "
                                          f"{step_label(current)}."})
    if next_action not in rules.next_actions(step):
        raise ValidationError({"next_action": f"{step_label(next_action)} is not a valid next action after "
                                              f"{step_label(step)}."})
    today = timezone.localdate()
    try:
        reminder_date, default_date, overridden = rules.resolve_reminder_date(next_action, today, reminder_override)
    except ValueError as exc:
        raise ValidationError({"next_followup_date": str(exc)})

    previous = lead.stage
    lead.stage = step
    lead.next_action = next_action
    lead.reminder_date = reminder_date
    lead.updated_by = user
    if lead.status == "draft":
        lead.status = "open"
    if next_action == "no_further_action":
        lead.status = "closed"
        lead.closed_at = timezone.now()
        close_pending_reminders(lead, user)
    lead.save()

    LeadEvent.objects.create(lead=lead, stage=step, next_action=next_action, reminder_date=reminder_date,
                             notes=notes, visit=visit, created_by=user)
    _audit(user, "update", lead, f"Journey {previous} -> {step} (next: {next_action})", from_stage=previous,
           to_stage=step, next_action=next_action, reminder_date=str(reminder_date) if reminder_date else None,
           reminder_overridden=overridden, visit=visit.number if visit else None)
    if reminder_date:
        target = step if next_action == "followup" else next_action
        schedule_reminder(entity=lead, reminder_type=rules.reminder_type_for(step, next_action),
                          reminder_date=reminder_date, default_date=default_date, is_overridden=overridden,
                          user=user, assigned_to=lead.assigned_to or user, mill=lead.mill, lead=lead,
                          title=f"{step_label(target)} - {lead.mill.name}")
    return lead, reminder_date, overridden


@transaction.atomic
def advance_lead(lead, user, next_action, *, reminder_override=None, notes="", step=None):
    """Quick update from the lead screen: record `step` (default: the lead's
    current step) with a new next action."""
    lead, _, _ = record_step(lead, user, step or lead.stage, next_action, reminder_override=reminder_override,
                             notes=notes)
    return lead


@transaction.atomic
def complete_stage1(lead, user, next_action, reminder_override=None, notes=""):
    if next_action not in rules.STAGE1_NEXT_ACTIONS:
        raise ValidationError({"next_action": "Choose a valid next action."})
    errors = {}
    for step in (1, 2, 3):
        errors.update(validate_stage1_step(lead, step))
    if errors:
        raise ValidationError(errors)
    lead.stage1_completed = True
    lead.stage1_step = 4
    if lead.status == "draft":
        lead.status = "open"
    lead.save()
    sync_mill_profile(lead, user)
    visit = Visit.objects.create(
        mill=lead.mill, lead=lead, contact=lead.contact, visit_type="mill_visit", visit_date=lead.visit_date,
        purpose="initial_introduction", people_met=lead.contact.name if lead.contact else "",
        summary=lead.technical_remarks or lead.remarks or "Mill visit & initial assessment",
        outcome="Assessment completed", details={"source": "stage1", "lead": lead.number},
        next_action=next_action, created_by=user, updated_by=user,
    )
    lead, reminder_date, overridden = record_step(lead, user, "initial_introduction", next_action,
                                                  reminder_override=reminder_override, notes=notes or visit.summary,
                                                  visit=visit)
    visit.next_followup_date = reminder_date
    visit.followup_overridden = overridden
    visit.save(update_fields=["next_followup_date", "followup_overridden"])
    return lead


# ---------------------------------------------------------------------------
# Trials
# ---------------------------------------------------------------------------

@transaction.atomic
def create_trial(*, lead, user, product_type, batch, quantity, finish, trial_start_date, delivery_mode,
                 remarks="", traveller_type=None, traveller_no=None, previous_trial=None, reminder_override=None,
                 record_journey=True):
    if lead.status == "closed":
        raise ValidationError("This lead is closed.")
    if record_journey and not rules.can_record_step(lead.stage if journey_started(lead) else None, "trial"):
        raise ValidationError(f"A trial cannot be created while the lead is at {step_label(lead.stage)}.")
    last_no = TrialOrder.objects.select_for_update().filter(lead=lead).order_by("-trial_no").values_list(
        "trial_no", flat=True).first() or 0
    if previous_trial is not None and previous_trial.status not in ("repeat_trial",):
        previous_trial.status = "repeat_trial"
        previous_trial.updated_by = user
        previous_trial.save()
        _audit(user, "update", previous_trial, "Trial marked for repeat", to_status="repeat_trial")
    trial = TrialOrder.objects.create(
        lead=lead, mill=lead.mill, trial_no=last_no + 1, previous_trial=previous_trial, product_type=product_type,
        traveller_type=traveller_type, traveller_no=traveller_no, batch=batch, quantity=quantity, finish=finish,
        trial_start_date=trial_start_date, delivery_mode=delivery_mode, remarks=remarks,
        created_by=user, updated_by=user,
    )
    _audit(user, "create", trial, f"Trial {trial.trial_no} created", lead=lead.number)
    if record_journey:
        record_step(lead, user, "trial", "trial_followup", reminder_override=reminder_override,
                    notes=f"Trial {trial.trial_no} ({trial.number}) created")
    notify_admins(exclude=user, kind="trial_created", title=f"New trial {trial.number}",
                  body=f"{lead.mill.name}: {product_type}, {quantity}, {finish}", entity=trial)
    return trial


@transaction.atomic
def set_trial_status(trial, user, new_status, *, result="", remarks="", reminder_override=None, record_journey=True):
    if not rules.can_transition_trial(trial.status, new_status):
        raise ValidationError(f"Cannot move a trial from {trial.get_status_display()} to {new_status}.")
    if new_status == "trial_pending" and not is_sales_admin(user):
        raise PermissionDenied("Only Admin reviews trials.")
    old = trial.status
    trial.status = new_status
    if result:
        trial.result = result
    if remarks:
        if is_sales_admin(user) and trial.created_by_id != user.pk:
            trial.admin_remarks = remarks
        else:
            trial.remarks = remarks
    if new_status == "trial_pending":
        trial.reviewed_by = user
        trial.reviewed_at = timezone.now()
    if new_status in ("trial_successful", "trial_failed"):
        trial.completed_at = timezone.now()
        trial.result = "successful" if new_status == "trial_successful" else "failed"
    trial.updated_by = user
    trial.save()
    _audit(user, "update", trial, f"Trial status {old} -> {new_status}", from_status=old, to_status=new_status)

    lead = trial.lead
    if record_journey and lead.status != "closed" and rules.can_record_step(
            lead.stage if journey_started(lead) else None, "trial_followup"):
        # Successful -> Order Discussion next; Failed -> repeat the trial.
        if new_status == "trial_successful":
            record_step(lead, user, "trial_followup", "order_discussion", reminder_override=reminder_override,
                        notes=f"Trial {trial.trial_no} successful")
        elif new_status == "trial_failed":
            record_step(lead, user, "trial_followup", "trial", reminder_override=reminder_override,
                        notes=f"Trial {trial.trial_no} failed")
        elif new_status == "trial_in_progress":
            LeadEvent.objects.create(lead=lead, stage=lead.stage, next_action=lead.next_action,
                                     reminder_date=lead.reminder_date,
                                     notes=f"Trial {trial.trial_no} in progress", created_by=user)
    if not is_sales_admin(user):
        notify_admins(kind="trial_status", title=f"Trial {trial.number}: {trial.get_status_display()}",
                      body=lead.mill.name, entity=trial)
    elif trial.created_by_id and trial.created_by_id != user.pk:
        notify([trial.created_by], kind="trial_status",
               title=f"Trial {trial.number}: {trial.get_status_display()}", body=remarks or lead.mill.name,
               entity=trial)
    return trial


# ---------------------------------------------------------------------------
# Stock check (read-only; never reserves or consumes anything)
# ---------------------------------------------------------------------------

def _decimal(value, field):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise InvalidOperation
        return number
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({field: "Enter a number greater than zero."})


def finished_goods_available():
    """The one base queryset behind Stock Check: Process 5 (Finished Goods)
    rows that are quality-approved and still hold weight. Rows on hold or
    rejected, WIP from Rolling to Finishing and raw coils never appear here.
    The options list and check_stock() both start from it so they agree."""
    return FinishedGoodsStock.objects.filter(
        status="available", accepted_quantity__gt=0, lot__source_rolling_batch__isnull=False,
    )


def stock_check_options():
    """Products currently in Finished Goods, one row per Traveller Type /
    Traveller No / Finish, with the weight available for each."""
    batch = "lot__source_rolling_batch__"
    fields = {
        "traveller_type_id": "traveller_type", "traveller_type_seq_no": "traveller_type__seq_no",
        "traveller_type_name": "traveller_type__name", "traveller_no_id": "traveller_no",
        "traveller_no_code": "traveller_no__code", "finish_id": "finish", "finish_name": "finish__finish_name",
    }
    rows = (
        finished_goods_available()
        .values(*(batch + f for f in fields.values()))
        .annotate(available_kg=Sum("accepted_quantity"))
        .order_by(batch + "traveller_type__seq_no", batch + "traveller_no__code", batch + "finish__finish_name")
    )
    return [
        {**{key: r[batch + f] for key, f in fields.items()}, "available_kg": r["available_kg"]}
        for r in rows
    ]


def check_stock(*, traveller_type_id, traveller_no_id, required_m, finish_id=None, mill=None, user=None,
                record=True):
    errors = {}
    traveller_type = TravellerType.objects.filter(pk=traveller_type_id, is_active=True).first() \
        if str(traveller_type_id or "").isdigit() else None
    if traveller_type is None:
        errors["traveller_type_id"] = "Select a valid Traveller Type."
    traveller_no = TravellerNo.objects.filter(pk=traveller_no_id, is_active=True).first() \
        if str(traveller_no_id or "").isdigit() else None
    if traveller_no is None:
        errors["traveller_no_id"] = "Select a valid Traveller No."
    finish = None
    if finish_id not in (None, ""):
        finish = SurfaceFinish.objects.filter(pk=finish_id, is_active=True).first() \
            if str(finish_id).isdigit() else None
        if finish is None:
            errors["finish_id"] = "Select a valid Finish."
    try:
        required_m = _decimal(required_m, "required_m")
    except ValidationError as exc:
        errors.update(exc.message_dict)
    if errors:
        raise ValidationError(errors)

    fg = finished_goods_available().filter(
        lot__source_rolling_batch__traveller_type=traveller_type,
        lot__source_rolling_batch__traveller_no=traveller_no,
    )
    if finish is not None:
        fg = fg.filter(lot__source_rolling_batch__finish=finish)
    lots = list(fg.select_related("lot__source_rolling_batch__finish").order_by("created_at"))
    available_kg = sum((row.accepted_quantity for row in lots), Decimal("0"))

    mapping = DiameterTravellerMapping.objects.select_related("raw_material").filter(
        traveller_type=traveller_type).first()
    required_kg = required_kg_from_metres(mapping.raw_material.diameter_mm, required_m) if mapping else None
    status = rules.stock_status(available_kg, required_kg)

    if status == "IN_STOCK":
        message = "Required stock is available."
    elif status == "PARTIALLY_AVAILABLE" and required_kg is None:
        message = ("Finished stock exists, but Required M cannot be converted to weight: no raw-material "
                   "mapping is configured for this Traveller Type.")
    elif status == "PARTIALLY_AVAILABLE":
        message = "Only part of the required quantity is in stock."
    else:
        message = "No finished stock. Capture a new requirement for Rolling."

    enquiry = None
    if record:
        enquiry = StockEnquiry.objects.create(
            mill=mill, traveller_type=traveller_type, traveller_no=traveller_no, finish=finish,
            required_m=required_m, required_kg=required_kg, available_kg=available_kg, stock_status=status,
            created_by=user, updated_by=user,
        )
    return {
        "enquiry_id": str(enquiry.pk) if enquiry else None,
        "traveller_type": {"id": traveller_type.pk, "seq_no": traveller_type.seq_no, "name": traveller_type.name},
        "traveller_no": {"id": traveller_no.pk, "code": traveller_no.code},
        "finish": {"id": finish.pk, "name": finish.finish_name} if finish else None,
        "brand": getattr(settings, "SALES_OWN_BRAND", "Rover"),
        "required_m": required_m,
        "required_kg": required_kg,
        "available_kg": available_kg,
        "shortfall_kg": (required_kg - available_kg) if required_kg is not None and available_kg < required_kg
        else None,
        "stock_status": status,
        "message": message,
        "has_mapping": mapping is not None,
        "lots": [
            {"fg_lot_number": row.fg_lot_number, "quantity_kg": row.accepted_quantity,
             "finish": row.lot.surface_finish.finish_name if row.lot.surface_finish else None}
            for row in lots
        ],
    }


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def _optional_decimal(value, field):
    if value in (None, ""):
        return None
    return _decimal(value, field)


def order_step_for(lead):
    """First order on a journey is "Order Received"; later ones are "Repeat Order"."""
    if lead is None:
        return "order_received"
    if lead.orders.exists() or lead.stage in ("order_received", "repeat_order_followup", "repeat_order"):
        return "repeat_order"
    return "order_received"


@transaction.atomic
def create_order(*, user, mill, traveller_type, traveller_no, finish, required_m=None, order_type=None, brand="",
                 remarks="", lead=None, trial=None, stock_enquiry=None, stock_status_at_order="",
                 reminder_override=None, po_number="", po_date=None, order_quantity=None, rate=None,
                 order_value=None, delivery_date=None, record_journey=True):
    required_m = _optional_decimal(required_m, "required_m")
    order_quantity = _optional_decimal(order_quantity, "order_quantity")
    rate = _optional_decimal(rate, "rate")
    order_value = _optional_decimal(order_value, "order_value")
    if required_m is None and order_quantity is None:
        raise ValidationError({"order_quantity": "Enter the order quantity (or Required M)."})
    if order_value is None and order_quantity is not None and rate is not None:
        order_value = (order_quantity * rate).quantize(Decimal("0.01"))
    if lead is not None and lead.mill_id != mill.pk:
        raise ValidationError({"lead": "The lead belongs to a different mill."})
    if lead is None and record_journey:
        # Every order belongs to the mill's journey so it is tracked.
        lead = open_lead_for_mill(mill, user)
    step = order_step_for(lead)
    if order_type is None:
        order_type = "repeat" if step == "repeat_order" else "stock"
    order = SalesOrder.objects.create(
        mill=mill, lead=lead, trial=trial, stock_enquiry=stock_enquiry, order_type=order_type,
        traveller_type=traveller_type, traveller_no=traveller_no, finish=finish,
        brand=brand or getattr(settings, "SALES_OWN_BRAND", "Rover"), required_m=required_m,
        po_number=po_number or "", po_date=po_date, order_quantity=order_quantity, rate=rate,
        order_value=order_value, delivery_date=delivery_date,
        stock_status_at_order=stock_status_at_order or (stock_enquiry.stock_status if stock_enquiry else ""),
        remarks=remarks, status="placed", created_by=user, updated_by=user,
    )
    if stock_enquiry is not None:
        stock_enquiry.is_resolved = True
        stock_enquiry.save(update_fields=["is_resolved", "updated_at"])
    qty_text = f"{order_quantity} pcs" if order_quantity is not None else f"{required_m} M"
    _audit(user, "create", order, f"Order {order.number} placed", mill=mill.name, quantity=qty_text,
           order_type=order_type, po_number=order.po_number)
    if trial is None and lead is not None:
        trial = lead.trials.filter(status__in=["trial_successful", "order_followup"]).order_by("-trial_no").first()
        if trial is not None:
            order.trial = trial
            order.save(update_fields=["trial", "updated_at"])
    if trial is not None and trial.status in ("trial_successful", "order_followup"):
        trial.status = "order_placed"
        trial.save(update_fields=["status", "updated_at"])
    if record_journey and lead is not None and lead.status != "closed":
        record_step(lead, user, step, "repeat_order_followup", reminder_override=reminder_override,
                    notes=f"Order {order.number} placed" + (f" (PO {order.po_number})" if order.po_number else ""))
    notify_admins(exclude=user, kind="order_created", title=f"New order {order.number}",
                  body=f"{mill.name}: {traveller_type.name} / {traveller_no.code} / {finish.finish_name}, "
                       f"{qty_text} by {user.get_full_name() or user.username}",
                  entity=order)
    return order


@transaction.atomic
def set_order_status(order, user, new_status, remarks=""):
    if not is_sales_admin(user) and new_status != "cancelled":
        raise PermissionDenied("Only Admin can progress an order.")
    if not rules.can_transition_order(order.status, new_status):
        raise ValidationError(f"Cannot move an order from {order.get_status_display()} to {new_status}.")
    old = order.status
    order.status = new_status
    if remarks:
        order.admin_remarks = remarks
    order.updated_by = user
    order.save()
    _audit(user, "update", order, f"Order status {old} -> {new_status}", from_status=old, to_status=new_status)
    if order.created_by_id and order.created_by_id != user.pk:
        notify([order.created_by], kind="order_status", title=f"Order {order.number}: {order.get_status_display()}",
               body=remarks or order.mill.name, entity=order)
    return order


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

@transaction.atomic
def create_activity(*, user, assigned_to=None, **data):
    assigned_to = assigned_to or user
    if assigned_to.pk != user.pk and not is_sales_admin(user):
        raise PermissionDenied("Only Admin can assign activities to someone else.")
    activity = Activity.objects.create(assigned_to=assigned_to, created_by=user, updated_by=user, **data)
    _audit(user, "create", activity, f"Activity {activity.number} for {assigned_to}",
           assigned_to=assigned_to.username)
    days = activity.reminder_days_before
    if days is not None:
        remind_on = max(activity.date - timedelta(days=days), timezone.localdate())
        schedule_reminder(entity=activity, reminder_type="activity", reminder_date=remind_on, user=user,
                          assigned_to=assigned_to, mill=activity.mill, lead=activity.lead,
                          title=f"{activity.get_activity_type_display()}: {activity.purpose}")
    if assigned_to.pk != user.pk:
        notify([assigned_to], kind="activity_assigned",
               title=f"New {activity.get_activity_type_display()} assigned",
               body=f"{activity.mill.name} on {activity.date:%d %b %Y}: {activity.purpose}", entity=activity)
    return activity


@transaction.atomic
def set_activity_status(activity, user, new_status, outcome=""):
    if activity.status != "pending":
        raise ValidationError("Only a pending activity can be changed.")
    if new_status not in ("completed", "cancelled"):
        raise ValidationError("Status must be completed or cancelled.")
    activity.status = new_status
    activity.outcome = outcome or activity.outcome
    activity.completed_at = timezone.now() if new_status == "completed" else None
    activity.updated_by = user
    activity.save()
    close_pending_reminders(activity, user, status="completed" if new_status == "completed" else "cancelled")
    _audit(user, "complete" if new_status == "completed" else "cancel", activity, f"Activity {new_status}")
    if activity.created_by_id and activity.created_by_id != user.pk:
        notify([activity.created_by], kind="activity_status",
               title=f"Activity {activity.get_status_display()}: {activity.mill.name}", body=outcome, entity=activity)
    return activity


# ---------------------------------------------------------------------------
# Visit Recording (Sales Journey)
# ---------------------------------------------------------------------------

def _value(data, path):
    root, _, key = path.partition(".")
    if not key:
        return data.get(root)
    return (data.get(root) or {}).get(key)


def validate_visit(purpose, data):
    errors = {}
    for path in rules.VISIT_REQUIRED.get(purpose, []):
        value = _value(data, path)
        if value in (None, "", []):
            errors[path.split(".")[-1]] = "This field is required."
    return errors


def _parse_date(value, field):
    from django.utils.dateparse import parse_date
    if value in (None, ""):
        return None
    if hasattr(value, "year"):
        return value
    parsed = parse_date(str(value))
    if parsed is None:
        raise ValidationError({field: "Use YYYY-MM-DD."})
    return parsed


def _master(model, pk, field, label):
    if pk in (None, ""):
        return None
    obj = model.objects.filter(pk=pk, is_active=True).first() if str(pk).isdigit() else None
    if obj is None:
        raise ValidationError({field: f"Select a valid {label}."})
    return obj


TRIAL_STATUS_FROM_VISIT = {
    "Not Started": "trial_created",
    "Trial In Progress": "trial_in_progress",
    "Trial Completed": "trial_in_progress",
}


def _advance_trial(trial, user, target):
    """Walk a trial forward through its allowed statuses to `target`."""
    path = {
        "trial_in_progress": ["trial_in_progress"],
        "trial_successful": ["trial_in_progress", "trial_successful"],
        "trial_failed": ["trial_in_progress", "trial_failed"],
        "repeat_trial": ["trial_in_progress", "repeat_trial"],
    }.get(target, [])
    for status in path:
        if trial.status == status:
            continue
        if rules.can_transition_trial(trial.status, status):
            set_trial_status(trial, user, status, record_journey=False)
            trial.refresh_from_db()
    return trial


@transaction.atomic
def record_visit(*, user, mill, purpose, visit_date, next_action, visit_time=None, visit_type="mill_visit",
                 contact=None, people_met="", summary="", outcome="", details=None, next_followup_date=None,
                 lead=None, activity=None, order=None, trial=None):
    """Save one Visit Recording and apply it to the journey:
    - the lead's stage becomes `purpose`, the next action schedules the
      follow-up reminder (default 15 days, override allowed);
    - Trial creates / updates the trial order, Trial Follow-up sets its
      result, Order Received / Repeat Order create the sales order;
    - a planned activity it was started from is marked completed."""
    details = dict(details or {})
    order = dict(order or {})
    trial = dict(trial or {})
    if purpose not in rules.JOURNEY:
        raise ValidationError({"purpose": "Select the purpose of visit."})
    if not visit_date:
        raise ValidationError({"visit_date": "Visit date is required."})
    if visit_date > timezone.localdate():
        raise ValidationError({"visit_date": "Visit date cannot be in the future."})
    if contact is not None and contact.mill_id != mill.pk:
        raise ValidationError({"contact": "This contact belongs to a different mill."})
    errors = validate_visit(purpose, {"summary": summary, "details": details, "order": order})
    if not next_action:
        errors["next_action"] = "Select the next action."
    if errors:
        raise ValidationError(errors)
    next_followup_date = _parse_date(next_followup_date, "next_followup_date")

    if lead is not None:
        if lead.mill_id != mill.pk:
            raise ValidationError({"lead": "The lead belongs to a different mill."})
        if lead.status == "closed":
            lead = None
    if lead is None:
        lead = open_lead_for_mill(mill, user, contact=contact)
    if not is_sales_admin(user) and lead.assigned_to_id not in (None, user.pk):
        raise PermissionDenied("This customer's lead is assigned to someone else.")
    if contact is not None and lead.contact_id is None:
        lead.contact = contact
        lead.save(update_fields=["contact", "updated_at"])
    current = lead.stage if journey_started(lead) else None
    if not rules.can_record_step(current, purpose):
        raise ValidationError({"purpose": f"{step_label(purpose)} cannot be recorded after {step_label(current)}."})

    visit = Visit.objects.create(
        mill=mill, lead=lead, contact=contact, activity=activity, visit_type=visit_type or "mill_visit",
        visit_date=visit_date, visit_time=visit_time, purpose=purpose, people_met=people_met or "",
        summary=summary or "", outcome=outcome or "", details=details, next_action=next_action,
        created_by=user, updated_by=user,
    )

    # Trial order created / updated by the Trial step.
    latest_trial = lead.trials.order_by("-trial_no").first()
    if purpose == "trial":
        status = TRIAL_STATUS_FROM_VISIT.get(details.get("trial_status"), "trial_in_progress")
        open_trial = latest_trial if latest_trial and latest_trial.status in (
            "trial_created", "trial_pending", "trial_in_progress") else None
        if open_trial is None:
            finish = _master(SurfaceFinish, trial.get("finish"), "finish", "Finish")
            missing = {k: "This field is required." for k in ("product_type", "quantity") if not trial.get(k)}
            if finish is None:
                missing["finish"] = "This field is required."
            if missing:
                raise ValidationError(missing)
            open_trial = create_trial(
                lead=lead, user=user, product_type=trial["product_type"], batch=trial.get("batch") or "-",
                quantity=str(trial["quantity"]), finish=finish,
                trial_start_date=_parse_date(details.get("trial_started_on"), "trial_started_on") or visit_date,
                delivery_mode=trial.get("delivery_mode") or "Direct",
                remarks=details.get("trial_performance", ""),
                traveller_type=_master(TravellerType, trial.get("traveller_type"), "traveller_type", "Traveller Type"),
                traveller_no=_master(TravellerNo, trial.get("traveller_no"), "traveller_no", "Traveller No"),
                previous_trial=latest_trial if latest_trial and latest_trial.status in (
                    "trial_failed", "repeat_trial") else None,
                record_journey=False,
            )
        if status == "trial_in_progress":
            _advance_trial(open_trial, user, "trial_in_progress")
        visit.trial = open_trial
    elif purpose == "trial_followup":
        target = {"successful": "trial_successful", "failed": "trial_failed", "repeat": "repeat_trial"}.get(
            str(details.get("trial_result", "")).lower())
        if target is None:
            raise ValidationError({"trial_result": "Choose Successful, Failed or Repeat Trial."})
        if latest_trial is not None:
            _advance_trial(latest_trial, user, target)
            visit.trial = latest_trial
    elif purpose in ("order_received", "repeat_order"):
        sales_order = create_order(
            user=user, mill=mill, lead=lead,
            traveller_type=_master(TravellerType, order.get("traveller_type"), "traveller_type", "Traveller Type"),
            traveller_no=_master(TravellerNo, order.get("traveller_no"), "traveller_no", "Traveller No"),
            finish=_master(SurfaceFinish, order.get("finish"), "finish", "Finish"),
            required_m=order.get("required_m"), order_type="repeat" if purpose == "repeat_order" else "new_requirement",
            brand=order.get("brand", ""), remarks=summary or "", po_number=order.get("po_number", ""),
            po_date=_parse_date(order.get("po_date"), "po_date"), order_quantity=order.get("order_quantity"),
            rate=order.get("rate"), order_value=order.get("order_value"),
            delivery_date=_parse_date(order.get("delivery_date"), "delivery_date"), record_journey=False,
        )
        visit.order = sales_order

    lead.refresh_from_db()
    lead, reminder_date, overridden = record_step(
        lead, user, purpose, next_action, reminder_override=next_followup_date,
        notes=summary or f"{visit.get_visit_type_display()}: {step_label(purpose)}", visit=visit)
    visit.next_followup_date = reminder_date
    visit.followup_overridden = overridden
    visit.save()

    if activity is not None and activity.status == "pending":
        set_activity_status(activity, user, "completed",
                            outcome=summary or f"Visit {visit.number}: {step_label(purpose)}")
    _audit(user, "create", visit, f"Visit {visit.number}: {step_label(purpose)} at {mill.name}",
           purpose=purpose, next_action=next_action, lead=lead.number,
           order=visit.order.number if visit.order_id else None, trial=visit.trial.number if visit.trial_id else None)
    if not is_sales_admin(user):
        notify_admins(kind="visit_recorded", title=f"{step_label(purpose)}: {mill.name}",
                      body=f"{visit.get_visit_type_display()} by {user.get_full_name() or user.username}. "
                           f"Next: {step_label(next_action)}", entity=visit)
    return visit


def journey_for_mill(mill, lead=None):
    """Journey at a Glance for the mill's current (or given) lead."""
    lead = lead or Lead.objects.filter(mill=mill).order_by(
        models_case_open_first(), "-updated_at").first()
    done = {}
    if lead is not None:
        for ev in lead.events.order_by("created_at"):
            if ev.stage in rules.JOURNEY:
                done[ev.stage] = ev.created_at
    current = lead.stage if lead is not None and done else None
    steps = []
    for i, code in enumerate(rules.JOURNEY, start=1):
        steps.append({
            "code": code, "label": LEAD_STAGE_LABELS[code], "index": i,
            "done": code in done, "current": code == current,
            "last_recorded": done.get(code),
        })
    return {
        "lead": lead,
        "steps": steps,
        "current": current,
        "allowed_steps": rules.allowed_steps(current) if (lead is None or lead.status != "closed") else rules.JOURNEY,
        "suggested_next": rules.SUGGESTED_NEXT.get(current, "initial_introduction") if current else
        "initial_introduction",
    }


def models_case_open_first():
    from django.db.models import Case, IntegerField, Value, When
    return Case(When(status__in=["draft", "open"], then=Value(0)), default=Value(1), output_field=IntegerField())
