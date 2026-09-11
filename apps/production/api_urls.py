from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("production-orders", api_views.ProductionOrderViewSet, basename="api-production-order")
router.register("lots", api_views.ProductionLotViewSet, basename="api-lot")

urlpatterns = router.urls
