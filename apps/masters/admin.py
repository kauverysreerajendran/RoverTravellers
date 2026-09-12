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


@admin.register(models.RackZone)
class RackZoneAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "process_slug", "rack_count", "rows", "columns", "is_active")
    list_filter = ("is_active", "process_slug")
    search_fields = ("code", "name")


@admin.register(models.StorageRack)
class StorageRackAdmin(admin.ModelAdmin):
    list_display = ("code", "zone", "position", "is_active")
    list_filter = ("zone", "is_active")
    search_fields = ("code",)


@admin.register(models.RackSlot)
class RackSlotAdmin(admin.ModelAdmin):
    list_display = ("label", "rack", "row", "column", "lot", "placed_at")
    list_filter = ("zone", "rack")
    search_fields = ("rack__code", "lot__lot_number")
    raw_id_fields = ("lot",)


@admin.register(models.RackPlacement)
class RackPlacementAdmin(admin.ModelAdmin):
    list_display = ("slot", "lot", "placed_at", "released_at", "released_reason")
    list_filter = ("slot__zone",)
    search_fields = ("lot__lot_number", "slot__rack__code")
    raw_id_fields = ("slot", "lot")


@admin.register(models.BatchNoFormat)
class BatchNoFormatAdmin(admin.ModelAdmin):
    list_display = ("process_slug", "regex", "prefix", "pad", "is_active")
    list_filter = ("is_active",)
