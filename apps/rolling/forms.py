from django import forms

from apps.masters.models import RackSlot, SurfaceFinish, TravellerNo, TravellerType


class RollingInitiateForm(forms.Form):
    traveller_type_id = forms.ModelChoiceField(
        queryset=TravellerType.objects.filter(is_active=True), widget=forms.HiddenInput
    )
    traveller_no = forms.ModelChoiceField(
        queryset=TravellerNo.objects.filter(is_active=True), empty_label="Select traveller no",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    finish = forms.ModelChoiceField(
        queryset=SurfaceFinish.objects.filter(is_active=True), empty_label="Select finish",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    required_box = forms.IntegerField(
        min_value=1, widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "Enter box count"})
    )
    wire_weight_issued_kg = forms.DecimalField(
        min_value=0.01, max_digits=8, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "Enter weight"}),
    )
    coils_json = forms.CharField(widget=forms.HiddenInput)


class RollingCompleteForm(forms.Form):
    rolled_thickness_mm = forms.DecimalField(max_digits=5, decimal_places=2, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}))
    rolled_width_mm = forms.DecimalField(max_digits=5, decimal_places=2, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}))
    finished_weight_kg = forms.DecimalField(max_digits=8, decimal_places=2, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}))
    # Where the rolled wire is placed. Optional: when the operator does not
    # click a slot the completion falls back to the next free one, and the
    # queryset is narrowed to this zone so a hand-posted id cannot put the
    # material on some other zone's rack.
    rack_slot = forms.ModelChoiceField(queryset=RackSlot.objects.none(), required=False, widget=forms.HiddenInput)

    def __init__(self, *args, zone=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rack_slot"].queryset = (
            RackSlot.objects.filter(zone=zone) if zone is not None else RackSlot.objects.none()
        )
