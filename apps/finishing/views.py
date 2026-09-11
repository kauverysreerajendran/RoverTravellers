from apps.production.services import complete_stage
from apps.production.stage_views import StageCompleteView, StageCreateView, StageDetailView

from .forms import FinishingCompleteForm, FinishingInitiateForm
from .models import FinishingTransaction


class FinishingCreateView(StageCreateView):
    model = FinishingTransaction
    form_class = FinishingInitiateForm
    stage = "finishing"
    page_title = "Finishing Transaction"
    list_url_name = "finishing:list"
    complete_url_name = "finishing:complete"
    checklist = [
        "Select the completed Heat Treatment lot and enter the Batch No",
        "Pick the date and Surface Finish - Received Weight is auto-filled",
        "Initiating creates the transaction; enter Traveller Weight and Colour on the Complete screen",
        "Completing the transaction makes the lot ready for Finished Goods receiving",
    ]


class FinishingDetailView(StageDetailView):
    model = FinishingTransaction
    stage = "finishing"
    page_title = "Finishing"
    complete_url_name = "finishing:complete"


class FinishingCompleteView(StageCompleteView):
    model = FinishingTransaction
    complete_form_class = FinishingCompleteForm
    complete_fn = staticmethod(complete_stage)
    stage = "finishing"
    page_title = "Finishing"
    detail_url_name = "finishing:detail"
    list_url_name = "finishing:list"
