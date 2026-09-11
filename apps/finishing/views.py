from apps.production.services import complete_stage
from apps.production.stage_views import StageCompleteView, StageCreateView, StageDetailView, StageListView

from .forms import FinishingTransactionForm
from .models import FinishingTransaction


class FinishingListView(StageListView):
    model = FinishingTransaction
    stage = "finishing"
    page_title = "Finishing"
    detail_url_name = "finishing:detail"
    create_url_name = "finishing:create"


class FinishingCreateView(StageCreateView):
    model = FinishingTransaction
    form_class = FinishingTransactionForm
    stage = "finishing"
    page_title = "Finishing Transaction"
    list_url_name = "finishing:list"
    checklist = [
        "Select the finishing operation, machine and surface finish spec",
        "Enter input weight and the resulting output weight",
        "Record any rejection quantity and reason code",
        "Completing the transaction makes the lot ready for Finished Goods receiving",
    ]


class FinishingDetailView(StageDetailView):
    model = FinishingTransaction
    stage = "finishing"
    page_title = "Finishing"
    complete_url_name = "finishing:complete"


class FinishingCompleteView(StageCompleteView):
    model = FinishingTransaction
    complete_fn = staticmethod(complete_stage)
    detail_url_name = "finishing:detail"

    def get_kwargs(self, operation, request):
        return {"current_stage": "finishing"}
