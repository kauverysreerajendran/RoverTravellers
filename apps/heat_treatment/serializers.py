from rest_framework import serializers

from django.urls import reverse

from .models import HeatBatch, HeatTreatmentTransaction


class HeatTreatmentTransactionSerializer(serializers.ModelSerializer):
    lot_number = serializers.CharField(source="lot.lot_number", read_only=True)

    class Meta:
        model = HeatTreatmentTransaction
        fields = [
            "id", "transaction_number", "lot", "lot_number", "batch_number", "heat_treatment_type",
            "temperature_celsius", "holding_time_minutes", "machine", "operator", "shift",
            "start_time", "end_time", "input_quantity", "output_quantity", "rejection_quantity",
            "rejection_reason", "status", "remarks", "created_at", "updated_at",
        ]
        read_only_fields = ["transaction_number", "status"]


class HeatBatchSerializer(serializers.ModelSerializer):
    """What the Locate-me box and the batch typeahead need: enough to
    recognise a load and reach it, with no extra round trip."""

    traveller_types = serializers.SerializerMethodField()
    wire_serials = serializers.SerializerMethodField()
    lot_count = serializers.SerializerMethodField()
    received_weight_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    output_weight_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    url = serializers.SerializerMethodField()
    qr_url = serializers.SerializerMethodField()
    label_url = serializers.SerializerMethodField()

    class Meta:
        model = HeatBatch
        fields = [
            "batch_no", "status", "created_at", "completed_at", "qr_token",
            "traveller_types", "wire_serials", "lot_count",
            "received_weight_total", "output_weight_total", "url", "qr_url", "label_url",
        ]

    def get_traveller_types(self, batch):
        return [t.name for t in batch.traveller_types]

    def get_wire_serials(self, batch):
        return batch.wire_serials

    def get_lot_count(self, batch):
        return batch.transactions.count()

    def get_url(self, batch):
        return reverse("heat_treatment:batch_detail", kwargs={"batch_no": batch.batch_no})

    def get_qr_url(self, batch):
        return reverse("scan_qr", kwargs={"token": batch.qr_token})

    def get_label_url(self, batch):
        return reverse("heat_treatment:batch_label", kwargs={"batch_no": batch.batch_no})
