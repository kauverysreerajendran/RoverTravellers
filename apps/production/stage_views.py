from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, DetailView, View

from .models import OperationQualityCheck, ProductionLot
from .process_registry import get_process
from .services import incoming_record_for, initiate_stage


class StageCreateView(LoginRequiredMixin, CreateView):
    """Initiate screen. It is always entered from an incoming row on the
    Main Table (`?lot=`), so it reads the material's identity and its
    Received Weight from the predecessor record rather than offering a
    free list of lots."""

    template_name = "production/stage_form.html"
    stage = None
    page_title = ""
    list_url_name = ""
    complete_url_name = ""

    @property
    def process(self):
        return get_process(self.stage)

    def main_table_url(self):
        return reverse("process:main", kwargs={"process": self.process.slug})

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.can_operate_stage(self.stage):
            raise PermissionDenied("You are not authorized to create transactions for this stage.")

        lot_id = request.GET.get("lot") or request.POST.get("lot")
        if not lot_id:
            messages.error(request, f"Start a {self.page_title} from an incoming row on the Main Table.")
            return redirect(self.main_table_url())

        self.lot = get_object_or_404(ProductionLot, pk=lot_id)
        self.incoming = incoming_record_for(self.process, self.lot)
        if self.incoming is None:
            messages.error(
                request,
                f"{self.lot.wire_serial or self.lot.lot_number} is not waiting at {self.process.label}.",
            )
            return redirect(self.main_table_url())
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        initial["lot"] = self.lot.pk
        # Read-only on the form; the saved value comes from the predecessor
        # record server-side, never from what the client posted.
        initial["input_quantity"] = self.incoming.output_weight
        return initial

    def form_valid(self, form):
        if form.cleaned_data.get("lot") != self.lot:
            form.add_error(None, "This transaction does not belong to the incoming lot.")
            return self.form_invalid(form)

        existing = (
            self.model.objects.filter(lot=self.lot)
            .exclude(status__in=["completed", "cancelled", "rejected"])
            .first()
        )
        if existing:
            messages.info(self.request, f"{self.lot.wire_serial} already has an open {self.page_title} transaction.")
            return redirect(self.complete_url_name, pk=existing.pk)

        fields = {
            name: value for name, value in form.cleaned_data.items()
            if name not in ("lot", "input_quantity")
        }
        try:
            self.object = initiate_stage(
                self.process, self.lot, self.request.user,
                draft="save_draft" in self.request.POST, **fields,
            )
        except ValidationError as exc:
            for err in exc.messages:
                form.add_error(None, err)
            return self.form_invalid(form)
        messages.success(self.request, f"{self.page_title} {self.object.transaction_number} initiated.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse(self.complete_url_name, kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"New {self.page_title}"
        ctx["incoming"] = self.incoming
        ctx["received_weight"] = self.incoming.output_weight
        return ctx


class StageDetailView(LoginRequiredMixin, DetailView):
    template_name = "production/stage_detail.html"
    stage = None
    page_title = ""
    complete_url_name = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"{self.page_title} {self.object.transaction_number}"
        ctx["quality_checks"] = OperationQualityCheck.objects.filter(
            content_type=ContentType.objects.get_for_model(self.object.__class__), object_id=self.object.pk
        )
        ctx["complete_url_name"] = self.complete_url_name
        ctx["can_complete"] = self.request.user.can_approve()
        return ctx


class StageCompleteView(LoginRequiredMixin, View):
    """The stage's Complete table: shows the previous-process fields
    auto-populated on the transaction plus the completion-only inputs
    (e.g. Output Weight), and finalizes the transaction on submit.
    Concrete stage apps subclass this and set `model`, `complete_form_class`
    and `complete_fn`."""

    model = None
    complete_form_class = None
    complete_fn = None
    template_name = "production/stage_complete.html"
    page_title = ""
    stage = ""
    detail_url_name = ""
    list_url_name = ""

    def get_kwargs(self, operation, request):
        return {}

    def get_object(self, pk):
        return get_object_or_404(self.model, pk=pk)

    def dispatch(self, request, *args, **kwargs):
        self.operation = self.get_object(kwargs["pk"])
        if self.operation.status == "completed":
            messages.info(request, f"{self.operation.transaction_number} is already completed.")
            return redirect(self.detail_url_name, pk=self.operation.pk)
        if request.user.is_authenticated and not request.user.can_approve():
            raise PermissionDenied("You are not authorized to complete transactions.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        form = self.complete_form_class(instance=self.operation)
        return render(request, self.template_name, self._context(form))

    def post(self, request, pk):
        form = self.complete_form_class(request.POST, instance=self.operation)
        if form.is_valid():
            form.save(commit=False)
            try:
                self.complete_fn(self.operation, request.user, **self.get_kwargs(self.operation, request))
                messages.success(request, f"{self.operation.transaction_number} completed successfully.")
                return redirect(self.detail_url_name, pk=pk)
            except (ValidationError, PermissionDenied) as exc:
                detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                messages.error(request, detail)
        return render(request, self.template_name, self._context(form))

    def _context(self, form):
        return {
            "object": self.operation,
            "form": form,
            "stage": self.stage,
            "page_title": f"Complete {self.page_title} {self.operation.transaction_number}",
            "detail_url_name": self.detail_url_name,
            "list_url_name": self.list_url_name,
            "breadcrumbs": [
                {"label": self.page_title, "url": reverse(self.list_url_name)},
                {"label": f"Complete {self.operation.transaction_number}"},
            ],
        }
