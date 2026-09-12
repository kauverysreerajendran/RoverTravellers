import datetime
from decimal import Decimal

from django.db.models import F, Sum
from django.db.models.functions import TruncDate, TruncWeek
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.finishing.models import FinishingTransaction
from apps.forming.models import FormingTransaction
from apps.heat_treatment.models import HeatTreatmentTransaction
from apps.inventory.models import FinishedGoodsStock, RawMaterialStock, WIPStock
from apps.master_data.models import MaterialMaster
from apps.masters.models import CoilMaster, RackMaster, RackSlot, RackZone
from apps.production.models import ProductionLot, ProductionOrder
from apps.production.process_registry import PROCESSES
from apps.rolling.models import RollingBatch

# Rolling is deliberately excluded: it now runs on its own wire-serial/coil
# model (RollingBatch) rather than the generic OperationBase shape shared by
# Forming/Heat Treatment/Finishing, so it's summarized separately below.
STAGE_MODELS = {
    "forming": FormingTransaction,
    "heat_treatment": HeatTreatmentTransaction,
    "finishing": FinishingTransaction,
}


def _sum(qs, field):
    return qs.aggregate(total=Sum(field))["total"] or Decimal("0")


def get_rolling_summary():
    qs = RollingBatch.objects.all()
    return {
        "stage": "rolling",
        "label": "Rolling",
        "total_lots": qs.count(),
        "input_quantity": _sum(qs, "wire_weight_issued_kg"),
        "output_quantity": _sum(qs, "finished_weight_kg"),
        "rejection_quantity": _sum(qs, "wastage_kg"),
        "pending": qs.filter(status="In Progress").count(),
        "completed": qs.filter(status="Completed").count(),
    }


def get_stage_summary():
    summary = [get_rolling_summary()]
    for stage, model in STAGE_MODELS.items():
        qs = model.objects.all()
        summary.append(
            {
                "stage": stage,
                "label": stage.replace("_", " ").title(),
                "total_lots": qs.values("lot").distinct().count(),
                "input_quantity": _sum(qs, "input_quantity"),
                "output_quantity": _sum(qs, "output_quantity"),
                "rejection_quantity": _sum(qs, "rejection_quantity"),
                "pending": qs.filter(status__in=["draft", "in_progress"]).count(),
                "completed": qs.filter(status="completed").count(),
            }
        )
    return summary


def get_dashboard_summary():
    total_orders = ProductionOrder.objects.count()
    active_lots = ProductionLot.objects.exclude(current_stage=PROCESSES[-1].slug).count()

    wip_by_stage = {
        row["stage"]: row["total"]
        for row in WIPStock.objects.filter(status="available").values("stage").annotate(total=Sum("quantity"))
    }

    fg_quantity = _sum(FinishedGoodsStock.objects.filter(status="available"), "accepted_quantity")

    rolling_summary = get_rolling_summary()
    total_output = rolling_summary["output_quantity"]
    total_rejection = rolling_summary["rejection_quantity"]
    for model in STAGE_MODELS.values():
        total_output += _sum(model.objects.all(), "output_quantity")
        total_rejection += _sum(model.objects.all(), "rejection_quantity")
    rejection_rate = float(total_rejection / (total_output + total_rejection) * 100) if (total_output + total_rejection) else 0.0

    low_stock = list(
        RawMaterialStock.objects.filter(status="available", quantity__lte=F("material__reorder_level"))
        .select_related("material", "location")[:10]
    )

    pending_qc = FinishedGoodsStock.objects.filter(quality_approved=False, status="hold").select_related("product", "lot")[:10]

    recent_audit = AuditLog.objects.select_related("user").all()[:10]

    recent_transactions = []
    for batch in RollingBatch.objects.all()[:5]:
        recent_transactions.append(
            {
                "stage": "rolling",
                "transaction_number": batch.wire_serial,
                "wire_serial": batch.wire_serial,
                "status": batch.status,
                "created_at": batch.created_at,
            }
        )
    for stage, model in STAGE_MODELS.items():
        for txn in model.objects.select_related("lot")[:5]:
            recent_transactions.append(
                {
                    "stage": stage,
                    "transaction_number": txn.transaction_number,
                    "wire_serial": txn.lot.wire_serial,
                    "status": txn.status,
                    "created_at": txn.created_at,
                }
            )
    recent_transactions.sort(key=lambda t: t["created_at"], reverse=True)
    recent_transactions = recent_transactions[:10]

    return {
        "total_production_orders": total_orders,
        "active_lots": active_lots,
        "rolling_wip": rolling_summary["pending"],
        "forming_wip": wip_by_stage.get("forming", Decimal("0")),
        "heat_treatment_wip": wip_by_stage.get("heat_treatment", Decimal("0")),
        "finishing_wip": wip_by_stage.get("finishing", Decimal("0")),
        "finished_goods_quantity": fg_quantity,
        "quality_rejection_rate": round(rejection_rate, 2),
        "stage_summary": get_stage_summary(),
        "low_stock_alerts": low_stock,
        "pending_qc_approvals": list(pending_qc),
        "recent_audit_logs": list(recent_audit),
        "recent_transactions": recent_transactions,
    }


