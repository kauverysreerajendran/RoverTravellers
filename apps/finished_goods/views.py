from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView

from apps.finishing.models import FinishingTransaction
from apps.inventory.models import FinishedGoodsStock, WIPStock
from apps.production.models import ProductionLot

from . import services
from .forms import FinishedGoodsReceiveForm


class FinishedGoodsListView(LoginRequiredMixin, ListView):
    model = FinishedGoodsStock
    template_name = "finished_goods/finished_goods_list.html"
    context_object_name = "items"
    paginate_by = 20

    def get_queryset(self):
        qs = FinishedGoodsStock.objects.select_related(
            "product", "lot", "lot__source_rolling_batch", "location"
        ).order_by("-created_at")
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Finished Goods"
        ctx["status_choices"] = FinishedGoodsStock._meta.get_field("status").choices
        received_lot_ids = FinishedGoodsStock.objects.values_list("lot_id", flat=True)
        ctx["pending_lots"] = (
            ProductionLot.objects.filter(current_stage="finished_goods")
            .exclude(pk__in=list(received_lot_ids))
            .select_related("source_rolling_batch")
            .order_by("-created_at")
        )
        return ctx


class FinishedGoodsReceiveView(LoginRequiredMixin, View):
    template_name = "finished_goods/finished_goods_form.html"

    def get(self, request):
        lot_id = request.GET.get("lot")
        initial = {}
        auto = None
        if lot_id:
            lot = get_object_or_404(ProductionLot, pk=lot_id, current_stage="finished_goods")
            available = (
                WIPStock.objects.filter(stage="finished_goods", lot=lot, status="available")
                .values_list("quantity", flat=True)
                .first()
            )
            initial["lot"] = lot.pk
            if available is not None:
                initial["accepted_quantity"] = available
            finishing = FinishingTransaction.objects.filter(lot=lot, status="completed").order_by("-created_at").first()
            auto = {
                "lot": lot,
                "wire_serial": lot.wire_serial,
                "traveller_no": lot.traveller_no,
                "traveller_date": lot.traveller_date,
                "surface_finish": finishing.surface_finish if finishing else lot.surface_finish,
                "colour": finishing.colour if finishing else "",
                "weight_received": available,
            }
        form = FinishedGoodsReceiveForm(initial=initial)
        return render(
            request, self.template_name,
            {"form": form, "page_title": "Receive Finished Goods", "auto": auto},
        )

    def post(self, request):
        form = FinishedGoodsReceiveForm(request.POST)
        if form.is_valid():
            try:
                fg_stock = services.receive_finished_goods(
                    lot=form.cleaned_data["lot"],
                    product=form.cleaned_data["product"],
                    accepted_quantity=form.cleaned_data["accepted_quantity"],
                    rejected_quantity=form.cleaned_data["rejected_quantity"],
                    location=form.cleaned_data["location"],
                    rack=form.cleaned_data.get("rack"),
                    shelf=form.cleaned_data.get("shelf"),
                    tray=form.cleaned_data.get("tray"),
                    user=request.user,
                    remarks=form.cleaned_data.get("remarks", ""),
                )
                messages.success(request, f"Finished goods {fg_stock.fg_lot_number} received and on hold for QC.")
                return redirect("finished_goods:detail", pk=fg_stock.pk)
            except (ValidationError, PermissionDenied) as exc:
                detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                messages.error(request, detail)
        auto = None
        lot = form.cleaned_data.get("lot") if form.is_bound and hasattr(form, "cleaned_data") else None
        if lot:
            auto = {
                "lot": lot, "wire_serial": lot.wire_serial, "traveller_no": lot.traveller_no,
                "traveller_date": lot.traveller_date, "surface_finish": lot.surface_finish,
            }
        return render(request, self.template_name, {"form": form, "page_title": "Receive Finished Goods", "auto": auto})


class FinishedGoodsDetailView(LoginRequiredMixin, DetailView):
    model = FinishedGoodsStock
    template_name = "finished_goods/finished_goods_detail.html"
    context_object_name = "item"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"Finished Goods {self.object.fg_lot_number}"
        ctx["can_approve"] = self.request.user.can_approve()
        return ctx


class FinishedGoodsApproveView(LoginRequiredMixin, View):
    def post(self, request, pk):
        fg_stock = get_object_or_404(FinishedGoodsStock, pk=pk)
        try:
            services.approve_finished_goods(fg_stock, request.user, mark_available=True)
            messages.success(request, f"{fg_stock.fg_lot_number} approved and marked available.")
        except (ValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            messages.error(request, detail)
        return redirect("finished_goods:detail", pk=pk)


class FinishedGoodsRejectView(LoginRequiredMixin, View):
    def post(self, request, pk):
        fg_stock = get_object_or_404(FinishedGoodsStock, pk=pk)
        try:
            services.reject_finished_goods(fg_stock, request.user, remarks=request.POST.get("remarks", ""))
            messages.success(request, f"{fg_stock.fg_lot_number} rejected.")
        except (ValidationError, PermissionDenied) as exc:
            detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            messages.error(request, detail)
        return redirect("finished_goods:detail", pk=pk)


class FinishedGoodsHoldView(LoginRequiredMixin, View):
    def post(self, request, pk):
        fg_stock = get_object_or_404(FinishedGoodsStock, pk=pk)
        services.hold_finished_goods(fg_stock, request.user)
        messages.success(request, f"{fg_stock.fg_lot_number} put on hold.")
        return redirect("finished_goods:detail", pk=pk)
