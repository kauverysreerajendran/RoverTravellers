from rest_framework import serializers

from .models import FinishingTransaction


class FinishingTransactionSerializer(serializers.ModelSerializer):
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)

    class Meta:
        model = FinishingTransaction
        fields = [
            "id", "transaction_number", "lot", "lot_number", "finishing_operation", "surface_finish_spec",
            "machine", "operator", "shift", "start_time", "end_time", "input_quantity", "output_quantity",
            "rejection_quantity", "rejection_reason", "status", "remarks", "created_at", "updated_at",
        ]
        read_only_fields = ["transaction_number", "status"]
