from rest_framework import serializers

from . import models


class ProductionOrderSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.product_code", read_only=True)

    class Meta:
        model = models.ProductionOrder
        fields = [
            "id", "order_number", "product", "product_code", "planned_quantity", "uom",
            "status", "due_date", "remarks", "created_at", "updated_at",
        ]
        read_only_fields = ["order_number"]


class ProductionLotSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="production_order.order_number", read_only=True)

    class Meta:
        model = models.ProductionLot
        fields = [
            "id", "lot_number", "production_order", "order_number", "current_stage",
            "quantity", "is_on_hold", "remarks", "created_at", "updated_at",
        ]
        read_only_fields = ["lot_number"]
