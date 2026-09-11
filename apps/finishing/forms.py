from django import forms

from apps.master_data.forms import StyledModelForm
from apps.masters.models import Machine
from apps.masters.models import SurfaceFinish
from apps.production.models import ProductionLot

from .models import FinishingTransaction


class FinishingInitiateForm(StyledModelForm):
    class Meta:
        model = FinishingTransaction
        fields = ["lot", "batch_no", "operation_date", "surface_finish", "machine", "input_quantity"]
        labels = {"input_quantity": "Received Weight (kg)"}
        widgets = {"operation_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = ProductionLot.objects.all()
        self.fields["lot"].widget = forms.HiddenInput()
        self.fields["machine"].queryset = Machine.active.all()
        self.fields["surface_finish"].queryset = SurfaceFinish.objects.filter(is_active=True)
        self.fields["input_quantity"].required = False
        self.fields["input_quantity"].widget.attrs["readonly"] = True
        self.fields["input_quantity"].help_text = "Auto-filled from the completed Heat Treatment transaction."
        self.fields["input_quantity"].disabled = True


# Backwards-compatible alias.
FinishingTransactionForm = FinishingInitiateForm


class FinishingCompleteForm(StyledModelForm):
    class Meta:
        model = FinishingTransaction
        fields = ["output_quantity", "traveller_weight_kg", "colour", "remarks"]
        labels = {
            "output_quantity": "Output Weight (kg)",
            "traveller_weight_kg": "Traveller Weight (kg)",
            "colour": "Colour",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("output_quantity", "traveller_weight_kg", "colour"):
            self.fields[name].required = True
