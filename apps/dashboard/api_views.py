from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class DashboardSummaryView(APIView):
    def get(self, request):
        data = services.get_dashboard_summary()
        data["low_stock_alerts"] = [
            {
                "material_code": s.material.material_code,
                "material_name": s.material.name,
                "location": s.location.name,
                "quantity": s.quantity,
                "reorder_level": s.material.reorder_level,
            }
            for s in data["low_stock_alerts"]
        ]
        data["pending_qc_approvals"] = [
            {
                "fg_lot_number": fg.fg_lot_number,
                "product_code": fg.product.product_code,
                "lot_number": fg.lot.lot_number,
                "accepted_quantity": fg.accepted_quantity,
                "rejected_quantity": fg.rejected_quantity,
            }
            for fg in data["pending_qc_approvals"]
        ]
        data["recent_audit_logs"] = [
            {
                "user": str(log.user) if log.user else None,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "created_at": log.created_at,
            }
            for log in data["recent_audit_logs"]
        ]
        return Response(data)
