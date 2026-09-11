from django.contrib import admin

from . import models


@admin.register(models.UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(models.Plant)
class PlantAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


@admin.register(models.Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "plant", "is_active")
    list_filter = ("plant",)


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "plant", "location_type", "is_active")
    list_filter = ("plant", "location_type")


@admin.register(models.Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ("code", "location", "is_active")


@admin.register(models.Shelf)
class ShelfAdmin(admin.ModelAdmin):
    list_display = ("code", "rack", "is_active")


@admin.register(models.Tray)
class TrayAdmin(admin.ModelAdmin):
    list_display = ("code", "shelf", "is_active")


@admin.register(models.Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "stage", "plant", "is_operational", "is_active")
    list_filter = ("stage", "plant", "is_operational")
    search_fields = ("code", "name")


@admin.register(models.Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "contact_person", "phone", "is_active")
    search_fields = ("code", "name")


@admin.register(models.Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "start_time", "end_time", "is_active")


@admin.register(models.Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_code", "first_name", "last_name", "department", "designation", "is_active")
    search_fields = ("employee_code", "first_name", "last_name")
    list_filter = ("department",)


@admin.register(models.ProcessMaster)
class ProcessMasterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "stage", "sequence", "is_active")
    list_filter = ("stage",)


@admin.register(models.ReasonCode)
class ReasonCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "description", "category", "is_active")
    list_filter = ("category",)


class ProductSpecificationInline(admin.TabularInline):
    model = models.ProductSpecification
    extra = 1


@admin.register(models.MaterialMaster)
class MaterialMasterAdmin(admin.ModelAdmin):
    list_display = ("material_code", "name", "material_type", "unit_of_measure", "reorder_level", "is_active")
    search_fields = ("material_code", "name")
    list_filter = ("material_type",)


@admin.register(models.ProductMaster)
class ProductMasterAdmin(admin.ModelAdmin):
    list_display = ("product_code", "name", "unit_of_measure", "raw_material", "is_active")
    search_fields = ("product_code", "name")
    inlines = [ProductSpecificationInline]
