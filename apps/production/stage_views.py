from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
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

    def get_queryset(self):
        qs = self.model.objects.select_related("lot", "machine", "operator", "shift").order_by("-created_at")
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        from .models import STATUS_CHOICES

        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = self.page_title
        ctx["status_choices"] = STATUS_CHOICES
        ctx["detail_url_name"] = self.detail_url_name
        ctx["create_url_name"] = self.create_url_name
        ctx["stage"] = self.stage
        return ctx


class StageCreateView(LoginRequiredMixin, CreateView):
    template_name = "production/stage_form.html"
    stage = None
    page_title = ""
    list_url_name = ""
    checklist = []

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.can_operate_stage(self.stage):
            raise PermissionDenied("You are not authorized to create transactions for this stage.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        form.instance.status = "draft" if "save_draft" in self.request.POST else "in_progress"
        try:
            form.instance.full_clean()
        except ValidationError as exc:
            for err in exc.messages:
                form.add_error(None, err)
            return self.form_invalid(form)
        response = super().form_valid(form)
        messages.success(self.request, f"{self.page_title} {self.object.transaction_number} saved.")
        return response

    def get_success_url(self):
        return reverse(self.list_url_name)

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
    """Concrete stage apps subclass this and set `model` + `complete_fn`."""

    model = None
    complete_fn = None
    detail_url_name = ""

    def get_kwargs(self, operation, request):
        return {}

    def post(self, request, pk):
        operation = get_object_or_404(self.model, pk=pk)
        try:
            self.complete_fn(operation, request.user, **self.get_kwargs(operation, request))
            messages.success(request, f"{operation.transaction_number} completed successfully.")
        except (ValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            messages.error(request, detail)
        return redirect(self.detail_url_name, pk=pk)
