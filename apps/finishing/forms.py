from django import forms

from apps.master_data.forms import StyledModelForm

from .models import FinishingTransaction


class FinishingTransactionForm(StyledModelForm):
    class Meta:
        model = FinishingTransaction
        fields = [
            "lot", "finishing_operation", "surface_finish_spec", "machine", "operator", "shift",
            "start_time", "end_time", "input_quantity", "output_quantity", "rejection_quantity",
            "rejection_reason", "remarks",
        ]
        widgets = {
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
