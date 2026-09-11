from django.urls import path

from apps.production.process_views import LegacyListRedirectView

from . import views

app_name = "finishing"

urlpatterns = [
    # Canonical Main Table now lives at /process/finishing/main/ - this
    # legacy path redirects so existing links keep working.
    path("", LegacyListRedirectView.as_view(process_slug="finishing"), name="list"),
    path("create/", views.FinishingCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.FinishingDetailView.as_view(), name="detail"),
    path("<uuid:pk>/complete/", views.FinishingCompleteView.as_view(), name="complete"),
]
