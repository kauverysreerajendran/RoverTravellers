from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import models, serializers, services


class RawMaterialStockViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.RawMaterialStock.objects.select_related("material", "location").all()
    serializer_class = serializers.RawMaterialStockSerializer
    filterset_fields = ["material", "location", "status"]
    search_fields = ["material__material_code", "material__name"]


class WIPStockViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.WIPStock.objects.select_related("lot", "location").all()
    serializer_class = serializers.WIPStockSerializer
    filterset_fields = ["stage", "lot", "location", "status"]
    search_fields = ["lot__lot_number"]


class FinishedGoodsStockViewSet(viewsets.ModelViewSet):
    queryset = models.FinishedGoodsStock.objects.select_related("product", "lot", "location").all()
    serializer_class = serializers.FinishedGoodsStockSerializer
    filterset_fields = ["product", "status", "quality_approved"]
    search_fields = ["fg_lot_number", "lot__lot_number"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)


class StockTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.StockTransaction.objects.select_related("material", "lot", "location").all()
    serializer_class = serializers.StockTransactionSerializer
    filterset_fields = ["stock_type", "movement_type", "material", "lot", "location"]
    search_fields = ["reference_number"]
    ordering_fields = ["created_at"]


class StockAdjustmentViewSet(viewsets.ModelViewSet):
    queryset = models.StockAdjustment.objects.all()
    serializer_class = serializers.StockAdjustmentSerializer
    filterset_fields = ["stock_type"]

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        try:
            services.apply_adjustment(instance, user=self.request.user)
        except DjangoValidationError as exc:
            instance.delete()
            raise


class StockTransferViewSet(viewsets.ModelViewSet):
    queryset = models.StockTransfer.objects.all()
    serializer_class = serializers.StockTransferSerializer
    filterset_fields = ["stock_type", "status"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        transfer = self.get_object()
        try:
            services.transfer_stock(transfer, user=request.user)
        except DjangoValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(transfer).data)
