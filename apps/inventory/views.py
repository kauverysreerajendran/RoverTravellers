from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, View

from apps.common.views import DynamicPageSizeMixin

from . import forms, models, services


class RawMaterialStockListView(LoginRequiredMixin, DynamicPageSizeMixin, ListView):
    model = models.RawMaterialStock
    template_name = "inventory/raw_material_stock_list.html"
    context_object_name = "stocks"

    def get_queryset(self):
        return models.RawMaterialStock.objects.select_related("material", "location").order_by("material__material_code")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Raw Material Stock"
        return ctx


class WIPStockListView(LoginRequiredMixin, DynamicPageSizeMixin, ListView):
    model = models.WIPStock
    template_name = "inventory/wip_stock_list.html"
    context_object_name = "stocks"

    def get_queryset(self):
        qs = models.WIPStock.objects.select_related("lot", "lot__source_rolling_batch", "location").order_by("stage", "-created_at")
        stage = self.request.GET.get("stage")
        if stage:
            qs = qs.filter(stage=stage)
        return qs

    def get_context_data(self, **kwargs):
        from apps.production.models import LOT_STAGE_CHOICES

        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "WIP Stock"
        ctx["stage_choices"] = LOT_STAGE_CHOICES
        return ctx


class FinishedGoodsStockListView(LoginRequiredMixin, DynamicPageSizeMixin, ListView):
    model = models.FinishedGoodsStock
    template_name = "inventory/finished_goods_stock_list.html"
    context_object_name = "stocks"

    def get_queryset(self):
        return models.FinishedGoodsStock.objects.select_related("product", "lot", "lot__source_rolling_batch", "location").order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Finished Goods Stock"
        return ctx


class StockTransactionListView(LoginRequiredMixin, DynamicPageSizeMixin, ListView):
    model = models.StockTransaction
    template_name = "inventory/stock_ledger.html"
    context_object_name = "transactions"

    def get_queryset(self):
        qs = models.StockTransaction.objects.select_related("material", "lot", "location").order_by("-created_at")
        stock_type = self.request.GET.get("stock_type")
        if stock_type:
            qs = qs.filter(stock_type=stock_type)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Stock Ledger"
        ctx["stock_type_choices"] = models.StockTransaction.STOCK_TYPE_CHOICES
        return ctx


class StockTransferListView(LoginRequiredMixin, DynamicPageSizeMixin, ListView):
    model = models.StockTransfer
    template_name = "inventory/stock_transfer_list.html"
    context_object_name = "transfers"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Stock Transfers"
        return ctx


class StockTransferCreateView(LoginRequiredMixin, CreateView):
    model = models.StockTransfer
    form_class = forms.StockTransferForm
    template_name = "inventory/stock_transfer_form.html"
    success_url = reverse_lazy("inventory:transfer_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, f"Transfer {self.object.transfer_number} created as pending.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "New Stock Transfer"
        return ctx


class StockTransferCompleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        transfer = models.StockTransfer.objects.get(pk=pk)
        try:
            services.transfer_stock(transfer, user=request.user)
            messages.success(request, f"Transfer {transfer.transfer_number} completed.")
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
        return redirect("inventory:transfer_list")


class StockAdjustmentListView(LoginRequiredMixin, DynamicPageSizeMixin, ListView):
    model = models.StockAdjustment
    template_name = "inventory/stock_adjustment_list.html"
    context_object_name = "adjustments"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Stock Adjustments"
        return ctx


class StockAdjustmentCreateView(LoginRequiredMixin, CreateView):
    model = models.StockAdjustment
    form_class = forms.StockAdjustmentForm
    template_name = "inventory/stock_adjustment_form.html"
    success_url = reverse_lazy("inventory:adjustment_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        form.instance.quantity_before = 0
        self.object = form.save()
        try:
            services.apply_adjustment(self.object, user=self.request.user)
            messages.success(self.request, f"Adjustment {self.object.adjustment_number} applied.")
        except ValidationError as exc:
            self.object.delete()
            messages.error(self.request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
            return redirect("inventory:adjustment_create")
        return redirect(self.success_url)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "New Stock Adjustment"
        return ctx
