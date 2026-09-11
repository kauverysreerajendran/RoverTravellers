from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.production.services import complete_stage

from .models import FormingTransaction
from .serializers import FormingTransactionSerializer


class FormingTransactionViewSet(viewsets.ModelViewSet):
    queryset = FormingTransaction.objects.select_related("lot", "machine", "operator", "shift").all()
    serializer_class = FormingTransactionSerializer
    filterset_fields = ["status", "machine", "lot"]
    search_fields = ["transaction_number", "lot__lot_number"]
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
            complete_stage(operation, request.user, current_stage="forming")
        except (DjangoValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(operation).data)
