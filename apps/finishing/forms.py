from django import forms

from apps.master_data.forms import StyledModelForm
from apps.master_data.models import Machine
from apps.masters.models import SurfaceFinish
from apps.production.models import ProductionLot

from .models import FinishingTransaction


class FinishingInitiateForm(StyledModelForm):
    class Meta:
        model = FinishingTransaction
        fields = ["lot", "tt", "t_no", "batch_no", "operation_date", "surface_finish", "machine", "input_quantity"]
        labels = {"input_quantity": "Received Weight (kg)"}
        widgets = {"operation_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = ProductionLot.objects.filter(current_stage="finishing").select_related(
            "source_rolling_batch"
        )
        self.fields["lot"].label_from_instance = lambda lot: (
            f"{lot.wire_serial or lot.lot_number} - Traveller {lot.traveller_no} ({lot.quantity} kg)"
        )
        self.fields["machine"].queryset = Machine.active.filter(stage="finishing")
        self.fields["surface_finish"].queryset = SurfaceFinish.objects.filter(is_active=True)
        self.fields["input_quantity"].required = False
        self.fields["input_quantity"].widget.attrs["readonly"] = True
        self.fields["input_quantity"].help_text = "Auto-filled from the completed Heat Treatment transaction."


# Backwards-compatible alias.
FinishingTransactionForm = FinishingInitiateForm


class FinishingCompleteForm(StyledModelForm):
    class Meta:
        model = FinishingTransaction
        fields = ["output_quantity", "traveller_weight_kg", "colour", "rejection_quantity", "rejection_reason", "remarks"]
        labels = {"output_quantity": "Finished Weight (kg)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("output_quantity", "traveller_weight_kg", "colour"):
            self.fields[name].required = True
