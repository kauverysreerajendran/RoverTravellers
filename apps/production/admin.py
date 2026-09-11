from django.contrib import admin

from . import models


@admin.register(models.ProductionOrder)
class ProductionOrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "product", "planned_quantity", "status", "due_date", "created_at")
    list_filter = ("status",)
    search_fields = ("order_number",)


@admin.register(models.ProductionLot)
class ProductionLotAdmin(admin.ModelAdmin):
    list_display = ("lot_number", "production_order", "current_stage", "quantity", "is_on_hold", "created_at")
    list_filter = ("current_stage", "is_on_hold")
    search_fields = ("lot_number",)


@admin.register(models.OperationQualityCheck)
class OperationQualityCheckAdmin(admin.ModelAdmin):
    list_display = ("parameter", "result", "inspector", "created_at")
    list_filter = ("result",)


@admin.register(models.OperationStatusHistory)
class OperationStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("from_status", "to_status", "created_at")
