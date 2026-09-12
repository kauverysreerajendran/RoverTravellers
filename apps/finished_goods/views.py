from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView

from apps.inventory.models import FinishedGoodsStock
from apps.production.models import ProductionLot
from apps.production.process_registry import get_process
from apps.production.services import incoming_record_for

from . import services
from .forms import FinishedGoodsReceiveForm


class FinishedGoodsReceiveView(LoginRequiredMixin, View):
    """Receiving is always entered from an incoming row on the Finished
    Goods Main Table, so the lot, its identity and the Received Weight all
    come from the completed Finishing record rather than a free lot list."""

    template_name = "finished_goods/finished_goods_form.html"

    @property
    def process(self):
        return get_process("finished_goods")

    def main_table_url(self):
        return reverse("process:main", kwargs={"process": self.process.slug})

    def resolve_incoming(self, request, lot_id):
        """Return (lot, predecessor record) or (None, None) after messaging
        the operator why this lot cannot be received."""
        if not lot_id:
            messages.error(request, "Start receiving from an incoming row on the Main Table.")
            return None, None
        lot = get_object_or_404(ProductionLot, pk=lot_id)
        incoming = incoming_record_for(self.process, lot)
        if incoming is None:
            messages.error(
                request, f"{lot.wire_serial or lot.lot_number} is not waiting at {self.process.label}."
            )
            return None, None
        return lot, incoming

    def _auto(self, lot, incoming):
        return {
            "lot": lot,
            "wire_serial": incoming.wire_serial,
            "traveller_no": incoming.traveller_no,
            "surface_finish": incoming.surface_finish,
            "colour": getattr(incoming, "colour", ""),
            "weight_received": incoming.output_weight,
        }

    def get(self, request):
        lot, incoming = self.resolve_incoming(request, request.GET.get("lot"))
        if lot is None:
            return redirect(self.main_table_url())
        form = FinishedGoodsReceiveForm(
            initial={"lot": lot.pk, "accepted_quantity": incoming.output_weight}
        )
        return render(
            request, self.template_name,
            {"form": form, "page_title": "Receive Finished Goods", "auto": self._auto(lot, incoming)},
        )

    def post(self, request):
        lot, incoming = self.resolve_incoming(request, request.POST.get("lot"))
        if lot is None:
            return redirect(self.main_table_url())
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
        return render(
            request, self.template_name,
            {"form": form, "page_title": "Receive Finished Goods", "auto": self._auto(lot, incoming)},
        )


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


class FinishedGoodsRemoveFromRackView(LoginRequiredMixin, View):
    """Finished Goods is the terminal process, so nothing downstream frees
    its rack slots: stock leaves a slot only through this action."""

    def post(self, request, pk):
        fg_stock = get_object_or_404(FinishedGoodsStock, pk=pk)
        try:
            slot = services.remove_from_rack(fg_stock, request.user, reason=request.POST.get("reason", ""))
            messages.success(request, f"{fg_stock.fg_lot_number} removed from {slot.label}.")
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
