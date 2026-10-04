from decimal import Decimal
from urllib.parse import urlencode

from django.urls import reverse
from rest_framework import serializers

from apps.masters.serializers import CoilSerializer

from .models import RollingBatch, RollingBatchCoil


class RollingBatchCoilInputSerializer(serializers.Serializer):
    coil_id = serializers.IntegerField()
    weight_taken_kg = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=Decimal("0.01"))


class RollingInitiateSerializer(serializers.Serializer):
    traveller_type_id = serializers.IntegerField()
    traveller_no_id = serializers.IntegerField()
    finish_id = serializers.IntegerField()
    required_box = serializers.IntegerField(min_value=1)
    wire_weight_issued_kg = serializers.DecimalField(max_digits=8, decimal_places=2)
    coils = RollingBatchCoilInputSerializer(many=True)


class RollingCompleteSerializer(serializers.Serializer):
    rolled_thickness_mm = serializers.DecimalField(max_digits=5, decimal_places=2)
    rolled_width_mm = serializers.DecimalField(max_digits=5, decimal_places=2)
    finished_weight_kg = serializers.DecimalField(max_digits=8, decimal_places=2)


class RollingBatchCoilSerializer(serializers.ModelSerializer):
    coil_display_number = serializers.IntegerField(source="coil.coil_display_number", read_only=True)

    class Meta:
        model = RollingBatchCoil
        fields = ["coil", "coil_display_number", "weight_taken_kg"]


class RollingBatchSerializer(serializers.ModelSerializer):
    traveller_type_name = serializers.CharField(source="traveller_type.name", read_only=True)
    finish_name = serializers.CharField(source="finish.finish_name", read_only=True)
    coils_used = RollingBatchCoilSerializer(many=True, read_only=True)

    class Meta:
        model = RollingBatch
        fields = [
            "batch_id", "wire_serial", "traveller_type", "traveller_type_name", "traveller_no", "finish",
            "finish_name", "wire_diameter_mm", "f_thickness_mm", "f_width_mm", "required_box",
            "wire_weight_issued_kg", "status", "rolled_thickness_mm", "rolled_width_mm", "finished_weight_kg",
            "wastage_kg", "coils_used", "created_at", "completed_at",
        ]
        read_only_fields = [
            "wire_serial", "wire_diameter_mm", "f_thickness_mm", "f_width_mm", "status",
            "rolled_thickness_mm", "rolled_width_mm", "finished_weight_kg", "wastage_kg",
        ]


def stock_check_payload(result, user):
    """JSON body for POST /api/rolling/stock-check/: the services.check_stock
    result with decimals as strings, the coils in the same shape as
    /api/coils/, and the links the modal offers next."""
    def text(value):
        return None if value is None else str(value)

    raw_material = result["raw_material"]
    payload = {
        "status": result["status"],
        "available": result["available"],
        "message": result["message"],
        "traveller_type": result["traveller_type"],
        "traveller_no": result["traveller_no"],
        "raw_material": raw_material and {
            "raw_material_id": raw_material["raw_material_id"],
            "diameter_mm": text(raw_material["diameter_mm"]),
        },
        "f_thickness_mm": text(result["f_thickness_mm"]),
        "f_width_mm": text(result["f_width_mm"]),
        "required_m": text(result["required_m"]),
        "required_kg": text(result["required_kg"]),
        "total_available_kg": text(result["total_available_kg"]),
        "available_m": text(result.get("available_m")),
        "shortfall_kg": text(result["shortfall_kg"]),
        "coils": CoilSerializer(result["coils"], many=True).data,
        "proceed_url": None,
        "proceed_label": "Proceed to Rolling",
        "inventory_url": None,
        # Set when this traveller's material is already in the line: the
        # stage it is at now, which is where the operator should go next.
        "current_stage": None,
    }
    if raw_material and not result["available"]:
        # Short of wire: the existing way to fix that is receiving coils on
        # the diameter's Inventory screen.
        payload["inventory_url"] = reverse("masters:diameter_detail", kwargs={"pk": raw_material["raw_material_id"]})
    if result["available"] and user.can_operate_stage("rolling"):
        payload["proceed_url"] = reverse("rolling:create") + "?" + urlencode({
            "traveller_type": result["traveller_type"]["id"],
            "traveller_no": result["traveller_no"]["id"],
            "required_m": text(result["required_m"]),
        })
    current = result.get("current")
    if current:
        process = current["process"]
        can_operate = user.can_operate_stage(process.slug)
        payload["current_stage"] = {
            "slug": process.slug,
            "label": process.label,
            "state": LOT_STATE_LABELS[current["state"]],
            "wire_serial": current["wire_serial"],
            "can_operate": can_operate,
            "button_label": f"{'Proceed to' if can_operate else 'View in'} {process.label}",
            # The stage's Main Table, filtered to this wire serial: it shows
            # the Initiate / Complete action for that lot.
            "url": _stage_url(process, completed=False, search=current["wire_serial"]),
        }
    return payload


LOT_STATE_LABELS = {"waiting": "Waiting", "in_progress": "In Progress", "completed": "Completed"}


def _stage_url(process, *, completed, search=""):
    """A process screen: its Main Table while the material is still open
    work there, its Complete Table once it has finished there."""
    url = reverse("process:complete" if completed else "process:main", kwargs={"process": process.slug})
    return f"{url}?{urlencode({'q': search})}" if search else url


def traveller_overview_payload(result):
    """JSON body for GET /api/rolling/stock-check/traveller/."""

    def text(value):
        return None if value is None else str(value)

    raw_material = result["raw_material"]
    stock, history = result["stock"], result["history"]
    return {
        "traveller_type": result["traveller_type"],
        "traveller_no": result["traveller_no"],
        "raw_material": raw_material and {
            "raw_material_id": raw_material["raw_material_id"],
            "diameter_mm": text(raw_material["diameter_mm"]),
        },
        "f_thickness_mm": text(result.get("f_thickness_mm")),
        "f_width_mm": text(result.get("f_width_mm")),
        "stock": stock and {key: text(value) if key != "coil_count" else value for key, value in stock.items()},
        "history": history and {key: text(value) if key != "batch_count" else value for key, value in history.items()},
        "stages": [
            {
                "slug": stage["process"].slug,
                "label": stage["process"].label,
                "count": stage["count"],
                "url": _stage_url(stage["process"], completed=stage["count"] > 0 and not stage["open"]),
            }
            for stage in result["stages"]
        ],
        "lot_count": result["lot_count"],
        "lots": [
            {
                "wire_serial": row["wire_serial"],
                "traveller_no": row["traveller_no"],
                "stage": row["process"].label if row["process"] else "Raw Material",
                "state": LOT_STATE_LABELS[row["state"]],
                "url": row["process"] and _stage_url(
                    row["process"], completed=row["state"] == "completed", search=row["wire_serial"]
                ),
            }
            for row in result["lots"]
        ],
    }
