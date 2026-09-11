from apps.production.services import complete_rolling
from apps.production.stage_views import StageCompleteView, StageCreateView, StageDetailView, StageListView

from .forms import RollingTransactionForm
from .models import RollingTransaction


class RollingListView(StageListView):
    model = RollingTransaction
    stage = "rolling"
    page_title = "Rolling"
    detail_url_name = "rolling:detail"
    create_url_name = "rolling:create"


class RollingCreateView(StageCreateView):
    model = RollingTransaction
    form_class = RollingTransactionForm
    stage = "rolling"
    page_title = "Rolling Transaction"
    list_url_name = "rolling:list"
    checklist = [
        "Select the raw material lot, machine and shift for this run",
        "Enter input weight and the resulting output weight",
        "Record any rejection quantity and reason code",
        "Completing the transaction deducts raw material stock and stages the output for Forming",
    ]


class RollingDetailView(StageDetailView):
    model = RollingTransaction
    stage = "rolling"
    page_title = "Rolling"
    complete_url_name = "rolling:complete"


class RollingCompleteView(StageCompleteView):
    model = RollingTransaction
    complete_fn = staticmethod(complete_rolling)
    detail_url_name = "rolling:detail"

    def get_kwargs(self, operation, request):
        return {"material": operation.raw_material}
