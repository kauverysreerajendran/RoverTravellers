import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView

from apps.masters import services as masters_services
from apps.masters.models import TravellerType

from . import services
from .forms import RollingCompleteForm, RollingInitiateForm
from .models import RollingBatch

PAGE_ICON = "bi-disc"


class RollingListView(LoginRequiredMixin, ListView):
    model = RollingBatch
    template_name = "rolling/rolling_list.html"
    context_object_name = "batches"
    PER_PAGE_OPTIONS = (10, 25, 50, 100)

    def get_paginate_by(self, queryset):
        try:
            per_page = int(self.request.GET.get("per_page", 10))
        except (TypeError, ValueError):
            per_page = 10
        return per_page if per_page in self.PER_PAGE_OPTIONS else 10

    def get_queryset(self):
        qs = (
            RollingBatch.objects.select_related("traveller_type", "traveller_no", "finish")
            .prefetch_related("coils_used__coil")
            .order_by("-created_at")
        )
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(wire_serial__icontains=q)
                | Q(traveller_type__name__icontains=q)
                | Q(traveller_no__code__icontains=q)
                | Q(finish__finish_name__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx.update({
            "page_title": "Rolling",
            "page_subtitle": "Manage and track all rolling batches",
            "page_icon": PAGE_ICON,
            "status_choices": RollingBatch._meta.get_field("status").choices,
            "search_query": self.request.GET.get("q", "").strip(),
            "per_page": self.get_paginate_by(None),
            "per_page_options": self.PER_PAGE_OPTIONS,
            "qs": params.urlencode(),
        })
        if ctx.get("is_paginated"):
            ctx["page_range"] = list(
                ctx["paginator"].get_elided_page_range(ctx["page_obj"].number, on_each_side=1, on_ends=1)
            )
        return ctx


class RollingCreateView(LoginRequiredMixin, View):
    template_name = "rolling/rolling_form.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.can_operate_stage("rolling"):
            raise PermissionDenied("You are not authorized to create rolling batches.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return render(request, self.template_name, self._context(RollingInitiateForm()))

    def post(self, request):
        form = RollingInitiateForm(request.POST)
        if form.is_valid():
            try:
                coil_weights = self._parse_coils(form.cleaned_data["coils_json"])
                batch = services.initiate_rolling_batch(
                    traveller_type=form.cleaned_data["traveller_type_id"],
                    traveller_no=form.cleaned_data["traveller_no"],
                    finish=form.cleaned_data["finish"],
                    required_box=form.cleaned_data["required_box"],
                    wire_weight_issued_kg=form.cleaned_data["wire_weight_issued_kg"],
                    coil_weights=coil_weights,
                    user=request.user,
                )
                messages.success(
                    request,
                    f"Rolling batch {batch.wire_serial} created and added to the rolling table.",
                )
                return redirect("rolling:list")
            except (ValidationError, PermissionDenied) as exc:
                detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                messages.error(request, detail)
            except (ValueError, InvalidOperation):
                messages.error(request, "Invalid coil selection. Please check the coils you selected and try again.")
        return render(request, self.template_name, self._context(form))

    @staticmethod
    def _context(form):
        return {
            "form": form,
            "page_title": "New Rolling Batch",
            "page_subtitle": "Create a new rolling batch for manufacturing",
            "page_icon": PAGE_ICON,
            "breadcrumbs": [
                {"label": "Rolling", "url": reverse("rolling:list")},
                {"label": "New Rolling Batch"},
            ],
            "traveller_types": TravellerType.objects.filter(is_active=True).order_by("seq_no"),
            "next_wire_serial": masters_services.peek_next_wire_serial(),
        }

    @staticmethod
    def _parse_coils(raw_json):
        data = json.loads(raw_json or "[]")
        return [(int(row["coil_id"]), Decimal(str(row["weight_taken_kg"]))) for row in data]


class RollingDetailView(LoginRequiredMixin, DetailView):
    model = RollingBatch
    pk_url_kwarg = "pk"
    template_name = "rolling/rolling_detail.html"
    context_object_name = "batch"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        batch = self.object
        ctx.update({
            "page_title": f"Rolling Batch {batch.wire_serial}",
            "page_subtitle": f"{batch.traveller_type.name} · {batch.finish.finish_name} · {batch.wire_diameter_mm} mm",
            "page_icon": PAGE_ICON,
            "breadcrumbs": [
                {"label": "Rolling", "url": reverse("rolling:list")},
                {"label": batch.wire_serial},
            ],
            "coils_used": batch.coils_used.select_related("coil", "coil__rack", "coil__raw_material"),
            "can_complete": self.request.user.can_approve(),
            "complete_form": RollingCompleteForm(),
        })
        return ctx


class RollingCompleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        batch = get_object_or_404(RollingBatch, pk=pk)
        form = RollingCompleteForm(request.POST)
        if form.is_valid():
            try:
                services.complete_rolling_batch(batch, user=request.user, **form.cleaned_data)
                messages.success(request, f"Rolling batch {batch.wire_serial} completed.")
            except (ValidationError, PermissionDenied) as exc:
                detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                messages.error(request, detail)
        else:
            messages.error(request, "Please enter valid rolled thickness, width and finished weight values.")
        return redirect("rolling:detail", pk=pk)
