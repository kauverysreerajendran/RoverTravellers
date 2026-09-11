from django import forms

from apps.master_data.forms import StyledModelForm

from .models import RollingTransaction


class RollingTransactionForm(StyledModelForm):
    class Meta:
        model = RollingTransaction
        fields = [
            "lot", "raw_material", "machine", "operator", "shift", "start_time", "end_time",
            "input_quantity", "output_quantity", "rejection_quantity", "rejection_reason", "remarks",
        ]
        widgets = {
            "start_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
