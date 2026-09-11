from django.urls import path

from . import views

app_name = "master_data"

urlpatterns = [
    path("materials/", views.MaterialListView.as_view(), name="material_list"),
    path("materials/create/", views.MaterialCreateView.as_view(), name="material_create"),
    path("materials/<uuid:pk>/edit/", views.MaterialUpdateView.as_view(), name="material_edit"),

    path("products/", views.ProductListView.as_view(), name="product_list"),
    path("products/create/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<uuid:pk>/edit/", views.ProductUpdateView.as_view(), name="product_edit"),

    path("vendors/", views.VendorListView.as_view(), name="vendor_list"),
    path("vendors/create/", views.VendorCreateView.as_view(), name="vendor_create"),
    path("vendors/<uuid:pk>/edit/", views.VendorUpdateView.as_view(), name="vendor_edit"),

    path("locations/", views.LocationListView.as_view(), name="location_list"),
    path("locations/create/", views.LocationCreateView.as_view(), name="location_create"),
    path("locations/<uuid:pk>/edit/", views.LocationUpdateView.as_view(), name="location_edit"),

    path("racks/", views.RackListView.as_view(), name="rack_list"),
    path("racks/create/", views.RackCreateView.as_view(), name="rack_create"),

    path("shelves/", views.ShelfListView.as_view(), name="shelf_list"),
    path("shelves/create/", views.ShelfCreateView.as_view(), name="shelf_create"),

    path("trays/", views.TrayListView.as_view(), name="tray_list"),
    path("trays/create/", views.TrayCreateView.as_view(), name="tray_create"),

    path("machines/", views.MachineListView.as_view(), name="machine_list"),
    path("machines/create/", views.MachineCreateView.as_view(), name="machine_create"),
    path("machines/<uuid:pk>/edit/", views.MachineUpdateView.as_view(), name="machine_edit"),

    path("employees/", views.EmployeeListView.as_view(), name="employee_list"),
    path("employees/create/", views.EmployeeCreateView.as_view(), name="employee_create"),
    path("employees/<uuid:pk>/edit/", views.EmployeeUpdateView.as_view(), name="employee_edit"),

    path("shifts/", views.ShiftListView.as_view(), name="shift_list"),
    path("shifts/create/", views.ShiftCreateView.as_view(), name="shift_create"),
    path("shifts/<uuid:pk>/edit/", views.ShiftUpdateView.as_view(), name="shift_edit"),
]
