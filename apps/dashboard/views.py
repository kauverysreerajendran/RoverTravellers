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

    from apps.masters.models import TravellerType
    from apps.rolling.models import RollingBatch

    q = request.GET.get("q", "").strip()
    if not q:
        return redirect("dashboard:overview")

    batch = RollingBatch.objects.filter(wire_serial__iexact=q).first()
    if batch:
        return redirect("rolling:detail", pk=batch.pk)

    if RollingBatch.objects.filter(wire_serial__icontains=q).exists() or TravellerType.objects.filter(name__icontains=q).exists():
        return redirect(f"{reverse('rolling:list')}?q={q}")

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

    messages.info(request, f'Nothing found matching "{q}" (wire serial, traveller type, lot, order, material or product).')
    return redirect("dashboard:overview")
