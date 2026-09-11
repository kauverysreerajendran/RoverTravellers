from decimal import Decimal

from django import forms

from .models import RackMaster


class CoilReceiveForm(forms.Form):
    weight_kg = forms.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "Enter weight"}),
    )
    rack = forms.ModelChoiceField(
        queryset=RackMaster.objects.filter(is_active=True), required=False, empty_label="Select rack",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    supplier = forms.CharField(
        required=False, max_length=100, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Supplier"})
    )
    received_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"})
    )
