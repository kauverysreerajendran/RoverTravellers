from django.utils import timezone


def nav_context(request):
    ctx = {
        "nav_now": timezone.localtime(),
        "app_name": "Rover Traveller",
    }
    if getattr(request, "user", None) and request.user.is_authenticated:
        from apps.inventory.models import FinishedGoodsStock

        ctx["pending_qc_count"] = FinishedGoodsStock.objects.filter(
            quality_approved=False, status="hold"
        ).count()
    return ctx
