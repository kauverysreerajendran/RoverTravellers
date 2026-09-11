from django.contrib import admin

from . import models


@admin.register(models.TravellerType)
class TravellerTypeAdmin(admin.ModelAdmin):
    list_display = ("seq_no", "name", "is_active")
    search_fields = ("name",)
    ordering = ("seq_no",)


@admin.register(models.TravellerNo)
class TravellerNoAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "is_active")


@admin.register(models.SurfaceFinish)
class SurfaceFinishAdmin(admin.ModelAdmin):
    list_display = ("finish_name", "is_active")
    search_fields = ("finish_name",)


@admin.register(models.RackMaster)
class RackMasterAdmin(admin.ModelAdmin):
    list_display = ("rack_code", "is_active")
    search_fields = ("rack_code",)


class CoilInline(admin.TabularInline):
    model = models.CoilMaster
    extra = 0
    fields = ("coil_display_number", "weight_kg", "status", "rack", "supplier", "received_date")
    readonly_fields = ("coil_display_number",)


@admin.register(models.DiameterMaster)
class DiameterMasterAdmin(admin.ModelAdmin):
    list_display = ("raw_material_id", "diameter_mm", "unit", "total_stock", "active_coils", "status")
    search_fields = ("raw_material_id",)
    readonly_fields = ("total_stock", "active_coils")
    inlines = [CoilInline]


@admin.register(models.CoilMaster)
class CoilMasterAdmin(admin.ModelAdmin):
    list_display = ("coil_id", "raw_material", "coil_display_number", "weight_kg", "status", "rack")
    list_filter = ("status", "rack")
    search_fields = ("raw_material__raw_material_id",)


@admin.register(models.DiameterTravellerMapping)
class DiameterTravellerMappingAdmin(admin.ModelAdmin):
    list_display = ("traveller_type", "raw_material", "f_thickness_mm", "f_width_mm")
    search_fields = ("traveller_type__name", "raw_material__raw_material_id")


@admin.register(models.WireSerialMaster)
class WireSerialMasterAdmin(admin.ModelAdmin):
    list_display = ("serial_no", "prefix", "sequence", "status", "used_at")
    list_filter = ("status", "prefix")
    search_fields = ("serial_no",)
    ordering = ("sort_order",)
    readonly_fields = ("serial_no", "prefix", "sequence", "sort_order", "used_at")

    def has_add_permission(self, request):
        return False
