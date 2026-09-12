from django.urls import path

from . import views

app_name = "masters"

urlpatterns = [
    path("racks/", views.RackLocatorView.as_view(), name="rack_locator"),
    path("racks/<str:code>/", views.RackZoneView.as_view(), name="rack_zone"),
    path("inventory/", views.DiameterListView.as_view(), name="diameter_list"),
    path("inventory/<str:pk>/", views.DiameterDetailView.as_view(), name="diameter_detail"),
]
