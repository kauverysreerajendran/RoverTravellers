from django.urls import path

from . import api_views

urlpatterns = [
    path("dashboard/summary/", api_views.DashboardSummaryView.as_view(), name="api-dashboard-summary"),
    path("dashboard/overview/", api_views.DashboardOverviewApiView.as_view(), name="api-dashboard-overview"),
]
