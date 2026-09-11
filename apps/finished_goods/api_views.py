from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.models import FinishedGoodsStock
from apps.master_data.models import Location, ProductMaster, Rack, Shelf, Tray

from . import services
from .serializers import FinishedGoodsReceiveSerializer, FinishedGoodsStockSerializer


class FinishedGoodsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = FinishedGoodsStock.objects.select_related("product", "lot", "location").all()
    serializer_class = FinishedGoodsStockSerializer
    filterset_fields = ["status", "quality_approved", "product"]
    search_fields = ["fg_lot_number", "lot__lot_number"]
    ordering_fields = ["created_at"]

    @action(detail=False, methods=["post"])
    def receive(self, request):
        serializer = FinishedGoodsReceiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            fg_stock = services.receive_finished_goods(
                lot=data["lot"],
                product=ProductMaster.objects.get(pk=data["product_id"]),
                accepted_quantity=data["accepted_quantity"],
                rejected_quantity=data.get("rejected_quantity", 0),
                location=Location.objects.get(pk=data["location_id"]),
                rack=Rack.objects.filter(pk=data.get("rack_id")).first(),
                shelf=Shelf.objects.filter(pk=data.get("shelf_id")).first(),
                tray=Tray.objects.filter(pk=data.get("tray_id")).first(),
                user=request.user,
                remarks=data.get("remarks", ""),
            )
        except (DjangoValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(FinishedGoodsStockSerializer(fg_stock).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        fg_stock = self.get_object()
        try:
            services.approve_finished_goods(fg_stock, request.user)
        except (DjangoValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(FinishedGoodsStockSerializer(fg_stock).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        fg_stock = self.get_object()
        try:
            services.reject_finished_goods(fg_stock, request.user, remarks=request.data.get("remarks", ""))
        except (DjangoValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(FinishedGoodsStockSerializer(fg_stock).data)
