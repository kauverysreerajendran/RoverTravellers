from django.contrib import admin

from .models import HeatTreatmentTransaction


@admin.register(HeatTreatmentTransaction)
class HeatTreatmentTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_number", "lot", "machine", "heat_treatment_type", "status", "input_quantity", "output_quantity")
    list_filter = ("status", "heat_treatment_type", "machine")
    search_fields = ("transaction_number", "lot__lot_number", "batch_number")
