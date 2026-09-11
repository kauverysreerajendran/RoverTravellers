from django.urls import path

from . import api_views

urlpatterns = [
    path("reports/production/", api_views.ProductionReportAPIView.as_view(), name="api-report-production"),
    path("reports/traceability/", api_views.TraceabilityReportAPIView.as_view(), name="api-report-traceability"),
]
