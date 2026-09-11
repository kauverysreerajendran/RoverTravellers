from django import forms

from apps.master_data.forms import StyledModelForm
from apps.masters.models import SurfaceFinish
from apps.production.models import ProductionLot

from .models import HeatTreatmentTransaction


class HeatTreatmentInitiateForm(StyledModelForm):
    class Meta:
        model = HeatTreatmentTransaction
        fields = ["lot", "batch_number", "operation_date", "surface_finish", "input_quantity"]
        labels = {"input_quantity": "Received Weight (kg)", "batch_number": "Batch No"}
        widgets = {"operation_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = ProductionLot.objects.all()
        self.fields["lot"].widget = forms.HiddenInput()
        self.fields["surface_finish"].queryset = SurfaceFinish.objects.filter(is_active=True)
        self.fields["input_quantity"].required = False
        self.fields["input_quantity"].widget.attrs["readonly"] = True
        self.fields["input_quantity"].help_text = "Auto-filled from the completed Forming transaction."
        self.fields["input_quantity"].disabled = True


# Backwards-compatible alias.
HeatTreatmentTransactionForm = HeatTreatmentInitiateForm


class HeatTreatmentCompleteForm(StyledModelForm):
    class Meta:
        model = HeatTreatmentTransaction
        fields = ["output_quantity", "remarks"]
        labels = {"output_quantity": "Output Weight (kg)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["output_quantity"].required = True
