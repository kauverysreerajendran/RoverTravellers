from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from . import services
from .forms import CoilReceiveForm
from .models import CoilMaster, DiameterMaster, RackMaster, RackZone


def rack_tabs(active=""):
    """The Rack screen's tab strip: the raw-material coil bay first, then one
    tab per active storage zone. Zones are read from the database, so a new
    zone appears here without touching this view."""
    tabs = [{
        "code": "",
        "label": "Raw Material",
        "url": reverse("masters:rack_locator"),
        "active": not active,
    }]
    for zone in RackZone.objects.filter(is_active=True).order_by("code"):
        tabs.append({
            "code": zone.code,
            "label": zone.name,
            "url": reverse("masters:rack_zone", kwargs={"code": zone.code}),
            "active": active == zone.code,
        })
    return tabs


class RackLocatorView(LoginRequiredMixin, TemplateView):
    """Every rack with its stocked coils and free slots, searchable live so an
    operator can type a coil number / diameter / raw material id and see
    exactly which rack it sits on."""

    template_name = "masters/rack_locator.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        stocked = CoilMaster.objects.filter(status="In Stock").select_related("raw_material").order_by("coil_display_number")
        racks = (
            RackMaster.objects.filter(is_active=True)
            .order_by("rack_code")
            .prefetch_related(Prefetch("coils", queryset=stocked, to_attr="stocked_coils"))
        )

        rows, total_slots, occupied = [], 0, 0
        for rack in racks:
            coils = rack.stocked_coils
            empty = max(rack.capacity - len(coils), 0)
            rows.append({
                "rack": rack,
                "coils": coils,
                "occupied": len(coils),
                "empty_slots": range(empty),
                "pct": int(len(coils) / rack.capacity * 100) if rack.capacity else 0,
            })
            total_slots += rack.capacity
            occupied += len(coils)

        ctx.update({
            "rack_tabs": rack_tabs(),
            "page_title": "Rack",
            "page_subtitle": "Locate coils and find empty rack space",
            "page_icon": "bi-grid-3x3-gap",
            "racks": rows,
            "unracked": stocked.filter(rack__isnull=True),
            "total_racks": len(rows),
            "total_slots": total_slots,
            "occupied": occupied,
            "empty": max(total_slots - occupied, 0),
        })
        return ctx


class RackZoneView(LoginRequiredMixin, TemplateView):
    """One storage zone: every rack as a real grid of slots, occupied and
    empty alike, searchable by wire serial, traveller type or slot label."""

    template_name = "masters/rack_zone.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        zone = get_object_or_404(RackZone, code=self.kwargs["code"], is_active=True)
        summary = services.zone_summary(zone)
        ctx.update(summary)
        ctx.update({
            "rack_tabs": rack_tabs(zone.code),
            "page_title": "Rack",
            "page_subtitle": f"{zone.name} - locate material and find empty slots",
            "page_icon": "bi-grid-3x3-gap",
        })
        return ctx


class DiameterListView(LoginRequiredMixin, TemplateView):
    """Raw Material List (Phase 1, Screen 1): diameter, total stock, active coils."""

    template_name = "masters/diameter_list.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        diameters = DiameterMaster.objects.order_by("diameter_mm")
        ctx.update({
            "page_title": "Inventory",
            "page_subtitle": "Raw material stock by diameter",
            "page_icon": "bi-boxes",
            "diameters": diameters,
            "with_stock": diameters.filter(active_coils__gt=0).count(),
        })
        return ctx


class DiameterDetailView(LoginRequiredMixin, View):
    """Diameter Details (Screen 2) plus Add New Coil (Screen 3)."""

    template_name = "masters/diameter_detail.html"

    def get(self, request, pk):
        diameter = get_object_or_404(DiameterMaster, pk=pk)
        return render(request, self.template_name, self._context(diameter, CoilReceiveForm()))

    def post(self, request, pk):
        diameter = get_object_or_404(DiameterMaster, pk=pk)
        form = CoilReceiveForm(request.POST)
        if form.is_valid():
            try:
                coil = services.receive_coil(
                    raw_material=diameter,
                    weight_kg=form.cleaned_data["weight_kg"],
                    rack=form.cleaned_data.get("rack"),
                    supplier=form.cleaned_data.get("supplier", ""),
                    received_date=form.cleaned_data.get("received_date"),
                )
                messages.success(request, f"Coil {coil.coil_display_number} ({coil.weight_kg} kg) added to {diameter.raw_material_id}.")
                return redirect("masters:diameter_detail", pk=pk)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
        return render(request, self.template_name, self._context(diameter, form))

    @staticmethod
    def _context(diameter, form):
        return {
            "page_title": f"{diameter.raw_material_id} · {diameter.diameter_mm} mm",
            "page_subtitle": "Coils in stock for this diameter",
            "page_icon": "bi-rulers",
            "breadcrumbs": [
                {"label": "Inventory", "url": reverse("masters:diameter_list")},
                {"label": diameter.raw_material_id},
            ],
            "diameter": diameter,
            "coils": diameter.coils.select_related("rack").order_by("-status", "coil_display_number"),
            "form": form,
        }
