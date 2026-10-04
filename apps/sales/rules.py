"""Pure business rules (no DB access) so they can be unit tested directly:
reminder defaults, and the allowed stage / status transitions."""
import calendar
from datetime import date, timedelta

from django.conf import settings

DEFAULT_REMINDER_DAYS = 15


def reminder_days():
    return int(getattr(settings, "SALES_DEFAULT_REMINDER_DAYS", DEFAULT_REMINDER_DAYS))


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def default_reminder_date(next_action: str, today: date) -> date | None:
    """Current date + 15 days for every follow-up style action, one month for
    repeat-order follow-up (monthly), and no reminder for No Further Action."""
    if not next_action or next_action == "no_further_action":
        return None
    if next_action == "repeat_order_followup":
        return add_months(today, int(getattr(settings, "SALES_REPEAT_ORDER_MONTHS", 1)))
    return today + timedelta(days=reminder_days())


def resolve_reminder_date(next_action, today, override=None):
    """Returns (reminder_date, default_date, is_overridden)."""
    default = default_reminder_date(next_action, today)
    if default is None:
        return None, None, False
    if override:
        if override < today:
            raise ValueError("Reminder date cannot be in the past.")
        return override, default, override != default
    return default, default, False


# ---------------------------------------------------------------------------
# Sales Journey (10 steps). A lead's stage is the latest step recorded.
# ---------------------------------------------------------------------------

JOURNEY = [
    "initial_introduction", "requirement_discussion", "sample_requested", "sample_delivered", "trial",
    "trial_followup", "order_discussion", "order_received", "repeat_order_followup", "repeat_order",
]

# Steps that may be recorded again after moving past them.
JOURNEY_LOOPS = {
    "trial": ["sample_requested"],
    "trial_followup": ["sample_requested", "trial"],
    "order_discussion": ["trial"],
    "repeat_order": ["repeat_order_followup"],
}

# What the reference screens suggest as the natural next step.
SUGGESTED_NEXT = {
    "initial_introduction": "requirement_discussion",
    "requirement_discussion": "sample_requested",
    "sample_requested": "sample_delivered",
    "sample_delivered": "trial",
    "trial": "trial_followup",
    "trial_followup": "order_discussion",
    "order_discussion": "order_received",
    "order_received": "repeat_order_followup",
    "repeat_order_followup": "repeat_order",
    "repeat_order": "repeat_order_followup",
}


def step_index(step):
    return JOURNEY.index(step) if step in JOURNEY else -1


def allowed_steps(current):
    """Steps that can be recorded when the lead is at `current` (None = new
    journey: any step, e.g. an existing customer placing a repeat order)."""
    if not current or current not in JOURNEY:
        return list(JOURNEY)
    i = JOURNEY.index(current)
    allowed = JOURNEY[i:] + [s for s in JOURNEY_LOOPS.get(current, []) if s not in JOURNEY[i:]]
    return [s for s in JOURNEY if s in allowed]


def can_record_step(current, step):
    return step in allowed_steps(current)


def next_actions(step):
    """Next Action choices after recording `step`: follow up at the same
    step, move to a later step (or a permitted loop back), or close."""
    later = [s for s in JOURNEY if s in allowed_steps(step) and s != step]
    return ["followup"] + later + ["no_further_action"]


# Stage 1 (Mill Visit & Initial Assessment) screen 4.
STAGE1_NEXT_ACTIONS = next_actions("initial_introduction")

# Which reminder type a next action produces ("followup" uses the step's).
REMINDER_TYPE_FOR_ACTION = {
    "initial_introduction": "lead_followup",
    "requirement_discussion": "lead_followup",
    "sample_requested": "sample_followup",
    "sample_delivered": "sample_followup",
    "trial": "trial_followup",
    "trial_followup": "trial_followup",
    "order_discussion": "order_followup",
    "order_received": "order_followup",
    "repeat_order_followup": "repeat_order",
    "repeat_order": "repeat_order",
}


def reminder_type_for(step, next_action):
    key = step if next_action == "followup" else next_action
    return REMINDER_TYPE_FOR_ACTION.get(key, "lead_followup")


# Visit Recording: required answers per step (besides purpose, date, next
# action and follow-up date, which every step needs).
VISIT_REQUIRED = {
    "initial_introduction": ["summary"],
    "requirement_discussion": ["details.traveller_type", "details.quantity"],
    "sample_requested": ["details.sample_requested", "details.trial_plan"],
    "sample_delivered": ["details.sample_details", "details.quantity_delivered"],
    "trial": ["details.trial_status"],
    "trial_followup": ["details.trial_result"],
    "order_discussion": ["details.order_quantity"],
    "order_received": ["order.po_number", "order.order_quantity", "order.traveller_type", "order.traveller_no",
                       "order.finish"],
    "repeat_order_followup": ["details.consumption_status"],
    "repeat_order": ["order.po_number", "order.order_quantity", "order.traveller_type", "order.traveller_no",
                     "order.finish"],
}

TRIAL_RESULTS = ["successful", "failed", "repeat"]


TRIAL_TRANSITIONS = {
    "trial_created": ["trial_pending", "trial_in_progress", "trial_failed"],
    "trial_pending": ["trial_in_progress", "trial_failed"],
    "trial_in_progress": ["trial_successful", "trial_failed", "repeat_trial"],
    "trial_failed": ["repeat_trial"],
    "trial_successful": ["order_followup", "order_placed"],
    "order_followup": ["order_placed"],
    "repeat_trial": [],
    "order_placed": [],
}


def can_transition_trial(current: str, target: str) -> bool:
    return target in TRIAL_TRANSITIONS.get(current, [])


ORDER_TRANSITIONS = {
    "draft": ["placed", "cancelled"],
    "placed": ["under_review", "confirmed", "cancelled"],
    "under_review": ["confirmed", "cancelled"],
    "confirmed": ["processing", "cancelled"],
    "processing": ["dispatched", "cancelled"],
    "dispatched": ["completed"],
    "completed": [],
    "cancelled": [],
}


def can_transition_order(current: str, target: str) -> bool:
    return target in ORDER_TRANSITIONS.get(current, [])


# Required fields per Stage 1 screen (mirrors the reference screens).
STAGE1_REQUIRED = {
    1: ["visit_date", "mill", "contact"],
    2: ["total_spindles", "frame_details", "make", "ring_make", "ring_profile", "speed", "count", "fibre_type"],
    3: ["existing_traveller_used", "brand", "wire_section", "surface_finish", "traveller_number",
        "frequency_of_change", "sample_quantity"],
    4: ["next_action"],
}


def stock_status(available_kg, required_kg):
    """IN_STOCK / PARTIALLY_AVAILABLE / OUT_OF_STOCK."""
    if available_kg is None or available_kg <= 0:
        return "OUT_OF_STOCK"
    if required_kg is None:
        return "PARTIALLY_AVAILABLE"
    return "IN_STOCK" if available_kg >= required_kg else "PARTIALLY_AVAILABLE"
