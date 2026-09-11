from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("rolling", api_views.RollingBatchViewSet, basename="api-rolling")

urlpatterns = router.urls
