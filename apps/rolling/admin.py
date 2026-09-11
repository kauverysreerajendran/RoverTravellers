from django.contrib import admin

from .models import RollingTransaction


@admin.register(RollingTransaction)
class RollingTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_number", "lot", "raw_material", "machine", "status", "input_quantity", "output_quantity", "rejection_quantity")
    list_filter = ("status", "machine")
    search_fields = ("transaction_number", "lot__lot_number")
