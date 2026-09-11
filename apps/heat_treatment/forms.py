from django import forms

from apps.master_data.forms import StyledModelForm
from apps.master_data.models import Machine
from apps.masters.models import SurfaceFinish
from apps.production.models import ProductionLot

from .models import HeatTreatmentTransaction


class HeatTreatmentInitiateForm(StyledModelForm):
    class Meta:
        model = HeatTreatmentTransaction
        fields = ["lot", "tt", "t_no", "batch_number", "operation_date", "surface_finish", "machine", "input_quantity"]
        labels = {"input_quantity": "Finished Weight (kg)", "batch_number": "Batch No"}
        widgets = {"operation_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = ProductionLot.objects.filter(current_stage="heat_treatment").select_related(
            "source_rolling_batch"
        )
        self.fields["lot"].label_from_instance = lambda lot: (
            f"{lot.wire_serial or lot.lot_number} - Traveller {lot.traveller_no} ({lot.quantity} kg)"
        )
        self.fields["machine"].queryset = Machine.active.filter(stage="heat_treatment")
        self.fields["surface_finish"].queryset = SurfaceFinish.objects.filter(is_active=True)
        self.fields["input_quantity"].required = False
        self.fields["input_quantity"].widget.attrs["readonly"] = True
        self.fields["input_quantity"].help_text = "Auto-filled from the completed Forming transaction."


# Backwards-compatible alias.
HeatTreatmentTransactionForm = HeatTreatmentInitiateForm


class HeatTreatmentCompleteForm(StyledModelForm):
    class Meta:
        model = HeatTreatmentTransaction
        fields = [
            "output_quantity", "heat_treatment_type", "temperature_celsius", "holding_time_minutes",
            "rejection_quantity", "rejection_reason", "remarks",
        ]
        labels = {
            "output_quantity": "Output Weight (kg)",
            "heat_treatment_type": "Heat Treatment Type",
            "temperature_celsius": "Temperature (C)",
            "holding_time_minutes": "Holding Time (min)",
            "rejection_quantity": "Rejection (kg)",
            "rejection_reason": "Rejection Reason",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["output_quantity"].required = True
