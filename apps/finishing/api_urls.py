from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("finishing", api_views.FinishingTransactionViewSet, basename="api-finishing")

urlpatterns = router.urls
