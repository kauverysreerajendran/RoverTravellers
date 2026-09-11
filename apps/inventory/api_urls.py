from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("inventory/raw-material", api_views.RawMaterialStockViewSet, basename="api-raw-material-stock")
router.register("inventory/wip", api_views.WIPStockViewSet, basename="api-wip-stock")
router.register("inventory/finished-goods", api_views.FinishedGoodsStockViewSet, basename="api-fg-stock")
router.register("inventory/transactions", api_views.StockTransactionViewSet, basename="api-stock-transaction")
router.register("inventory/adjustments", api_views.StockAdjustmentViewSet, basename="api-stock-adjustment")
router.register("inventory/transfers", api_views.StockTransferViewSet, basename="api-stock-transfer")

urlpatterns = router.urls
