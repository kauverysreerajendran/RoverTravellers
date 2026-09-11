from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("heat-treatment", api_views.HeatTreatmentTransactionViewSet, basename="api-heat-treatment")

urlpatterns = router.urls
