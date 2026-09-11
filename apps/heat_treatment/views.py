from apps.production.services import complete_stage
from apps.production.stage_views import StageCompleteView, StageCreateView, StageDetailView

from .forms import HeatTreatmentCompleteForm, HeatTreatmentInitiateForm
from .models import HeatTreatmentTransaction


class HeatTreatmentCreateView(StageCreateView):
    model = HeatTreatmentTransaction
    form_class = HeatTreatmentInitiateForm
    stage = "heat_treatment"
    page_title = "Heat Treatment Transaction"
    list_url_name = "heat_treatment:list"
    complete_url_name = "heat_treatment:complete"
    checklist = [
        "Select the completed Forming lot and enter the Batch No",
        "Pick the date and Surface Finish - Received Weight is auto-filled",
        "Initiating creates the transaction; enter the finished weight on the Complete screen",
        "Completing the transaction stages the output for Finishing",
    ]


class HeatTreatmentDetailView(StageDetailView):
    model = HeatTreatmentTransaction
    stage = "heat_treatment"
    page_title = "Heat Treatment"
    complete_url_name = "heat_treatment:complete"


class HeatTreatmentCompleteView(StageCompleteView):
    model = HeatTreatmentTransaction
    complete_form_class = HeatTreatmentCompleteForm
    complete_fn = staticmethod(complete_stage)
    stage = "heat_treatment"
    page_title = "Heat Treatment"
    detail_url_name = "heat_treatment:detail"
    list_url_name = "heat_treatment:list"
