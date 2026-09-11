from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("finished-goods", api_views.FinishedGoodsViewSet, basename="api-finished-goods")

urlpatterns = router.urls
