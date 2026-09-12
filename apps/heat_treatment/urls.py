from django.urls import path

from apps.production.process_views import LegacyListRedirectView

from . import views

app_name = "heat_treatment"

urlpatterns = [
    # Canonical Main Table now lives at /process/heat_treatment/main/ - this
    # legacy path redirects so existing links keep working.
    path("", LegacyListRedirectView.as_view(process_slug="heat_treatment"), name="list"),
    path("create/", views.HeatTreatmentCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.HeatTreatmentDetailView.as_view(), name="detail"),
    path("<uuid:pk>/complete/", views.HeatTreatmentCompleteView.as_view(), name="complete"),
    # The furnace load: its page, its printable label and its QR.
    path("batches/<str:batch_no>/", views.HeatBatchDetailView.as_view(), name="batch_detail"),
    path("batches/<str:batch_no>/label/", views.HeatBatchLabelView.as_view(), name="batch_label"),
    path("batches/<str:batch_no>/qr.svg", views.HeatBatchQrView.as_view(), name="batch_qr"),
]
