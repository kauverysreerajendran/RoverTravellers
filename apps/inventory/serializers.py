from rest_framework import serializers

from . import models


class RawMaterialStockSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.material_code", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)

    class Meta:
        model = models.RawMaterialStock
        fields = ["id", "material", "material_code", "location", "location_name", "quantity", "status"]


class WIPStockSerializer(serializers.ModelSerializer):
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)

    class Meta:
        model = models.WIPStock
        fields = ["id", "stage", "lot", "lot_number", "location", "location_name", "quantity", "status"]


class FinishedGoodsStockSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.product_code", read_only=True)
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)

    class Meta:
        model = models.FinishedGoodsStock
        fields = [
            "id", "fg_lot_number", "product", "product_code", "lot", "lot_number", "location", "rack", "shelf",
            "tray", "accepted_quantity", "rejected_quantity", "quality_approved", "status", "created_at",
        ]
        read_only_fields = ["fg_lot_number"]


class StockTransactionSerializer(serializers.ModelSerializer):
    material_code = serializers.CharField(source="material.material_code", read_only=True, default=None)
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True, default=None)

    class Meta:
        model = models.StockTransaction
        fields = [
            "id", "stock_type", "movement_type", "material", "material_code", "product", "lot", "lot_number",
            "location", "quantity", "balance_after", "reference_number", "remarks", "created_at",
        ]


class StockAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.StockAdjustment
        fields = "__all__"
        read_only_fields = ["adjustment_number", "quantity_before"]


class StockTransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.StockTransfer
        fields = "__all__"
        read_only_fields = ["transfer_number", "status"]
