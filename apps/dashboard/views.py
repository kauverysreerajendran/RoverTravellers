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


def _slot_by_label(label):
    """Resolve "FR-03-B4" to its RackSlot, or None if it is not one."""
    from apps.masters.models import ROW_LETTERS, RackSlot

    rack_code, _, cell = label.strip().rpartition("-")
    if not rack_code or len(cell) < 2 or not cell[1:].isdigit():
        return None
    row = ROW_LETTERS.find(cell[0].upper()) + 1
    if not row:
        return None
    return (
        RackSlot.objects.select_related("rack", "zone")
        .filter(rack__code__iexact=rack_code, row=row, column=int(cell[1:]))
        .first()
    )


@login_required
def global_search(request):
    """The one search box in the product: the header scan.

    The process tables and the rack screens carry no search of their own,
    so this has to answer for all of them. It resolves what was scanned to
    the screen that shows it *now*: a wire serial lands on the table of the
    process the material is currently at (scan it while it sits in Heat
    Treatment and you get the Heat Treatment table, filtered to it), a slot
    label lands on that rack zone at the slot, and anything a process
    declares as searchable lands on that process's table.

    Which processes exist, what each can be searched by and where material
    currently is all come from the registry and the lot, so a sixth process
    is searchable here without touching this view.
    """
    from apps.inventory.models import FinishedGoodsStock
    from apps.master_data.models import MaterialMaster, ProductMaster
    from apps.production.models import ProductionLot, ProductionOrder
    from apps.production.process_registry import PROCESSES, get_process
    from apps.rolling.models import RollingBatch

    q = request.GET.get("q", "").strip()
    if not q:
        return redirect("dashboard:overview")

    def table_for(process, term):
        return redirect(f"{reverse('process:main', kwargs={'process': process.slug})}?q={term}")

    def process_holding(lot):
        """The process a lot is at right now; before anything has touched
        it, that is the first process in the registry."""
        return get_process(lot.current_stage) if lot else None

    # A scanned wire serial: show it where the material actually is.
    batch = (
        RollingBatch.objects.filter(wire_serial__iexact=q).first()
        or RollingBatch.objects.filter(wire_serial__icontains=q).first()
    )
    if batch:
        process = process_holding(batch.handover_lot) or PROCESSES[0]
        return table_for(process, batch.wire_serial)

    # A scanned slot label (FR-03-B4) opens its zone at that slot. The rack
    # code carries a dash of its own, so the cell is whatever follows the
    # last one.
    slot = _slot_by_label(q)
    if slot:
        url = reverse("masters:rack_zone", kwargs={"code": slot.zone.code})
        return redirect(f"{url}#slot-{slot.label}")

    lot = ProductionLot.objects.filter(lot_number__icontains=q).first()
    if lot:
        return redirect("production:lot_detail", pk=lot.pk)

    order = ProductionOrder.objects.filter(order_number__icontains=q).first()
    if order:
        return redirect("production:order_detail", pk=order.pk)

    fg = FinishedGoodsStock.objects.filter(fg_lot_number__icontains=q).first()
    if fg:
        return redirect("finished_goods:detail", pk=fg.pk)

    # Anything a process declares as searchable - Heat Treatment batch
    # numbers, Finishing colours, machine codes, transaction numbers.
    for process in PROCESSES:
        if process.search_fields and process.filter_queryset(process.base_queryset(), search=q).exists():
            return table_for(process, q)

    if MaterialMaster.objects.filter(material_code__icontains=q).exists():
        return redirect(f"{reverse('master_data:material_list')}?q={q}")

    if ProductMaster.objects.filter(product_code__icontains=q).exists():
        return redirect(f"{reverse('master_data:product_list')}?q={q}")

    messages.info(
        request,
        f'Nothing found matching "{q}" (wire serial, traveller type, batch no, '
        "rack slot, lot, order, material or product).",
    )
    return redirect("dashboard:overview")
