from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView

from apps.audit.models import log_action

from . import forms, models, services


class ProductionOrderListView(LoginRequiredMixin, ListView):
    model = models.ProductionOrder
    template_name = "production/order_list.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_queryset(self):
        qs = models.ProductionOrder.objects.select_related("product").order_by("-created_at")
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Production Orders"
        ctx["status_choices"] = models.ORDER_STATUS_CHOICES
        return ctx


class ProductionOrderCreateView(LoginRequiredMixin, CreateView):
    model = models.ProductionOrder
    form_class = forms.ProductionOrderForm
    template_name = "production/order_form.html"
    success_url = reverse_lazy("production:order_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        log_action(self.request.user, "create", self.object, description="Production order created")
        messages.success(self.request, f"Production order {self.object.order_number} created.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "New Production Order"
        return ctx


class ProductionOrderDetailView(LoginRequiredMixin, DetailView):
    model = models.ProductionOrder
    template_name = "production/order_detail.html"
    context_object_name = "order"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"Order {self.object.order_number}"
        ctx["lots"] = self.object.lots.all()
        return ctx


class ProductionLotListView(LoginRequiredMixin, ListView):
    model = models.ProductionLot
    template_name = "production/lot_list.html"
    context_object_name = "lots"
    paginate_by = 20

    def get_queryset(self):
        qs = models.ProductionLot.objects.select_related("production_order").order_by("-created_at")
        stage = self.request.GET.get("stage")
        if stage:
            qs = qs.filter(current_stage=stage)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Production Lots"
        ctx["stage_choices"] = models.LOT_STAGE_CHOICES
        return ctx


class ProductionLotCreateView(LoginRequiredMixin, CreateView):
    model = models.ProductionLot
    form_class = forms.ProductionLotForm
    template_name = "production/lot_form.html"
    success_url = reverse_lazy("production:lot_list")

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        log_action(self.request.user, "create", self.object, description="Production lot created")
        messages.success(self.request, f"Lot {self.object.lot_number} created.")
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "New Production Lot"
        return ctx


class ProductionLotDetailView(LoginRequiredMixin, DetailView):
    """Lot traceability screen: shows every stage transaction for a lot,
    from raw material through finished goods."""

    model = models.ProductionLot
    template_name = "production/lot_detail.html"
    context_object_name = "lot"

    def get_context_data(self, **kwargs):
        from apps.finishing.models import FinishingTransaction
        from apps.inventory.models import FinishedGoodsStock
        from apps.forming.models import FormingTransaction
        from apps.heat_treatment.models import HeatTreatmentTransaction
        from apps.rolling.models import RollingTransaction

        ctx = super().get_context_data(**kwargs)
        lot = self.object
        ctx["page_title"] = f"Lot {lot.lot_number} Traceability"
        ctx["rolling_ops"] = RollingTransaction.objects.filter(lot=lot)
        ctx["forming_ops"] = FormingTransaction.objects.filter(lot=lot)
        ctx["heat_treatment_ops"] = HeatTreatmentTransaction.objects.filter(lot=lot)
        ctx["finishing_ops"] = FinishingTransaction.objects.filter(lot=lot)
        ctx["finished_goods"] = FinishedGoodsStock.objects.filter(lot=lot)
        ctx["wip_stock"] = lot.wip_stock.select_related("location").all()
        ctx["stepper_steps"] = services.stage_progress(lot)
        return ctx


class ProcessTrackerView(LoginRequiredMixin, ListView):
    """Horizontal stepper overview of the manufacturing pipeline plus a
    batch-level table showing every lot's current stage at a glance."""

    model = models.ProductionLot
    template_name = "production/process_tracker.html"
    context_object_name = "lots"
    paginate_by = 25

    def get_queryset(self):
        return models.ProductionLot.objects.select_related("production_order__product").order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Process Tracker"

        selected_id = self.request.GET.get("lot")
        featured_lot = None
        if selected_id:
            featured_lot = models.ProductionLot.objects.filter(pk=selected_id).first()
        if not featured_lot:
            featured_lot = (
                models.ProductionLot.objects.exclude(current_stage="finished_goods")
                .order_by("-created_at")
                .first()
                or models.ProductionLot.objects.order_by("-created_at").first()
            )

        ctx["featured_lot"] = featured_lot
        ctx["stepper_steps"] = services.stage_progress(featured_lot) if featured_lot else []

        rows = []
        for lot in ctx["lots"]:
            spec = lot.production_order.product.specifications.filter(parameter_name__icontains="diameter").first()
            if lot.current_stage == "finished_goods" and lot.finished_goods.filter(status="available").exists():
                status = "completed"
            elif lot.is_on_hold:
                status = "hold"
            else:
                status = "in_progress"
            rows.append({
                "lot": lot,
                "diameter": spec.target_value if spec else None,
                "status": status,
            })
        ctx["rows"] = rows
        return ctx
