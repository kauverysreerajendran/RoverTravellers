from apps.production.services import complete_stage
from apps.production.stage_views import StageCompleteView, StageCreateView, StageDetailView, StageListView

from .forms import HeatTreatmentTransactionForm
from .models import HeatTreatmentTransaction


class HeatTreatmentListView(StageListView):
    model = HeatTreatmentTransaction
    stage = "heat_treatment"
    page_title = "Heat Treatment"
    detail_url_name = "heat_treatment:detail"
    create_url_name = "heat_treatment:create"


class HeatTreatmentCreateView(StageCreateView):
    model = HeatTreatmentTransaction
    form_class = HeatTreatmentTransactionForm
    stage = "heat_treatment"
    page_title = "Heat Treatment Transaction"
    list_url_name = "heat_treatment:list"
    checklist = [
        "Select the furnace, batch number and heat treatment type",
        "Set the target temperature and holding time",
        "Enter input weight and the resulting output weight",
        "Completing the transaction stages the output for Finishing",
    ]


class HeatTreatmentDetailView(StageDetailView):
    model = HeatTreatmentTransaction
    stage = "heat_treatment"
    page_title = "Heat Treatment"
    complete_url_name = "heat_treatment:complete"


class HeatTreatmentCompleteView(StageCompleteView):
    model = HeatTreatmentTransaction
    complete_fn = staticmethod(complete_stage)
    detail_url_name = "heat_treatment:detail"

    def get_kwargs(self, operation, request):
        return {"current_stage": "heat_treatment"}
