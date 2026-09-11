from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from . import services


class DashboardOverviewView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/overview.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Dashboard"
        ctx.update(services.get_dashboard_summary())
        return ctx


@login_required
def global_search(request):
    from apps.inventory.models import FinishedGoodsStock
    from apps.master_data.models import MaterialMaster, ProductMaster
    from apps.production.models import ProductionLot, ProductionOrder

    q = request.GET.get("q", "").strip()
    if not q:
        return redirect("dashboard:overview")

    lot = ProductionLot.objects.filter(lot_number__icontains=q).first()
    if lot:
        return redirect("production:lot_detail", pk=lot.pk)

    order = ProductionOrder.objects.filter(order_number__icontains=q).first()
    if order:
        return redirect("production:order_detail", pk=order.pk)

    fg = FinishedGoodsStock.objects.filter(fg_lot_number__icontains=q).first()
    if fg:
        return redirect("finished_goods:detail", pk=fg.pk)

    if MaterialMaster.objects.filter(material_code__icontains=q).exists():
        return redirect(f"{reverse('master_data:material_list')}?q={q}")

    if ProductMaster.objects.filter(product_code__icontains=q).exists():
        return redirect(f"{reverse('master_data:product_list')}?q={q}")

    messages.info(request, f'No lot, order, finished goods, material, or product found matching "{q}".')
    return redirect("dashboard:overview")