# ---------------------------------------------------------------------------
# The overview screen. Everything below walks `PROCESSES` and reads the
# weight fields off each model, so a sixth process appears on the dashboard
# - in its KPIs, its flow column and every chart series - without a line
# of code here. No stage name is written down.
# ---------------------------------------------------------------------------

RANGES = {"7d": 7, "30d": 30, "90d": 90, "ytd": None}
DEFAULT_RANGE = "30d"

# Field names to look for on a process's model, most specific first. These
# are column names, not stages: a process that spells its weights
# differently is read correctly without being named.
RECEIVED_FIELDS = ("input_quantity", "wire_weight_issued_kg")
OUTPUT_FIELDS = ("output_quantity", "finished_weight_kg", "accepted_quantity")
WASTAGE_FIELDS = ("wastage_kg", "rejected_quantity")
COMPLETED_FIELDS = ("completed_at", "updated_at")


def _fields(model):
    """Where this model keeps its weights and its completion time.

    Two of the three weights can be missing as columns and still be known:
    the terminal process records what it accepted and what it rejected
    rather than what it received, and the middle stages record no wastage
    at all - it is what went in less what came out. Those are expressed
    here as ORM expressions, so every figure is still summed in the
    database rather than in a loop.
    """
    names = {field.name for field in model._meta.concrete_fields}

    def first(candidates):
        return next((name for name in candidates if name in names), None)

    received, output, wastage = first(RECEIVED_FIELDS), first(OUTPUT_FIELDS), first(WASTAGE_FIELDS)

    received_expr = F(received) if received else None
    output_expr = F(output) if output else None
    wastage_expr = F(wastage) if wastage else None
    if received_expr is None and output_expr is not None and wastage_expr is not None:
        # Accepted + rejected is what was booked in.
        received_expr = F(output) + F(wastage)
    if wastage_expr is None and received_expr is not None and output_expr is not None:
        wastage_expr = F(received) - F(output)

    return {
        "received": received_expr,
        "output": output_expr,
        "wastage": wastage_expr,
        "completed": first(COMPLETED_FIELDS),
    }


def resolve_range(value):
    """(key, start, end) for a range key. Unknown keys fall back to the
    default rather than failing a page load."""
    key = value if value in RANGES else DEFAULT_RANGE
    end = timezone.now()
    days = RANGES[key]
    if days is None:
        start = end.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = end - datetime.timedelta(days=days)
    return key, start, end


def _window_before(start, end):
    """The same length of time immediately before the window, so a figure
    can be shown against what it was."""
    span = end - start
    return start - span, start


def _completed_in(process, start, end):
    """This process's records that finished inside the window."""
    field = _fields(process.model)["completed"]
    qs = process.complete_queryset(None)
    if field is None:
        return qs.none()
    return qs.filter(**{f"{field}__gte": start, f"{field}__lte": end})


def _total(qs, expression):
    """Sum an expression over a queryset, treating "this model has no such
    weight" as zero rather than as an error."""
    if expression is None:
        return Decimal("0")
    return qs.aggregate(total=Sum(expression))["total"] or Decimal("0")


def _open_queryset(process):
    """Work started here and not finished: what is physically on the floor."""
    return process.main_queryset(None)


def _incoming_count(process):
    incoming = process.incoming_queryset(None)
    return incoming.count() if incoming is not None else 0


def _percent(part, whole):
    return round(float(part) / float(whole) * 100, 1) if whole else 0.0


def _delta(now, before):
    """Percentage change, or None when there is nothing to compare with."""
    if not before:
        return None
    return round((float(now) - float(before)) / float(before) * 100, 1)


