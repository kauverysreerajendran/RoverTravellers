from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("production/", views.ProductionReportView.as_view(), name="production"),
    path("process-wise/", views.ProcessWiseReportView.as_view(), name="process_wise"),
    path("traceability/", views.TraceabilityReportView.as_view(), name="traceability"),
    path("inventory/", views.InventoryReportView.as_view(), name="inventory"),
    path("rejection/", views.RejectionReportView.as_view(), name="rejection"),
    path("quality/", views.QualityReportView.as_view(), name="quality"),
    path("finished-goods/", views.FinishedGoodsReportView.as_view(), name="finished_goods"),
    path("date-summary/", views.DateWiseSummaryReportView.as_view(), name="date_summary"),
    path("export/<str:report_type>/", views.export_csv, name="export_csv"),
]
