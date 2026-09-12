from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from apps.common.views import DynamicPageSizeMixin

from apps.audit.models import log_action

from . import forms, models


class MasterListView(LoginRequiredMixin, DynamicPageSizeMixin, ListView):
    template_name = "master_data/generic_list.html"

    page_title = ""
    create_url_name = ""
    edit_url_name = ""
    search_fields = []

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q")
        if q and self.search_fields:
            from django.db.models import Q

            filters = Q()
            for f in self.search_fields:
                filters |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(filters)
        return qs.order_by(qs.model._meta.ordering[0] if qs.model._meta.ordering else "pk")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = self.page_title
        ctx["create_url_name"] = self.create_url_name
        ctx["edit_url_name"] = self.edit_url_name
        ctx["search_query"] = self.request.GET.get("q", "")
        ctx["columns"] = self.columns
        return ctx


class MasterFormView:
    template_name = "master_data/generic_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = self.page_title
        return ctx

    def form_valid(self, form):
        is_create = form.instance.pk is None
        if hasattr(form.instance, "created_by") and is_create:
            form.instance.created_by = self.request.user
        if hasattr(form.instance, "updated_by"):
            form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        log_action(
            self.request.user,
            "create" if is_create else "update",
            self.object,
            description=f"{self.object._meta.verbose_name} saved via UI",
        )
        messages.success(self.request, f"{self.page_title} saved successfully.")
        return response


# ---- Material ----
class MaterialListView(MasterListView):
    model = models.MaterialMaster
    page_title = "Materials"
    create_url_name = "master_data:material_create"
    search_fields = ["material_code", "name"]
    columns = ["material_code", "name", "material_type", "unit_of_measure", "reorder_level", "is_active"]
    edit_url_name = "master_data:material_edit"



class MaterialCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.MaterialMaster
    form_class = forms.MaterialMasterForm
    success_url = reverse_lazy("master_data:material_list")
    page_title = "Add Material"


class MaterialUpdateView(LoginRequiredMixin, MasterFormView, UpdateView):
    model = models.MaterialMaster
    form_class = forms.MaterialMasterForm
    success_url = reverse_lazy("master_data:material_list")
    page_title = "Edit Material"


# ---- Product ----
class ProductListView(MasterListView):
    model = models.ProductMaster
    page_title = "Products"
    create_url_name = "master_data:product_create"
    search_fields = ["product_code", "name"]
    columns = ["product_code", "name", "unit_of_measure", "raw_material", "is_active"]
    edit_url_name = "master_data:product_edit"



class ProductCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.ProductMaster
    form_class = forms.ProductMasterForm
    success_url = reverse_lazy("master_data:product_list")
    page_title = "Add Product"


class ProductUpdateView(LoginRequiredMixin, MasterFormView, UpdateView):
    model = models.ProductMaster
    form_class = forms.ProductMasterForm
    success_url = reverse_lazy("master_data:product_list")
    page_title = "Edit Product"


# ---- Vendor ----
class VendorListView(MasterListView):
    model = models.Vendor
    page_title = "Vendors"
    create_url_name = "master_data:vendor_create"
    search_fields = ["code", "name"]
    columns = ["code", "name", "contact_person", "phone", "email", "is_active"]
    edit_url_name = "master_data:vendor_edit"



class VendorCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.Vendor
    form_class = forms.VendorForm
    success_url = reverse_lazy("master_data:vendor_list")
    page_title = "Add Vendor"


class VendorUpdateView(LoginRequiredMixin, MasterFormView, UpdateView):
    model = models.Vendor
    form_class = forms.VendorForm
    success_url = reverse_lazy("master_data:vendor_list")
    page_title = "Edit Vendor"


# ---- Location ----
class LocationListView(MasterListView):
    model = models.Location
    page_title = "Locations"
    create_url_name = "master_data:location_create"
    search_fields = ["code", "name"]
    columns = ["code", "name", "plant", "location_type", "is_active"]
    edit_url_name = "master_data:location_edit"



class LocationCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.Location
    form_class = forms.LocationForm
    success_url = reverse_lazy("master_data:location_list")
    page_title = "Add Location"


class LocationUpdateView(LoginRequiredMixin, MasterFormView, UpdateView):
    model = models.Location
    form_class = forms.LocationForm
    success_url = reverse_lazy("master_data:location_list")
    page_title = "Edit Location"


# ---- Rack / Shelf / Tray ----
class RackListView(MasterListView):
    model = models.Rack
    page_title = "Racks"
    create_url_name = "master_data:rack_create"
    search_fields = ["code"]
    columns = ["code", "location", "is_active"]


class RackCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.Rack
    form_class = forms.RackForm
    success_url = reverse_lazy("master_data:rack_list")
    page_title = "Add Rack"


class ShelfListView(MasterListView):
    model = models.Shelf
    page_title = "Shelves"
    create_url_name = "master_data:shelf_create"
    search_fields = ["code"]
    columns = ["code", "rack", "is_active"]


class ShelfCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.Shelf
    form_class = forms.ShelfForm
    success_url = reverse_lazy("master_data:shelf_list")
    page_title = "Add Shelf"


class TrayListView(MasterListView):
    model = models.Tray
    page_title = "Trays"
    create_url_name = "master_data:tray_create"
    search_fields = ["code"]
    columns = ["code", "shelf", "is_active"]


class TrayCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.Tray
    form_class = forms.TrayForm
    success_url = reverse_lazy("master_data:tray_list")
    page_title = "Add Tray"


# ---- Machine ----
class MachineListView(MasterListView):
    model = models.Machine
    page_title = "Machines"
    create_url_name = "master_data:machine_create"
    search_fields = ["code", "name"]
    columns = ["code", "name", "stage", "plant", "is_operational", "is_active"]
    edit_url_name = "master_data:machine_edit"



class MachineCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.Machine
    form_class = forms.MachineForm
    success_url = reverse_lazy("master_data:machine_list")
    page_title = "Add Machine"


class MachineUpdateView(LoginRequiredMixin, MasterFormView, UpdateView):
    model = models.Machine
    form_class = forms.MachineForm
    success_url = reverse_lazy("master_data:machine_list")
    page_title = "Edit Machine"


# ---- Employee ----
class EmployeeListView(MasterListView):
    model = models.Employee
    page_title = "Employees"
    create_url_name = "master_data:employee_create"
    search_fields = ["employee_code", "first_name", "last_name"]
    columns = ["employee_code", "first_name", "last_name", "department", "designation", "is_active"]
    edit_url_name = "master_data:employee_edit"



class EmployeeCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.Employee
    form_class = forms.EmployeeForm
    success_url = reverse_lazy("master_data:employee_list")
    page_title = "Add Employee"


class EmployeeUpdateView(LoginRequiredMixin, MasterFormView, UpdateView):
    model = models.Employee
    form_class = forms.EmployeeForm
    success_url = reverse_lazy("master_data:employee_list")
    page_title = "Edit Employee"


# ---- Shift ----
class ShiftListView(MasterListView):
    model = models.Shift
    page_title = "Shifts"
    create_url_name = "master_data:shift_create"
    search_fields = ["code", "name"]
    columns = ["code", "name", "start_time", "end_time", "is_active"]
    edit_url_name = "master_data:shift_edit"



class ShiftCreateView(LoginRequiredMixin, MasterFormView, CreateView):
    model = models.Shift
    form_class = forms.ShiftForm
    success_url = reverse_lazy("master_data:shift_list")
    page_title = "Add Shift"


class ShiftUpdateView(LoginRequiredMixin, MasterFormView, UpdateView):
    model = models.Shift
    form_class = forms.ShiftForm
    success_url = reverse_lazy("master_data:shift_list")
    page_title = "Edit Shift"
