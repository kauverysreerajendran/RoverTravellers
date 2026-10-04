from django.urls import path
from rest_framework.routers import DefaultRouter

from . import api_views as v

router = DefaultRouter()
router.register("mills", v.MillViewSet, basename="sales-mill")
router.register("contacts", v.MillContactViewSet, basename="sales-contact")
router.register("leads", v.LeadViewSet, basename="sales-lead")
router.register("trials", v.TrialViewSet, basename="sales-trial")
router.register("orders", v.SalesOrderViewSet, basename="sales-order")
router.register("stock-enquiries", v.StockEnquiryViewSet, basename="sales-stock-enquiry")
router.register("activities", v.ActivityViewSet, basename="sales-activity")
router.register("visits", v.VisitViewSet, basename="sales-visit")
router.register("reminders", v.ReminderViewSet, basename="sales-reminder")
router.register("notifications", v.NotificationViewSet, basename="sales-notification")

urlpatterns = [
    path("auth/login/", v.LoginView.as_view(), name="sales-login"),
    path("auth/logout/", v.LogoutView.as_view(), name="sales-logout"),
    path("auth/me/", v.MeView.as_view(), name="sales-me"),
    path("masters/", v.MastersView.as_view(), name="sales-masters"),
    path("users/", v.SalesUsersView.as_view(), name="sales-users"),
    path("stock-check/", v.StockCheckView.as_view(), name="sales-stock-check"),
    path("stock-check/options/", v.StockCheckOptionsView.as_view(), name="sales-stock-check-options"),
    path("dashboard/", v.DashboardView.as_view(), name="sales-dashboard"),
    path("today-plan/", v.TodayPlanView.as_view(), name="sales-today-plan"),
    path("search/", v.SearchView.as_view(), name="sales-search"),
    path("monitoring/", v.MonitoringView.as_view(), name="sales-monitoring"),
] + router.urls
