from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, View

from .models import OperationQualityCheck


class StageListView(LoginRequiredMixin, ListView):
    paginate_by = 20
    stage = None
    page_title = ""
    template_name = "production/stage_list.html"
    detail_url_name = ""
    create_url_name = ""
    complete_url_name = ""

    def get_queryset(self):
        qs = self.model.objects.select_related("lot", "lot__source_rolling_batch", "machine", "operator", "shift").order_by("-created_at")
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        from .models import STATUS_CHOICES, ProductionLot

        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = self.page_title
        ctx["status_choices"] = STATUS_CHOICES
        ctx["detail_url_name"] = self.detail_url_name
        ctx["create_url_name"] = self.create_url_name
        ctx["complete_url_name"] = self.complete_url_name
        ctx["stage"] = self.stage
        # Main table row for material that has completed the previous
        # process but has not yet had this stage's transaction initiated.
        started_lot_ids = self.model.objects.values_list("lot_id", flat=True)
        ctx["pending_lots"] = (
            ProductionLot.objects.filter(current_stage=self.stage)
            .exclude(pk__in=list(started_lot_ids))
            .select_related("source_rolling_batch")
            .order_by("-created_at")
        )
        return ctx


class StageCreateView(LoginRequiredMixin, CreateView):
    template_name = "production/stage_form.html"
    stage = None
    page_title = ""
    list_url_name = ""
    complete_url_name = ""
    checklist = []

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.can_operate_stage(self.stage):
            raise PermissionDenied("You are not authorized to create transactions for this stage.")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        lot_id = self.request.GET.get("lot")
        if lot_id:
            initial["lot"] = lot_id
        return initial

    def form_valid(self, form):
        from apps.inventory.models import WIPStock

        lot = form.instance.lot
        if not lot.wire_serial:
            form.add_error(
                None, "Wire Serial is missing for this lot - it cannot be initiated without a traceable Wire Serial."
            )
            return self.form_invalid(form)

        # Prevent duplicate initiation: only one open (non-completed,
        # non-cancelled) transaction per lot per stage.
        existing = self.model.objects.filter(lot=lot).exclude(status__in=["completed", "cancelled"]).first()
        if existing:
            messages.info(self.request, f"{lot.wire_serial} already has an open {self.page_title} transaction.")
            return redirect(self.complete_url_name, pk=existing.pk)

        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        form.instance.status = "draft" if "save_draft" in self.request.POST else "in_progress"
        # Received Weight always comes from the previous process's WIP
        # balance, never trusted from the client-submitted form value.
        available = (
            WIPStock.objects.filter(stage=self.stage, lot=lot, status="available")
            .values_list("quantity", flat=True)
            .first()
        )
        if available is not None:
            form.instance.input_quantity = available
        try:
            form.instance.full_clean()
        except ValidationError as exc:
            for err in exc.messages:
                form.add_error(None, err)
            return self.form_invalid(form)
        response = super().form_valid(form)
        messages.success(self.request, f"{self.page_title} {self.object.transaction_number} initiated.")
        return response

    def get_success_url(self):
        return reverse(self.complete_url_name, kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"New {self.page_title}"
        ctx["checklist"] = self.checklist
        ctx["checklist_title"] = f"{self.page_title} Process"
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
    (e.g. Finished Weight), and finalizes the transaction on submit.
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
            "page_subtitle": "Complete table - review auto-populated data and record completion values",
            "detail_url_name": self.detail_url_name,
            "list_url_name": self.list_url_name,
            "breadcrumbs": [
                {"label": self.page_title, "url": reverse(self.list_url_name)},
                {"label": f"Complete {self.operation.transaction_number}"},
            ],
        }
