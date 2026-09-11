from rest_framework import serializers

from . import models


class TravellerTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TravellerType
        fields = ["traveller_type_id", "seq_no", "name"]


class TravellerNoSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.TravellerNo
        fields = ["traveller_no_id", "code", "label"]


class SurfaceFinishSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.SurfaceFinish
        fields = ["finish_id", "finish_name"]


class RackMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.RackMaster
        fields = ["rack_id", "rack_code"]


class MappingSerializer(serializers.Serializer):
    raw_material_id = serializers.CharField()
    wire_diameter_mm = serializers.DecimalField(max_digits=6, decimal_places=2)
    f_thickness_mm = serializers.DecimalField(max_digits=5, decimal_places=2)
    f_width_mm = serializers.DecimalField(max_digits=5, decimal_places=2)


class CoilSerializer(serializers.ModelSerializer):
    rack_code = serializers.CharField(source="rack.rack_code", read_only=True, default=None)

    class Meta:
        model = models.CoilMaster
        fields = ["coil_id", "coil_display_number", "weight_kg", "status", "rack", "rack_code"]


class DiameterMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.DiameterMaster
        fields = ["raw_material_id", "diameter_mm", "unit", "total_stock", "active_coils", "status"]
