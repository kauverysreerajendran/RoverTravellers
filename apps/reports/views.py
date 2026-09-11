import csv

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views.generic import TemplateView

from apps.dashboard.services import STAGE_MODELS, get_stage_summary
from apps.inventory.models import FinishedGoodsStock, RawMaterialStock, WIPStock
from apps.production.models import OperationQualityCheck, ProductionLot, ProductionOrder


class ProductionReportView(LoginRequiredMixin, TemplateView):
    template_name = "reports/production_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Production Report"
        ctx["orders"] = ProductionOrder.objects.select_related("product").order_by("-created_at")[:100]
        return ctx


class ProcessWiseReportView(LoginRequiredMixin, TemplateView):
    template_name = "reports/process_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Process-wise Report"
        ctx["stage_summary"] = get_stage_summary()
        return ctx


class TraceabilityReportView(LoginRequiredMixin, TemplateView):
    template_name = "reports/traceability_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Lot Traceability Report"
        lot_number = self.request.GET.get("lot_number", "").strip()
        ctx["lot_number"] = lot_number
        if lot_number:
            ctx["lot"] = ProductionLot.objects.filter(lot_number__icontains=lot_number).first()
        return ctx


class InventoryReportView(LoginRequiredMixin, TemplateView):
    template_name = "reports/inventory_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Inventory Report"
        ctx["raw_material_stock"] = RawMaterialStock.objects.select_related("material", "location")
        ctx["wip_stock"] = WIPStock.objects.select_related("lot", "lot__source_rolling_batch", "location")
        ctx["finished_goods_stock"] = FinishedGoodsStock.objects.select_related(
            "product", "lot", "lot__source_rolling_batch", "location"
        )
        return ctx


class RejectionReportView(LoginRequiredMixin, TemplateView):
    template_name = "reports/rejection_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Rejection Report"
        rows = []
        for stage, model in STAGE_MODELS.items():
            for txn in model.objects.filter(rejection_quantity__gt=0).select_related("lot", "lot__source_rolling_batch", "machine")[:200]:
                rows.append(
                    {
                        "stage": stage,
                        "transaction_number": txn.transaction_number,
                        "wire_serial": txn.lot.wire_serial,
                        "machine": txn.machine.name,
                        "rejection_quantity": txn.rejection_quantity,
                        "reason": txn.rejection_reason.description if txn.rejection_reason else "",
                        "created_at": txn.created_at,
                    }
                )
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        ctx["rows"] = rows
        return ctx


class QualityReportView(LoginRequiredMixin, TemplateView):
    template_name = "reports/quality_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Quality Report"
        ctx["checks"] = OperationQualityCheck.objects.select_related("inspector").order_by("-created_at")[:200]
        return ctx


class FinishedGoodsReportView(LoginRequiredMixin, TemplateView):
    template_name = "reports/finished_goods_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Finished Goods Report"
        ctx["items"] = FinishedGoodsStock.objects.select_related(
            "product", "lot", "lot__source_rolling_batch", "location"
        ).order_by("-created_at")
        return ctx


class DateWiseSummaryReportView(LoginRequiredMixin, TemplateView):
    template_name = "reports/date_summary_report.html"

    def get_context_data(self, **kwargs):
        from django.db.models import Count, Sum
        from django.db.models.functions import TruncDate

        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Date-wise Summary"
        summaries = []
        for stage, model in STAGE_MODELS.items():
            data = (
                model.objects.annotate(day=TruncDate("created_at"))
                .values("day")
                .annotate(
                    total_input=Sum("input_quantity"), total_output=Sum("output_quantity"),
                    total_rejection=Sum("rejection_quantity"), count=Count("id"),
                )
                .order_by("-day")[:30]
            )
            for row in data:
                row["stage"] = stage
                summaries.append(row)
        summaries.sort(key=lambda r: r["day"], reverse=True)
        ctx["summaries"] = summaries
        return ctx


def export_csv(request, report_type):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f"attachment; filename={report_type}_report.csv"
    writer = csv.writer(response)

    if report_type == "finished-goods":
        writer.writerow(["FG Batch", "Product", "Wire Serial", "Accepted Qty", "Rejected Qty", "Status", "Quality Approved", "Created At"])
        for item in FinishedGoodsStock.objects.select_related("product", "lot", "lot__source_rolling_batch"):
            writer.writerow([
                item.fg_lot_number, item.product.product_code, item.lot.wire_serial,
                item.accepted_quantity, item.rejected_quantity, item.status, item.quality_approved, item.created_at,
            ])
    elif report_type == "inventory":
        writer.writerow(["Type", "Reference", "Location", "Quantity", "Status"])
        for s in RawMaterialStock.objects.select_related("material", "location"):
            writer.writerow(["Raw Material", s.material.material_code, s.location.name, s.quantity, s.status])
        for s in WIPStock.objects.select_related("lot", "lot__source_rolling_batch", "location"):
            writer.writerow(["WIP", s.lot.wire_serial, s.location.name, s.quantity, s.status])
    elif report_type == "rejection":
        writer.writerow(["Stage", "Transaction", "Wire Serial", "Rejection Qty", "Created At"])
        for stage, model in STAGE_MODELS.items():
            for txn in model.objects.filter(rejection_quantity__gt=0).select_related("lot", "lot__source_rolling_batch"):
                writer.writerow([stage, txn.transaction_number, txn.lot.wire_serial, txn.rejection_quantity, txn.created_at])
    else:
        writer.writerow(["Order Number", "Product", "Planned Qty", "Status", "Created At"])
        for order in ProductionOrder.objects.select_related("product"):
            writer.writerow([order.order_number, order.product.product_code, order.planned_quantity, order.status, order.created_at])

    return response
