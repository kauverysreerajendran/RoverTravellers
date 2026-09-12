from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView

from apps.production.services import complete_stage
from apps.production.stage_views import StageCompleteView, StageDetailView

from . import barcode, services
from .forms import HeatBatchInitiateForm, HeatTreatmentCompleteForm
from .models import HeatBatch, HeatTreatmentTransaction


class HeatTreatmentCreateView(LoginRequiredMixin, View):
    """Initiate: one furnace load, not one lot.

    Entered the same way as every other stage - from an incoming row
    (`?lot=`) - but it asks for a batch number and lets the operator tick
    the other lots going into the furnace with it, including lots of
    different traveller types. `?batch=` enters the same screen to add lots
    to a load that is already open.

    It is a plain View rather than the shared StageCreateView because it
    creates several transactions at once; each one is still created by the
    same `initiate_stage` the other stages use.
    """

    template_name = "heat_treatment/heat_batch_form.html"

    @property
    def process(self):
        return services.process()

    def main_table_url(self):
        return reverse("process:main", kwargs={"process": self.process.slug})

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.can_operate_stage(self.process.slug):
            raise PermissionDenied("You are not authorized to create heat treatment transactions.")
        return super().dispatch(request, *args, **kwargs)

    # ------------------------------------------------------------------
    def incoming_rows(self):
        """Everything waiting at this process, as the rows the operator
        ticks: the registry already knows what that is."""
        rows = []
        for record in self.process.incoming_queryset(self.request):
            lot = record.handover_lot
            if lot is None:
                continue
            rows.append({
                "lot": lot,
                "wire_serial": record.wire_serial,
                "traveller_type": record.traveller_type.name if record.traveller_type else "",
                "traveller_no": record.traveller_no.code if record.traveller_no else "",
                "surface_finish": record.surface_finish.finish_name if record.surface_finish else "",
                "received_weight": record.output_weight,
            })
        return rows

    def open_batch(self):
        batch_no = self.request.GET.get("batch", "")
        return HeatBatch.objects.filter(batch_no=batch_no.upper(), status="in_progress").first()

    def context(self, form, rows):
        batch = self.open_batch()
        # Always a list of strings: the template asks "is this lot ticked?"
        # and an unbound form would otherwise hand it None.
        selected = form["lots"].value() or []
        return {
            "form": form,
            "rows": rows,
            "selected_ids": [str(value) for value in selected],
            "batch": batch,
            "page_title": f"Add to Heat Batch {batch.batch_no}" if batch else "New Heat Batch",
            "page_subtitle": "Pick the lots going into the furnace together",
            "page_icon": "bi-fire",
            "next_batch_no": HeatBatch.objects.next_batch_no(),
            "open_batches": HeatBatch.objects.filter(status="in_progress").order_by("-created_at")[:20],
            "breadcrumbs": [
                {"label": self.process.label, "url": self.main_table_url()},
                {"label": "New Heat Batch"},
            ],
        }

    # ------------------------------------------------------------------
    def get(self, request):
        rows = self.incoming_rows()
        if not rows:
            messages.info(request, f"Nothing is waiting at {self.process.label} right now.")
            return redirect(self.main_table_url())

        batch = self.open_batch()
        selected = request.GET.get("lot")
        form = HeatBatchInitiateForm(
            incoming_lots=[row["lot"] for row in rows],
            initial={
                "batch_no": batch.batch_no if batch else HeatBatch.objects.next_batch_no(),
                "operation_date": timezone.localdate(),
                "lots": [selected] if selected else [],
            },
        )
        return render(request, self.template_name, self.context(form, rows))

    def post(self, request):
        rows = self.incoming_rows()
        form = HeatBatchInitiateForm(request.POST, incoming_lots=[row["lot"] for row in rows])
        if form.is_valid():
            chosen = [row["lot"] for row in rows if str(row["lot"].pk) in set(form.cleaned_data["lots"])]
            try:
                batch = services.get_or_create_heat_batch(form.cleaned_data["batch_no"], request.user)
                records = services.initiate_heat_batch(
                    batch, chosen, request.user, operation_date=form.cleaned_data["operation_date"]
                )
            except (ValidationError, PermissionDenied) as exc:
                detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                messages.error(request, detail)
                return render(request, self.template_name, self.context(form, rows))

            messages.success(
                request,
                f"Heat batch {batch.batch_no}: {len(records)} lot{'' if len(records) == 1 else 's'} initiated.",
            )
            return redirect("heat_treatment:batch_detail", batch_no=batch.batch_no)
        return render(request, self.template_name, self.context(form, rows))


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
            "rows": batch_rows(batch, prefill=batch.status != "completed"),
            "scan_url": barcode.scan_url(batch, self.request),
            "can_complete": self.request.user.can_approve() and batch.status != "completed",
            "complete_errors": kwargs.get("complete_errors", []),
        })
        return ctx


def batch_rows(batch, *, prefill=False):
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
            # The load usually comes out weighing what it went in weighing,
            # so that is the starting point the operator adjusts.
            "output_value": transaction.received_weight if prefill else None,
        })
    return rows


class HeatBatchCompleteView(LoginRequiredMixin, View):
    """Finish the whole load from its own page: one output weight per lot,
    all validated before anything is written, then each lot hands over to
    the next process on its own."""

    def post(self, request, batch_no):
        batch = get_object_or_404(HeatBatch, batch_no=batch_no.upper())
        outputs = {}
        for transaction in batch.open_transactions.all():
            outputs[transaction.lot_id] = request.POST.get(f"output-{transaction.lot_id}", "").strip()
        try:
            services.complete_heat_batch(batch, outputs, request.user)
        except (ValidationError, PermissionDenied) as exc:
            detail = exc.messages if hasattr(exc, "messages") else [str(exc)]
            # Re-render rather than redirect: losing a screen of typed
            # weights to a single bad row is not acceptable.
            view = HeatBatchDetailView(request=request, kwargs={"batch_no": batch.batch_no}, object=batch)
            context = view.get_context_data(object=batch, complete_errors=detail)
            return render(request, view.template_name, context)

        messages.success(request, f"Heat batch {batch.batch_no} completed; every lot handed over.")
        return redirect("heat_treatment:batch_detail", batch_no=batch.batch_no)


class HeatBatchQrView(LoginRequiredMixin, View):
    """The batch's QR as an SVG, so a page can <img> it and a label can
    print it at any size without going fuzzy."""

    def get(self, request, batch_no):
        batch = get_object_or_404(HeatBatch, batch_no=batch_no.upper())
        # No caption inside the image: the batch number is already printed
        # beside it, and leaving it out spends the whole box on the code.
        return HttpResponse(
            barcode.render_qr_svg(batch, request, caption=False), content_type="image/svg+xml"
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
def scan_qr(request, token):
    """The QR for a batch addressed by its token, so a table row can show
    its label with nothing but the value it already has."""
    batch = HeatBatch.objects.filter(qr_token=token).first()
    if batch is None:
        raise Http404("That label does not belong to any heat batch.")
    return HttpResponse(
        barcode.render_qr_svg(batch, request, caption=False), content_type="image/svg+xml"
    )


@login_required
def scan(request, token):
    """What a printed label resolves to: the batch page. The token is
    opaque, so a label gives away nothing about the row behind it."""
    batch = HeatBatch.objects.filter(qr_token=token).first()
    if batch is None:
        raise Http404("That label does not belong to any heat batch.")
    return redirect("heat_treatment:batch_detail", batch_no=batch.batch_no)
