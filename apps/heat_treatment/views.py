from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView

from apps.production.services import complete_stage
from apps.production.stage_views import StageCompleteView, StageCreateView, StageDetailView

from . import barcode
from .forms import HeatTreatmentCompleteForm, HeatTreatmentInitiateForm
from .models import HeatBatch, HeatTreatmentTransaction


class HeatTreatmentCreateView(StageCreateView):
    model = HeatTreatmentTransaction
    form_class = HeatTreatmentInitiateForm
    stage = "heat_treatment"
    page_title = "Heat Treatment Transaction"
    list_url_name = "heat_treatment:list"
    complete_url_name = "heat_treatment:complete"
    checklist = [
        "Select the completed Forming lot and enter the Batch No",
        "Pick the date and Surface Finish - Received Weight is auto-filled",
        "Initiating creates the transaction; enter the finished weight on the Complete screen",
        "Completing the transaction stages the output for Finishing",
    ]


class HeatTreatmentDetailView(StageDetailView):
    model = HeatTreatmentTransaction
    stage = "heat_treatment"
    page_title = "Heat Treatment"
    complete_url_name = "heat_treatment:complete"


class HeatTreatmentCompleteView(StageCompleteView):
    model = HeatTreatmentTransaction
    complete_form_class = HeatTreatmentCompleteForm
    complete_fn = staticmethod(complete_stage)
    stage = "heat_treatment"
    page_title = "Heat Treatment"
    detail_url_name = "heat_treatment:detail"
    list_url_name = "heat_treatment:list"


# ----------------------------------------------------------------------
# The heat batch: its page, its label, and the QR that leads back here.
# ----------------------------------------------------------------------
class HeatBatchDetailView(LoginRequiredMixin, DetailView):
    """Where a scanned label lands: everything in this furnace load, and
    where each of its lots has got to since."""

    model = HeatBatch
    template_name = "heat_treatment/heat_batch_detail.html"
    context_object_name = "batch"
    slug_field = "batch_no"
    slug_url_kwarg = "batch_no"

    def get_object(self, queryset=None):
        return get_object_or_404(HeatBatch, batch_no=self.kwargs["batch_no"].upper())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        batch = self.object
        ctx.update({
            "page_title": f"Heat Batch {batch.batch_no}",
            "page_subtitle": "Everything that went into the furnace together",
            "page_icon": "bi-upc-scan",
            "breadcrumbs": [
                {"label": "Heat Treatment", "url": reverse("heat_treatment:list")},
                {"label": batch.batch_no},
            ],
            "rows": batch_rows(batch),
            "scan_url": barcode.scan_url(batch, self.request),
        })
        return ctx


def batch_rows(batch):
    """One row per lot in the batch: what it is, what it weighed, and where
    it has got to since the furnace. The current process comes from the lot
    and the rack slot from the handover contract, so this needs no
    knowledge of which stages exist."""
    from apps.masters import services as rack_services
    from apps.production.process_registry import get_process

    rows = []
    for transaction in batch.transactions.select_related(
        "lot", "lot__source_rolling_batch__traveller_type", "surface_finish"
    ).order_by("created_at"):
        lot = transaction.lot
        current = get_process(lot.current_stage) if lot else None
        zone = rack_services.zone_for_process(current)
        slot = rack_services.slot_for_lot(zone, lot) if zone else None
        rows.append({
            "transaction": transaction,
            "lot": lot,
            "current_process": current.label if current else "-",
            "rack_slot": slot.label if slot else "",
        })
    return rows


class HeatBatchQrView(LoginRequiredMixin, View):
    """The batch's QR as an SVG, so a page can <img> it and a label can
    print it at any size without going fuzzy."""

    def get(self, request, batch_no):
        batch = get_object_or_404(HeatBatch, batch_no=batch_no.upper())
        return HttpResponse(
            barcode.render_qr_svg(batch, request), content_type="image/svg+xml"
        )


class HeatBatchLabelView(LoginRequiredMixin, DetailView):
    """The printable label: A7, QR, batch number and what is in the load."""

    model = HeatBatch
    template_name = "heat_treatment/heat_batch_label.html"
    context_object_name = "batch"

    def get_object(self, queryset=None):
        return get_object_or_404(HeatBatch, batch_no=self.kwargs["batch_no"].upper())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            "page_title": f"Label {self.object.batch_no}",
            # Inlined rather than <img>-ed: a label must print even if the
            # browser is fetching nothing else.
            "qr_svg": barcode.render_qr_svg(self.object, self.request, caption=False),
            "scan_url": barcode.scan_url(self.object, self.request),
            "code128": barcode.render_code128_svg(self.object),
        })
        return ctx


@login_required
def scan(request, token):
    """What a printed label resolves to: the batch page. The token is
    opaque, so a label gives away nothing about the row behind it."""
    batch = HeatBatch.objects.filter(qr_token=token).first()
    if batch is None:
        raise Http404("That label does not belong to any heat batch.")
    return redirect("heat_treatment:batch_detail", batch_no=batch.batch_no)
