from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.masters.models import SurfaceFinish, TravellerNo, TravellerType

from . import services
from .models import RollingBatch
from .serializers import RollingBatchSerializer, RollingCompleteSerializer, RollingInitiateSerializer


class RollingBatchViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RollingBatch.objects.select_related("traveller_type", "traveller_no", "finish").prefetch_related(
        "coils_used__coil"
    )
    serializer_class = RollingBatchSerializer
    filterset_fields = ["status", "traveller_type", "finish"]
    search_fields = ["wire_serial"]
    ordering_fields = ["created_at"]

    @action(detail=False, methods=["post"])
    def initiate(self, request):
        serializer = RollingInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            batch = services.initiate_rolling_batch(
                traveller_type=TravellerType.objects.get(pk=data["traveller_type_id"]),
                traveller_no=TravellerNo.objects.get(pk=data["traveller_no_id"]),
                finish=SurfaceFinish.objects.get(pk=data["finish_id"]),
                required_box=data["required_box"],
                wire_weight_issued_kg=data["wire_weight_issued_kg"],
                coil_weights=[(c["coil_id"], c["weight_taken_kg"]) for c in data["coils"]],
                user=request.user,
            )
        except (DjangoValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RollingBatchSerializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["put"])
    def complete(self, request, pk=None):
        batch = self.get_object()
        serializer = RollingCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.complete_rolling_batch(batch, user=request.user, **serializer.validated_data)
        except (DjangoValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RollingBatchSerializer(batch).data)
