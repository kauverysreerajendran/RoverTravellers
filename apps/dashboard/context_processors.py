from django.utils import timezone


def nav_context(request):
    ctx = {
        "nav_now": timezone.localtime(),
        "app_name": "Rover Traveller",
    }
    if getattr(request, "user", None) and request.user.is_authenticated:
        from apps.rolling.models import RollingBatch

        ctx["notification_count"] = RollingBatch.objects.filter(status="In Progress").count()
    return ctx
