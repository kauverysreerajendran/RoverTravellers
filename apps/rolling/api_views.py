from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.masters.models import SurfaceFinish, TravellerNo, TravellerType

from . import services
from .models import RollingBatch
from .serializers import (
    RollingBatchSerializer, RollingCompleteSerializer, RollingInitiateSerializer, stock_check_payload,
    traveller_overview_payload,
)


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

    @action(detail=False, methods=["post"], url_path="stock-check")
    def stock_check(self, request):
        """POST /api/rolling/stock-check/ -> read-only stock check before a
        batch is started (see services.check_stock)."""
        try:
            result = services.check_stock(
                request.data.get("traveller_type_id"),
                request.data.get("traveller_no_id"),
                request.data.get("required_m"),
            )
        except DjangoValidationError as exc:
            errors = exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages}
            return Response({"errors": {k: v[0] for k, v in errors.items()}}, status=status.HTTP_400_BAD_REQUEST)
        return Response(stock_check_payload(result, request.user))

    @action(detail=False, methods=["get"], url_path="stock-check/traveller", url_name="stock-check-traveller")
    def stock_check_traveller(self, request):
        """GET /api/rolling/stock-check/traveller/?traveller_type_id=&traveller_no_id=
        -> stock guidance for Required M and where the traveller's material
        is now (see services.traveller_overview). Read-only."""
        try:
            result = services.traveller_overview(
                request.query_params.get("traveller_type_id"), request.query_params.get("traveller_no_id"),
            )
        except DjangoValidationError as exc:
            return Response({"errors": {k: v[0] for k, v in exc.message_dict.items()}}, status=status.HTTP_400_BAD_REQUEST)
        return Response(traveller_overview_payload(result))

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
