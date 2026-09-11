from django.urls import path

from apps.production.process_views import LegacyListRedirectView

from . import views

app_name = "forming"

urlpatterns = [
    # Canonical Main Table now lives at /process/forming/main/ - this
    # legacy path redirects so existing links keep working.
    path("", LegacyListRedirectView.as_view(process_slug="forming"), name="list"),
    path("create/", views.FormingCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.FormingDetailView.as_view(), name="detail"),
    path("<uuid:pk>/complete/", views.FormingCompleteView.as_view(), name="complete"),
]
