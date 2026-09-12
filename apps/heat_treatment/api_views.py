from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.production.services import complete_stage

from . import services
from .models import HeatBatch, HeatTreatmentTransaction
from .serializers import HeatBatchSerializer, HeatTreatmentTransactionSerializer


class HeatTreatmentTransactionViewSet(viewsets.ModelViewSet):
    queryset = HeatTreatmentTransaction.objects.select_related("lot", "machine", "operator", "shift").all()
    serializer_class = HeatTreatmentTransactionSerializer
    filterset_fields = ["status", "machine", "lot", "heat_treatment_type"]
    search_fields = ["transaction_number", "lot__lot_number", "batch_number"]
    ordering_fields = ["created_at", "start_time"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.status == "completed":
            raise DjangoValidationError("Completed transactions cannot be edited.")
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        operation = self.get_object()
        try:
            complete_stage(operation, request.user)
        except (DjangoValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(operation).data)


class HeatBatchViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/heat-batches/?search={q}      -> typeahead over batch no,
                                                 wire serial, traveller type
    GET /api/heat-batches/?status=completed   -> what the Complete Table shows

    The completed set is read through the process registry's own
    `complete_queryset`, so the dropdown can never drift from the table.
    """

    serializer_class = HeatBatchSerializer
    lookup_field = "batch_no"
    pagination_class = None

    def get_queryset(self):
        params = self.request.query_params
        status_filter = params.get("status", "")
        if status_filter == "completed":
            process = services.process()
            batch_ids = process.complete_queryset(self.request).values_list("heat_batch_id", flat=True)
            batches = HeatBatch.objects.filter(pk__in=[b for b in batch_ids if b])
            search = params.get("search", "").strip()
            if search:
                matched = [b.pk for b in services.search_heat_batches(search, limit=200)]
                # Keep the search's own order: an exact batch number first.
                found = {b.pk: b for b in batches.filter(pk__in=matched)}
                return [found[pk] for pk in matched if pk in found][:services.SEARCH_LIMIT]
            return list(batches.order_by("-created_at")[:services.SEARCH_LIMIT])
        return services.search_heat_batches(params.get("search", ""), status=status_filter)
