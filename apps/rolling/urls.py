from django.urls import path

from apps.production.process_views import LegacyListRedirectView

from . import views

app_name = "rolling"

urlpatterns = [
    # Canonical Main Table now lives at /process/rolling/main/ - this
    # legacy path redirects so existing links keep working.
    path("", LegacyListRedirectView.as_view(process_slug="rolling"), name="list"),
    path("create/", views.RollingCreateView.as_view(), name="create"),
    path("<int:pk>/", views.RollingDetailView.as_view(), name="detail"),
    path("<int:pk>/complete/", views.RollingCompleteView.as_view(), name="complete"),
]