# ---------------------------------------------------------------------------
def kpis(start, end):
    """Four numbers, each against the same length of time before it."""
    previous_start, previous_end = _window_before(start, end)

    in_progress_kg = Decimal("0")
    open_count = 0
    for process in PROCESSES:
        fields = _fields(process.model)
        open_qs = _open_queryset(process)
        in_progress_kg += _total(open_qs, fields["received"])
        open_count += open_qs.count()

    def completed_and_weight(window_start, window_end):
        count = 0
        received = wastage = Decimal("0")
        for process in PROCESSES:
            fields = _fields(process.model)
            done = _completed_in(process, window_start, window_end)
            count += done.count()
            received += _total(done, fields["received"])
            wastage += _total(done, fields["wastage"])
        return count, received, wastage

    done_now, received_now, wastage_now = completed_and_weight(start, end)
    done_before, received_before, wastage_before = completed_and_weight(previous_start, previous_end)

    today_start = timezone.localtime(end).replace(hour=0, minute=0, second=0, microsecond=0)
    completed_today = sum(_completed_in(p, today_start, end).count() for p in PROCESSES)
    completed_yesterday = sum(
        _completed_in(p, today_start - datetime.timedelta(days=1), today_start).count()
        for p in PROCESSES
    )

    waiting = sum(_incoming_count(process) for process in PROCESSES)

    return [
        {
            "key": "in_progress",
            "label": "Material in progress",
            "value": round(float(in_progress_kg), 1),
            "unit": "kg",
            "note": f"{open_count} open record{'' if open_count == 1 else 's'}",
            "delta": None,
        },
        {
            "key": "completed_today",
            "label": "Completed today",
            "value": completed_today,
            "unit": "",
            "note": "operations finished",
            "delta": _delta(completed_today, completed_yesterday),
            "delta_note": "vs yesterday",
        },
        {
            "key": "wastage",
            "label": "Wastage",
            "value": _percent(wastage_now, received_now),
            "unit": "%",
            "note": f"{round(float(wastage_now), 1)} kg of {round(float(received_now), 1)} kg",
            "delta": _delta(_percent(wastage_now, received_now), _percent(wastage_before, received_before)),
            "delta_note": "vs prior period",
            "lower_is_better": True,
        },
        {
            "key": "waiting",
            "label": "Waiting to be picked up",
            "value": waiting,
            "unit": "",
            "note": "lots on an incoming list",
            "delta": None,
        },
    ]


def flow_by_process(start, end):
    """One column per process: what is waiting, what is open, what finished
    in the window, and the weight that went in against the weight that came
    out."""
    rows = []
    for process in PROCESSES:
        fields = _fields(process.model)
        done = _completed_in(process, start, end)
        received = _total(done, fields["received"])
        output = _total(done, fields["output"])
        wastage = _total(done, fields["wastage"])
        rows.append({
            "slug": process.slug,
            "label": process.label,
            "icon": process.icon,
            "incoming": _incoming_count(process),
            "in_progress": _open_queryset(process).count(),
            "completed": done.count(),
            "received_kg": round(float(received), 1),
            "output_kg": round(float(output), 1),
            "wastage_kg": round(float(wastage), 1),
            "wastage_pct": _percent(wastage, received),
            "yield_pct": _percent(output, received),
        })
    return rows


def daily_throughput(start, end):
    """Output weight per day, one series per process."""
    labels, series = [], []
    day = timezone.localtime(start).date()
    last = timezone.localtime(end).date()
    while day <= last:
        labels.append(day.isoformat())
        day += datetime.timedelta(days=1)

    for process in PROCESSES:
        fields = _fields(process.model)
        by_day = {}
        if fields["completed"] and fields["output"] is not None:
            rows = (
                _completed_in(process, start, end)
                .annotate(day=TruncDate(fields["completed"]))
                .values("day")
                .annotate(total=Sum(fields["output"]))
            )
            by_day = {row["day"].isoformat(): round(float(row["total"] or 0), 1) for row in rows if row["day"]}
        series.append({
            "label": process.label,
            "slug": process.slug,
            "data": [by_day.get(label, 0) for label in labels],
        })
    return {"labels": labels, "series": series, "empty": not any(any(s["data"]) for s in series)}


