from django import forms

from apps.master_data.forms import StyledModelForm
from apps.master_data.models import Machine
from apps.production.models import ProductionLot

from .models import FormingTransaction


class FormingInitiateForm(StyledModelForm):
    """Initiate screen: pick the completed Rolling lot, a Forming Machine
    and a date. Received Weight is auto-filled server-side, never entered."""

    class Meta:
        model = FormingTransaction
        fields = ["lot", "machine", "operation_date", "input_quantity"]
        labels = {"input_quantity": "Received Weight (kg)"}
        widgets = {"operation_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = ProductionLot.objects.filter(current_stage="forming").select_related(
            "source_rolling_batch"
        )
        self.fields["lot"].label_from_instance = lambda lot: (
            f"{lot.wire_serial or lot.lot_number} - Traveller {lot.traveller_no} ({lot.quantity} kg)"
        )
        self.fields["machine"].queryset = Machine.active.filter(stage="forming")
        self.fields["input_quantity"].required = False
        self.fields["input_quantity"].widget.attrs["readonly"] = True
        self.fields["input_quantity"].help_text = "Auto-filled from the completed Rolling batch."


# Backwards-compatible alias for the view/import name used elsewhere.
FormingTransactionForm = FormingInitiateForm


class FormingCompleteForm(StyledModelForm):
    """Complete table: Finished Weight, Traveller Length, Traveller Weight -
    entered when the user completes the Forming transaction. Wastage is
    calculated and saved server-side on submit."""

    class Meta:
        model = FormingTransaction
        fields = [
            "output_quantity", "traveller_length_mm", "traveller_weight_kg",
            "rejection_quantity", "rejection_reason", "remarks",
        ]
        labels = {"output_quantity": "Finished Weight (kg)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("output_quantity", "traveller_length_mm", "traveller_weight_kg"):
            self.fields[name].required = True
