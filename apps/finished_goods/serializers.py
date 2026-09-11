from decimal import Decimal

from rest_framework import serializers

from apps.inventory.models import FinishedGoodsStock
from apps.production.models import ProductionLot


class FinishedGoodsReceiveSerializer(serializers.Serializer):
    lot = serializers.PrimaryKeyRelatedField(queryset=ProductionLot.objects.all())
    product_id = serializers.UUIDField()
    accepted_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0"))
    rejected_quantity = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0"), default=0)
    location_id = serializers.UUIDField()
    rack_id = serializers.UUIDField(required=False, allow_null=True)
    shelf_id = serializers.UUIDField(required=False, allow_null=True)
    tray_id = serializers.UUIDField(required=False, allow_null=True)
    remarks = serializers.CharField(required=False, allow_blank=True)


class FinishedGoodsStockSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.product_code", read_only=True)
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)

    class Meta:
        model = FinishedGoodsStock
        fields = [
            "id", "fg_lot_number", "product", "product_code", "lot", "lot_number", "location", "rack", "shelf",
            "tray", "accepted_quantity", "rejected_quantity", "quality_approved", "status", "created_at",
        ]
        read_only_fields = ["fg_lot_number", "quality_approved", "status"]
