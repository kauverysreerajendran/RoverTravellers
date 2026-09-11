from django import forms

from apps.master_data.forms import StyledModelForm
from apps.production.models import ProductionLot


class FinishedGoodsReceiveForm(forms.Form):
    lot = forms.ModelChoiceField(queryset=ProductionLot.objects.filter(current_stage="finished_goods"))
    product = forms.ModelChoiceField(queryset=None)
    accepted_quantity = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0)
    rejected_quantity = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0, initial=0)
    location = forms.ModelChoiceField(queryset=None)
    rack = forms.ModelChoiceField(queryset=None, required=False)
    shelf = forms.ModelChoiceField(queryset=None, required=False)
    tray = forms.ModelChoiceField(queryset=None, required=False)
    remarks = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.master_data.models import Location, ProductMaster, Rack, Shelf, Tray

        self.fields["product"].queryset = ProductMaster.active.all()
        self.fields["location"].queryset = Location.active.filter(location_type="fg")
        self.fields["rack"].queryset = Rack.active.all()
        self.fields["shelf"].queryset = Shelf.active.all()
        self.fields["tray"].queryset = Tray.active.all()
        for name, field in self.fields.items():
            css = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )
            field.widget.attrs.setdefault("class", css)
