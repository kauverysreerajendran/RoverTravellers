from django import forms

from apps.master_data.forms import StyledModelForm
from apps.production.models import ProductionLot

from .models import HeatTreatmentTransaction


class HeatTreatmentInitiateForm(StyledModelForm):
    class Meta:
        model = HeatTreatmentTransaction
        # Surface finish is the material's own property, carried by the lot
        # from Rolling; the model still records it (see the model's save),
        # but the operator is not asked to re-enter it here.
        fields = ["lot", "batch_number", "operation_date", "input_quantity"]
        labels = {"input_quantity": "Received Weight (kg)", "batch_number": "Batch No"}
        widgets = {"operation_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lot"].queryset = ProductionLot.objects.all()
        self.fields["lot"].widget = forms.HiddenInput()
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


class HeatBatchInitiateForm(forms.Form):
    """The furnace load an operator is about to start.

    There is no Surface Finish here on purpose: a load can hold lots of
    different traveller types, and each lot's finish is its own property
    carried from Rolling - one batch-level value would overwrite the truth
    on every lot but one. The transaction fills it from its lot.
    """

    batch_no = forms.CharField(
        max_length=20, label="Batch No",
        widget=forms.TextInput(attrs={
            "class": "form-control", "autocomplete": "off", "list": "heatBatchOptions",
            "placeholder": "e.g. B001",
        }),
    )
    operation_date = forms.DateField(
        label="Date", widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    lots = forms.TypedMultipleChoiceField(
        coerce=str, label="Lots in this batch", widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Tick at least one lot to put in this batch."},
    )

    def __init__(self, *args, incoming_lots=(), **kwargs):
        """`incoming_lots` is what is actually waiting at this process right
        now; the choices are built from it so a hand-posted lot id cannot
        pull in material that is somewhere else."""
        super().__init__(*args, **kwargs)
        self.fields["lots"].choices = [(str(lot.pk), lot.wire_serial or lot.lot_number) for lot in incoming_lots]
