from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import models, serializers


class TravellerTypeViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/traveller-types?search={q}  -> typeahead
    GET /api/traveller-types/{id}/mapping   -> wire diameter / F-thickness / F-width
    """

    queryset = models.TravellerType.objects.filter(is_active=True)
    serializer_class = serializers.TravellerTypeSerializer
    search_fields = ["name"]
    ordering_fields = ["seq_no", "name"]

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    @action(detail=True, methods=["get"])
    def mapping(self, request, pk=None):
        traveller_type = self.get_object()
        mapping = getattr(traveller_type, "mapping", None)
        if mapping is None:
            return Response(
                {"detail": "No raw material mapping found for this traveller type."},
                status=status.HTTP_404_NOT_FOUND,
            )
        data = {
            "raw_material_id": mapping.raw_material_id,
            "wire_diameter_mm": mapping.raw_material.diameter_mm,
            "f_thickness_mm": mapping.f_thickness_mm,
            "f_width_mm": mapping.f_width_mm,
        }
        return Response(serializers.MappingSerializer(data).data)


class TravellerNoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.TravellerNo.objects.filter(is_active=True)
    serializer_class = serializers.TravellerNoSerializer
    pagination_class = None


class SurfaceFinishViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.SurfaceFinish.objects.filter(is_active=True)
    serializer_class = serializers.SurfaceFinishSerializer
    pagination_class = None


class RackMasterViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.RackMaster.objects.filter(is_active=True)
    serializer_class = serializers.RackMasterSerializer
    pagination_class = None


class DiameterMasterViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = models.DiameterMaster.objects.filter(status="Active")
    serializer_class = serializers.DiameterMasterSerializer
    filterset_fields = ["status"]
    search_fields = ["raw_material_id"]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def coils_for_diameter(request):
    """GET /api/coils?raw_material_id={id} -> In Stock coils for that diameter."""
    raw_material_id = request.query_params.get("raw_material_id")
    if not raw_material_id:
        return Response({"detail": "raw_material_id query parameter is required."}, status=400)
    coils = models.CoilMaster.objects.filter(
        raw_material_id=raw_material_id, status="In Stock"
    ).select_related("rack").order_by("coil_display_number")
    return Response(serializers.CoilSerializer(coils, many=True).data)
