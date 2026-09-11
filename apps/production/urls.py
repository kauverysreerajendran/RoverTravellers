from django.urls import path

from . import views

app_name = "production"

urlpatterns = [
    path("orders/", views.ProductionOrderListView.as_view(), name="order_list"),
    path("orders/create/", views.ProductionOrderCreateView.as_view(), name="order_create"),
    path("orders/<uuid:pk>/", views.ProductionOrderDetailView.as_view(), name="order_detail"),
    path("lots/", views.ProductionLotListView.as_view(), name="lot_list"),
    path("lots/create/", views.ProductionLotCreateView.as_view(), name="lot_create"),
    path("lots/<uuid:pk>/", views.ProductionLotDetailView.as_view(), name="lot_detail"),
    path("process-tracker/", views.ProcessTrackerView.as_view(), name="process_tracker"),
]
