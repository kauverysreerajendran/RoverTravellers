from django import forms

from apps.master_data.forms import StyledModelForm

from .models import HeatTreatmentTransaction


class HeatTreatmentTransactionForm(StyledModelForm):
    class Meta:
        model = HeatTreatmentTransaction
        fields = [
            "lot", "batch_number", "heat_treatment_type", "temperature_celsius", "holding_time_minutes",
            "machine", "operator", "shift", "start_time", "end_time",
            "input_quantity", "output_quantity", "rejection_quantity", "rejection_reason", "remarks",
        ]
        widgets = {
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
