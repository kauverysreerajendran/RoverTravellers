from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.heat_treatment import views as heat_treatment_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="dashboard:overview", permanent=False)),
    path("accounts/", include("apps.accounts.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("master-data/", include("apps.master_data.urls")),
    path("masters/", include("apps.masters.urls")),
    path("production/", include("apps.production.urls")),
    # Dynamic per-process Main Table / Complete Table screens. One route
    # pair serves every process in apps.production.process_registry.
    path("process/", include("apps.production.process_urls")),
    path("rolling/", include("apps.rolling.urls")),
    path("forming/", include("apps.forming.urls")),
    path("heat-treatment/", include("apps.heat_treatment.urls")),
    # What a printed QR label resolves to. Top-level and short, because it
    # is typed into a phone camera, not clicked.
    path("scan/<str:token>/", heat_treatment_views.scan, name="scan"),
    path("scan/<str:token>/qr.svg", heat_treatment_views.scan_qr, name="scan_qr"),
    path("finishing/", include("apps.finishing.urls")),
    path("finished-goods/", include("apps.finished_goods.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("reports/", include("apps.reports.urls")),
    path("audit/", include("apps.audit.urls")),
    path("api/", include("apps.accounts.api_urls")),
    path("api/", include("apps.master_data.api_urls")),
    path("api/", include("apps.masters.api_urls")),
    path("api/", include("apps.production.api_urls")),
    path("api/", include("apps.rolling.api_urls")),
    path("api/", include("apps.forming.api_urls")),
    path("api/", include("apps.heat_treatment.api_urls")),
    path("api/", include("apps.finishing.api_urls")),
    path("api/", include("apps.finished_goods.api_urls")),
    path("api/", include("apps.inventory.api_urls")),
    path("api/", include("apps.reports.api_urls")),
    path("api/", include("apps.dashboard.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
