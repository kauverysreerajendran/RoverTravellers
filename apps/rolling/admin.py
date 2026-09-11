from django.contrib import admin

from .models import RollingBatch, RollingBatchCoil


class RollingBatchCoilInline(admin.TabularInline):
    model = RollingBatchCoil
    extra = 0


@admin.register(RollingBatch)
class RollingBatchAdmin(admin.ModelAdmin):
    list_display = (
        "wire_serial", "traveller_type", "finish", "wire_diameter_mm",
        "wire_weight_issued_kg", "status", "wastage_kg", "created_at",
    )
    list_filter = ("status", "finish")
    search_fields = ("wire_serial",)
    inlines = [RollingBatchCoilInline]
