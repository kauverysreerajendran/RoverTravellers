from rest_framework import viewsets

from . import models, serializers


class ProductionOrderViewSet(viewsets.ModelViewSet):
    queryset = models.ProductionOrder.objects.select_related("product").all()
    serializer_class = serializers.ProductionOrderSerializer
    filterset_fields = ["status", "product"]
    search_fields = ["order_number"]
    ordering_fields = ["created_at", "due_date"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class ProductionLotViewSet(viewsets.ModelViewSet):
    queryset = models.ProductionLot.objects.select_related("production_order").all()
    serializer_class = serializers.ProductionLotSerializer
    filterset_fields = ["current_stage", "is_on_hold", "production_order"]
    search_fields = ["lot_number"]
    ordering_fields = ["created_at"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
