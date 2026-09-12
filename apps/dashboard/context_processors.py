from django.urls import reverse
from django.utils import timezone


def _process_nav(request):
    """Build the process menu from the process registry so every process
    automatically gets its Main Table / Complete Table submenus, and the
    active group + active submenu are resolved server-side (so a refresh
    or a direct URL always highlights correctly)."""
    from apps.production.process_registry import PROCESSES

    match = request.resolver_match
    namespace = getattr(match, "namespace", "") or ""
    url_name = getattr(match, "url_name", "") or ""
    active_slug = ""
    active_sub = ""

    if namespace == "process":
        active_slug = (match.kwargs or {}).get("process", "")
        active_sub = url_name if url_name in ("main", "complete") else ""
    elif namespace in {process.slug for process in PROCESSES}:
        # Drill-down screens (detail, initiate, per-record completion form)
        # belong to the process's Main Table branch.
        active_slug = namespace
        active_sub = "main"

    nav = []
    for process in PROCESSES:
        is_active = process.slug == active_slug
        nav.append(
            {
                "slug": process.slug,
                "label": process.label,
                "icon": process.icon,
                "is_active": is_active,
                "submenus": [
                    {
                        "key": "main",
                        "label": "Main Table",
                        "url": reverse("process:main", kwargs={"process": process.slug}),
                        "is_active": is_active and active_sub == "main",
                    },
                    {
                        "key": "complete",
                        "label": "Complete Table",
                        "url": reverse("process:complete", kwargs={"process": process.slug}),
                        "is_active": is_active and active_sub == "complete",
                    },
                ],
            }
        )
    return nav


def nav_context(request):
    ctx = {
        "nav_now": timezone.localtime(),
        "app_name": "Rover Traveller",
    }
    if getattr(request, "user", None) and request.user.is_authenticated:
        from apps.heat_treatment.barcode import site_base_url
        from apps.rolling.models import RollingBatch

        ctx["notification_count"] = RollingBatch.objects.filter(status="In Progress").count()
        ctx["process_nav"] = _process_nav(request)
        # Where a scanned label points. The Locate-me scanner compares what
        # the camera read against this, so a QR from somewhere else is
        # refused rather than followed.
        ctx["site_base_url"] = site_base_url(request)
    return ctx
