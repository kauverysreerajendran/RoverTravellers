from decimal import Decimal

from django.db.models import F, Sum

from apps.audit.models import AuditLog
from apps.finishing.models import FinishingTransaction
from apps.forming.models import FormingTransaction
from apps.heat_treatment.models import HeatTreatmentTransaction
from apps.inventory.models import FinishedGoodsStock, RawMaterialStock, WIPStock
from apps.master_data.models import MaterialMaster
from apps.production.models import ProductionLot, ProductionOrder
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
    active_lots = ProductionLot.objects.exclude(current_stage="finished_goods").count()

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
