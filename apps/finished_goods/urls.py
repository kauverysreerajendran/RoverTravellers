from django.urls import path

from apps.production.process_views import LegacyListRedirectView

from . import views

app_name = "finished_goods"

urlpatterns = [
    # Canonical Main Table now lives at /process/finished_goods/main/ - this
    # legacy path redirects so existing links keep working.
    path("", LegacyListRedirectView.as_view(process_slug="finished_goods"), name="list"),
    path("receive/", views.FinishedGoodsReceiveView.as_view(), name="receive"),
    path("<uuid:pk>/", views.FinishedGoodsDetailView.as_view(), name="detail"),
    path("<uuid:pk>/approve/", views.FinishedGoodsApproveView.as_view(), name="approve"),
    path("<uuid:pk>/reject/", views.FinishedGoodsRejectView.as_view(), name="reject"),
    path("<uuid:pk>/hold/", views.FinishedGoodsHoldView.as_view(), name="hold"),
    path(
        "<uuid:pk>/remove-from-rack/",
        views.FinishedGoodsRemoveFromRackView.as_view(),
        name="remove_from_rack",
    ),
]
