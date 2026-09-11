from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("uom", api_views.UnitOfMeasureViewSet, basename="api-uom")
router.register("plants", api_views.PlantViewSet, basename="api-plant")
router.register("departments", api_views.DepartmentViewSet, basename="api-department")
router.register("locations", api_views.LocationViewSet, basename="api-location")
router.register("racks", api_views.RackViewSet, basename="api-rack")
router.register("shelves", api_views.ShelfViewSet, basename="api-shelf")
router.register("trays", api_views.TrayViewSet, basename="api-tray")
router.register("machines", api_views.MachineViewSet, basename="api-machine")
router.register("vendors", api_views.VendorViewSet, basename="api-vendor")
router.register("shifts", api_views.ShiftViewSet, basename="api-shift")
router.register("employees", api_views.EmployeeViewSet, basename="api-employee")
router.register("processes", api_views.ProcessMasterViewSet, basename="api-process")
router.register("reason-codes", api_views.ReasonCodeViewSet, basename="api-reason-code")
router.register("materials", api_views.MaterialMasterViewSet, basename="api-material")
router.register("products", api_views.ProductMasterViewSet, basename="api-product")

urlpatterns = router.urls
