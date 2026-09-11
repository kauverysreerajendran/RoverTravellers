from decimal import Decimal

from rest_framework import serializers

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
