from rest_framework import serializers

from . import models


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.UnitOfMeasure
        fields = "__all__"


class PlantSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Plant
        fields = "__all__"


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Department
        fields = "__all__"


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Location
        fields = "__all__"


class RackSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Rack
        fields = "__all__"


class ShelfSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Shelf
        fields = "__all__"


class TraySerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Tray
        fields = "__all__"


class MachineSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Machine
        fields = "__all__"


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Vendor
        fields = "__all__"


class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Shift
        fields = "__all__"


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Employee
        fields = "__all__"


class ProcessMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ProcessMaster
        fields = "__all__"


class ReasonCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ReasonCode
        fields = "__all__"


class ProductSpecificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.ProductSpecification
        fields = "__all__"


class MaterialMasterSerializer(serializers.ModelSerializer):
    unit_of_measure_display = serializers.CharField(source="unit_of_measure.code", read_only=True)

    class Meta:
        model = models.MaterialMaster
        fields = "__all__"


class ProductMasterSerializer(serializers.ModelSerializer):
    specifications = ProductSpecificationSerializer(many=True, read_only=True)

    class Meta:
        model = models.ProductMaster
        fields = "__all__"
