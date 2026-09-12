from django.contrib import admin

from .models import HeatBatch, HeatTreatmentTransaction


@admin.register(HeatTreatmentTransaction)
class HeatTreatmentTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_number", "lot", "machine", "heat_treatment_type", "status", "input_quantity", "output_quantity")
    list_filter = ("status", "heat_treatment_type", "machine")
    search_fields = ("transaction_number", "lot__lot_number", "batch_number")


@admin.register(HeatBatch)
class HeatBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_no", "status", "created_at", "completed_at", "created_by")
    list_filter = ("status",)
    search_fields = ("batch_no", "transactions__lot__source_rolling_batch__wire_serial")
    readonly_fields = ("qr_token",)
