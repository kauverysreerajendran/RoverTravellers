from django.urls import path
from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("traveller-types", api_views.TravellerTypeViewSet, basename="api-traveller-type")
router.register("traveller-numbers", api_views.TravellerNoViewSet, basename="api-traveller-no")
router.register("surface-finishes", api_views.SurfaceFinishViewSet, basename="api-surface-finish")
router.register("racks", api_views.RackMasterViewSet, basename="api-rack-master")
router.register("diameters", api_views.DiameterMasterViewSet, basename="api-diameter-master")

urlpatterns = [
    path("coils/", api_views.coils_for_diameter, name="api-coils"),
] + router.urls
