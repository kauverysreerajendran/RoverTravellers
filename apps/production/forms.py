from django import forms

from apps.master_data.forms import StyledModelForm

from . import models


class ProductionOrderForm(StyledModelForm):
    class Meta:
        model = models.ProductionOrder
        fields = ["product", "planned_quantity", "uom", "due_date", "remarks"]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}


class ProductionLotForm(StyledModelForm):
    class Meta:
        model = models.ProductionLot
        fields = ["production_order", "quantity", "remarks"]