def wastage_trend(weeks=12):
    """Weekly wastage %, one series per process."""
    end = timezone.now()
    start = end - datetime.timedelta(weeks=weeks)
    labels = []
    buckets = []
    cursor = timezone.localtime(start).date()
    cursor -= datetime.timedelta(days=cursor.weekday())
    while cursor <= timezone.localtime(end).date():
        buckets.append(cursor)
        labels.append(cursor.isoformat())
        cursor += datetime.timedelta(weeks=1)

    series = []
    for process in PROCESSES:
        fields = _fields(process.model)
        by_week = {}
        if fields["completed"] and fields["wastage"] is not None and fields["received"] is not None:
            rows = (
                _completed_in(process, start, end)
                .annotate(week=TruncWeek(fields["completed"]))
                .values("week")
                .annotate(wastage=Sum(fields["wastage"]), received=Sum(fields["received"]))
            )
            by_week = {
                row["week"].date().isoformat(): _percent(row["wastage"] or 0, row["received"] or 0)
                for row in rows if row["week"]
            }
        series.append({
            "label": process.label,
            "slug": process.slug,
            "data": [by_week.get(label) for label in labels],
        })
    return {
        "labels": labels,
        "series": series,
        "empty": not any(any(v is not None for v in s["data"]) for s in series),
    }


def traveller_type_mix(start, end, top=8):
    """What the line actually ran, by weight, from the origin process - the
    only one that knows a traveller type first-hand."""
    origin = PROCESSES[0]
    fields = _fields(origin.model)
    if fields["output"] is None:
        return {"labels": [], "data": [], "empty": True}

    rows = list(
        _completed_in(origin, start, end)
        .values("traveller_type__name")
        .annotate(total=Sum(fields["output"]))
        .order_by("-total")
    )
    labels = [row["traveller_type__name"] or "-" for row in rows[:top]]
    data = [round(float(row["total"] or 0), 1) for row in rows[:top]]
    rest = sum(float(row["total"] or 0) for row in rows[top:])
    if rest:
        labels.append("Other")
        data.append(round(rest, 1))
    return {"labels": labels, "data": data, "empty": not data}


def rack_occupancy():
    """Every storage area in one shape: the raw-material coil bay and each
    storage zone."""
    bars = []
    coil_capacity = RackMaster.objects.filter(is_active=True).aggregate(total=Sum("capacity"))["total"] or 0
    coils_on_racks = CoilMaster.objects.filter(status="In Stock", rack__isnull=False).count()
    if coil_capacity:
        bars.append(_bar("Raw material coils", coils_on_racks, coil_capacity))

    for zone in RackZone.objects.filter(is_active=True).order_by("code"):
        total = RackSlot.objects.filter(zone=zone).count()
        occupied = RackSlot.objects.filter(zone=zone, lot__isnull=False).count()
        bars.append(_bar(zone.name, occupied, total))
    return bars


def _bar(label, occupied, total):
    """A bar never runs past its end: a bay holding more than its nominal
    capacity reads 100% and says so in its numbers."""
    pct = _percent(occupied, total)
    return {
        "label": label,
        "occupied": occupied,
        "total": total,
        "pct": min(pct, 100.0),
        "over_capacity": pct > 100,
    }


def recent_completions(limit=8):
    """The last thing that finished anywhere on the line."""
    rows = []
    for process in PROCESSES:
        fields = _fields(process.model)
        if not fields["completed"]:
            continue
        for record in (
            process.complete_queryset(None)
            .order_by(f"-{fields['completed']}")[:limit]
        ):
            traveller_type = record.traveller_type
            rows.append({
                "process": process.label,
                "slug": process.slug,
                "wire_serial": record.wire_serial,
                "traveller_type": traveller_type.name if traveller_type else "",
                "output_kg": round(float(record.output_weight or 0), 1),
                "when": getattr(record, fields["completed"], None),
            })
    rows = [row for row in rows if row["when"]]
    rows.sort(key=lambda row: row["when"], reverse=True)
    return rows[:limit]


def overview(range_key=DEFAULT_RANGE):
    """Everything the dashboard renders, in one call."""
    key, start, end = resolve_range(range_key)
    return {
        "range": key,
        "ranges": list(RANGES),
        "range_start": start,
        "range_end": end,
        "kpis": kpis(start, end),
        "flow": flow_by_process(start, end),
        "throughput": daily_throughput(start, end),
        "wastage": wastage_trend(),
        "traveller_mix": traveller_type_mix(start, end),
        "racks": rack_occupancy(),
        "completions": recent_completions(),
    }
