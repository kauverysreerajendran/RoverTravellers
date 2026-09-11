from django import forms

from apps.master_data.forms import StyledModelForm
from apps.masters.models import Machine
from apps.production.models import ProductionLot

from .models import FormingTransaction


class FormingInitiateForm(StyledModelForm):
    """Initiate screen, always entered from an incoming row: the lot is
    fixed by the `?lot=` parameter and Received Weight is auto-filled
    server-side from the predecessor record, never entered."""

    class Meta:
        model = FormingTransaction
        fields = ["lot", "machine", "operation_date", "input_quantity"]
        labels = {"input_quantity": "Received Weight (kg)"}
        widgets = {"operation_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = ProductionLot.objects.all()
        self.fields["lot"].widget = forms.HiddenInput()
        self.fields["machine"].queryset = Machine.active.all()
        self.fields["input_quantity"].required = False
        self.fields["input_quantity"].widget.attrs["readonly"] = True
        self.fields["input_quantity"].help_text = "Auto-filled from the completed Rolling batch."
        self.fields["input_quantity"].disabled = True


# Backwards-compatible alias for the view/import name used elsewhere.
FormingTransactionForm = FormingInitiateForm


class FormingCompleteForm(StyledModelForm):
    """Complete table: Output Weight, Traveller Length, Traveller Weight -
    entered when the user completes the Forming transaction. Wastage is
    calculated and saved server-side on submit."""

    class Meta:
        model = FormingTransaction
        fields = ["output_quantity", "traveller_length_mm", "traveller_weight_kg", "remarks"]
        labels = {
            "output_quantity": "Output Weight (kg)",
            "traveller_length_mm": "Traveller Length (mm)",
            "traveller_weight_kg": "Traveller Weight (kg)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("output_quantity", "traveller_length_mm", "traveller_weight_kg"):
            self.fields[name].required = True
