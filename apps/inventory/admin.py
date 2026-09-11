from django.contrib import admin

from . import models


@admin.register(models.RawMaterialStock)
class RawMaterialStockAdmin(admin.ModelAdmin):
    list_display = ("material", "location", "quantity", "status")
    list_filter = ("status", "location")
    search_fields = ("material__material_code",)


@admin.register(models.WIPStock)
class WIPStockAdmin(admin.ModelAdmin):
    list_display = ("lot", "stage", "location", "quantity", "status")
    list_filter = ("stage", "status")
    search_fields = ("lot__lot_number",)


@admin.register(models.FinishedGoodsStock)
class FinishedGoodsStockAdmin(admin.ModelAdmin):
    list_display = ("fg_lot_number", "product", "lot", "accepted_quantity", "rejected_quantity", "status", "quality_approved")
    list_filter = ("status", "quality_approved")
    search_fields = ("fg_lot_number", "lot__lot_number")


@admin.register(models.StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "stock_type", "movement_type", "material", "lot", "location", "quantity", "balance_after")
    list_filter = ("stock_type", "movement_type")
    search_fields = ("reference_number",)

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("adjustment_number", "stock_type", "material", "lot", "quantity_before", "quantity_after", "created_at")


@admin.register(models.StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = ("transfer_number", "stock_type", "from_location", "to_location", "quantity", "status")
    list_filter = ("status", "stock_type")
