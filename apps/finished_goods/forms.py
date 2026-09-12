from django import forms

from apps.master_data.forms import StyledModelForm
from apps.production.models import ProductionLot


class FinishedGoodsReceiveForm(forms.Form):
    # Fixed by the incoming row the operator came from; the view validates
    # it against the set of lots actually waiting here.
    lot = forms.ModelChoiceField(queryset=ProductionLot.objects.all(), widget=forms.HiddenInput)
    product = forms.ModelChoiceField(queryset=None)
    accepted_quantity = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0)
    rejected_quantity = forms.DecimalField(max_digits=14, decimal_places=3, min_value=0, initial=0)
    # Stock is located by its slot on the Finished Goods rack zone; the old
    # location / rack / shelf / tray fields are gone from this form. The
    # queryset is narrowed to the zone, so a hand-posted id cannot place
    # the stock on another zone's rack.
    rack_slot = forms.ModelChoiceField(queryset=None, required=False, widget=forms.HiddenInput)
    remarks = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args, zone=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.master_data.models import ProductMaster
        from apps.masters.models import RackSlot

        self.fields["product"].queryset = ProductMaster.active.all()
        self.fields["rack_slot"].queryset = (
            RackSlot.objects.filter(zone=zone) if zone is not None else RackSlot.objects.none()
        )
        for name, field in self.fields.items():
            css = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else (
                "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            )
            field.widget.attrs.setdefault("class", css)
