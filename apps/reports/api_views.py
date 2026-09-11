from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.services import STAGE_MODELS, get_stage_summary
from apps.production.models import ProductionLot, ProductionOrder


class ProductionReportAPIView(APIView):
    def get(self, request):
        orders = ProductionOrder.objects.select_related("product").order_by("-created_at")[:200]
        data = [
            {
                "order_number": o.order_number,
                "product": o.product.product_code,
                "planned_quantity": o.planned_quantity,
                "status": o.status,
                "due_date": o.due_date,
            }
            for o in orders
        ]
        return Response({"stage_summary": get_stage_summary(), "orders": data})


class TraceabilityReportAPIView(APIView):
    def get(self, request):
        lot_number = request.query_params.get("lot_number")
        if not lot_number:
            return Response({"detail": "lot_number query parameter is required."}, status=400)
        lot = ProductionLot.objects.filter(lot_number=lot_number).first()
        if not lot:
            return Response({"detail": "Lot not found."}, status=404)

        trace = {"lot_number": lot.lot_number, "current_stage": lot.current_stage, "stages": {}}
        for stage, model in STAGE_MODELS.items():
            trace["stages"][stage] = [
                {
                    "transaction_number": t.transaction_number,
                    "status": t.status,
                    "input_quantity": t.input_quantity,
                    "output_quantity": t.output_quantity,
                    "rejection_quantity": t.rejection_quantity,
                }
                for t in model.objects.filter(lot=lot)
            ]
        return Response(trace)
