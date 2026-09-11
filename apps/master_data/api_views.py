from rest_framework import viewsets

from . import models, serializers


class BaseMasterViewSet(viewsets.ModelViewSet):
    filterset_fields = []
    search_fields = ["name"]
    ordering_fields = "__all__"

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class UnitOfMeasureViewSet(BaseMasterViewSet):
    queryset = models.UnitOfMeasure.objects.all()
    serializer_class = serializers.UnitOfMeasureSerializer
    search_fields = ["code", "name"]


class PlantViewSet(BaseMasterViewSet):
    queryset = models.Plant.objects.all()
    serializer_class = serializers.PlantSerializer
    search_fields = ["code", "name"]


class DepartmentViewSet(BaseMasterViewSet):
    queryset = models.Department.objects.all()
    serializer_class = serializers.DepartmentSerializer
    filterset_fields = ["plant"]
    search_fields = ["code", "name"]


class LocationViewSet(BaseMasterViewSet):
    queryset = models.Location.objects.all()
    serializer_class = serializers.LocationSerializer
    filterset_fields = ["plant", "location_type"]
    search_fields = ["code", "name"]


class RackViewSet(BaseMasterViewSet):
    queryset = models.Rack.objects.all()
    serializer_class = serializers.RackSerializer
    filterset_fields = ["location"]


class ShelfViewSet(BaseMasterViewSet):
    queryset = models.Shelf.objects.all()
    serializer_class = serializers.ShelfSerializer
    filterset_fields = ["rack"]


class TrayViewSet(BaseMasterViewSet):
    queryset = models.Tray.objects.all()
    serializer_class = serializers.TraySerializer
    filterset_fields = ["shelf"]


class MachineViewSet(BaseMasterViewSet):
    queryset = models.Machine.objects.all()
    serializer_class = serializers.MachineSerializer
    filterset_fields = ["stage", "plant", "is_operational"]
    search_fields = ["code", "name"]


class VendorViewSet(BaseMasterViewSet):
    queryset = models.Vendor.objects.all()
    serializer_class = serializers.VendorSerializer
    search_fields = ["code", "name"]


class ShiftViewSet(BaseMasterViewSet):
    queryset = models.Shift.objects.all()
    serializer_class = serializers.ShiftSerializer
    search_fields = ["code", "name"]


class EmployeeViewSet(BaseMasterViewSet):
    queryset = models.Employee.objects.all()
    serializer_class = serializers.EmployeeSerializer
    filterset_fields = ["department"]
    search_fields = ["employee_code", "first_name", "last_name"]


class ProcessMasterViewSet(BaseMasterViewSet):
    queryset = models.ProcessMaster.objects.all()
    serializer_class = serializers.ProcessMasterSerializer
    filterset_fields = ["stage"]
    search_fields = ["code", "name"]


class ReasonCodeViewSet(BaseMasterViewSet):
    queryset = models.ReasonCode.objects.all()
    serializer_class = serializers.ReasonCodeSerializer
    filterset_fields = ["category"]
    search_fields = ["code", "description"]


class MaterialMasterViewSet(BaseMasterViewSet):
    queryset = models.MaterialMaster.objects.all()
    serializer_class = serializers.MaterialMasterSerializer
    filterset_fields = ["material_type", "is_active"]
    search_fields = ["material_code", "name", "grade"]


class ProductMasterViewSet(BaseMasterViewSet):
    queryset = models.ProductMaster.objects.all()
    serializer_class = serializers.ProductMasterSerializer
    filterset_fields = ["is_active"]
    search_fields = ["product_code", "name"]
