from apps.production.services import complete_stage
from apps.production.stage_views import StageCompleteView, StageCreateView, StageDetailView

from .forms import FormingCompleteForm, FormingInitiateForm
from .models import FormingTransaction


class FormingCreateView(StageCreateView):
    model = FormingTransaction
    form_class = FormingInitiateForm
    stage = "forming"
    page_title = "Forming Transaction"
    list_url_name = "forming:list"
    complete_url_name = "forming:complete"
    checklist = [
        "Select the completed Rolling lot and a Forming Machine",
        "Pick the date - Wire Serial, Traveller No and Finished Weight are auto-filled",
        "Initiating creates the transaction; enter Output Weight etc. on the Complete screen",
        "Completing the transaction stages the output for Heat Treatment",
    ]


class FormingDetailView(StageDetailView):
    model = FormingTransaction
    stage = "forming"
    page_title = "Forming"
    complete_url_name = "forming:complete"


class FormingCompleteView(StageCompleteView):
    model = FormingTransaction
    complete_form_class = FormingCompleteForm
    complete_fn = staticmethod(complete_stage)
    stage = "forming"
    page_title = "Forming"
    detail_url_name = "forming:detail"
    list_url_name = "forming:list"

    def get_kwargs(self, operation, request):
        return {"current_stage": "forming"}
