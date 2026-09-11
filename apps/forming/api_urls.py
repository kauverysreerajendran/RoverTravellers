from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("forming", api_views.FormingTransactionViewSet, basename="api-forming")

urlpatterns = router.urls
