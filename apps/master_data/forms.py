from django import forms

from . import models

BASE_WIDGET_CLASS = "form-control"
SELECT_WIDGET_CLASS = "form-select"


def _style(fields):
    for name, field in fields.items():
        if isinstance(field.widget, (forms.CheckboxInput,)):
            field.widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
            field.widget.attrs.setdefault("class", SELECT_WIDGET_CLASS)
        else:
            field.widget.attrs.setdefault("class", BASE_WIDGET_CLASS)


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self.fields)


class MaterialMasterForm(StyledModelForm):
    class Meta:
        model = models.MaterialMaster
        fields = [
            "material_code", "name", "material_type", "unit_of_measure", "grade",
            "standard_diameter_mm", "default_vendor", "reorder_level", "description", "is_active",
        ]


class ProductMasterForm(StyledModelForm):
    class Meta:
        model = models.ProductMaster
        fields = ["product_code", "name", "unit_of_measure", "raw_material", "description", "is_active"]


class VendorForm(StyledModelForm):
    class Meta:
        model = models.Vendor
        fields = ["code", "name", "contact_person", "email", "phone", "address", "is_active"]


class PlantForm(StyledModelForm):
    class Meta:
        model = models.Plant
        fields = ["code", "name", "address", "is_active"]


class LocationForm(StyledModelForm):
    class Meta:
        model = models.Location
        fields = ["plant", "code", "name", "location_type", "is_active"]


class RackForm(StyledModelForm):
    class Meta:
        model = models.Rack
        fields = ["location", "code", "is_active"]


class ShelfForm(StyledModelForm):
    class Meta:
        model = models.Shelf
        fields = ["rack", "code", "is_active"]


class TrayForm(StyledModelForm):
    class Meta:
        model = models.Tray
        fields = ["shelf", "code", "is_active"]


class MachineForm(StyledModelForm):
    class Meta:
        model = models.Machine
        fields = ["code", "name", "stage", "plant", "is_operational", "is_active"]


class EmployeeForm(StyledModelForm):
    class Meta:
        model = models.Employee
        fields = ["employee_code", "first_name", "last_name", "department", "designation", "phone", "email", "is_active"]


class ShiftForm(StyledModelForm):
    class Meta:
        model = models.Shift
        fields = ["code", "name", "start_time", "end_time", "is_active"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }
