from apps.production.services import complete_stage
from apps.production.stage_views import StageCompleteView, StageCreateView, StageDetailView, StageListView

from .forms import FormingTransactionForm
from .models import FormingTransaction


class FormingListView(StageListView):
    model = FormingTransaction
    stage = "forming"
    page_title = "Forming"
    detail_url_name = "forming:detail"
    create_url_name = "forming:create"


class FormingCreateView(StageCreateView):
    model = FormingTransaction
    form_class = FormingTransactionForm
    stage = "forming"
    page_title = "Forming Transaction"
    list_url_name = "forming:list"
    checklist = [
        "Select the forming operation, machine and shift",
        "Enter input weight and the resulting output weight",
        "Record any rejection quantity and reason code",
        "Completing the transaction stages the output for Heat Treatment",
    ]


class FormingDetailView(StageDetailView):
    model = FormingTransaction
    stage = "forming"
    page_title = "Forming"
    complete_url_name = "forming:complete"


class FormingCompleteView(StageCompleteView):
    model = FormingTransaction
    complete_fn = staticmethod(complete_stage)
    detail_url_name = "forming:detail"

    def get_kwargs(self, operation, request):
        return {"current_stage": "forming"}
