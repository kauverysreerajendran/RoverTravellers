from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

from .models import AuditLog


class AuditLogListView(LoginRequiredMixin, ListView):
    model = AuditLog
    template_name = "reports/audit_log_list.html"
    context_object_name = "logs"
    paginate_by = 30

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user").all()
        action = self.request.GET.get("action")
        entity_type = self.request.GET.get("entity_type")
        if action:
            qs = qs.filter(action=action)
        if entity_type:
            qs = qs.filter(entity_type__icontains=entity_type)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action_choices"] = AuditLog.ACTION_CHOICES
        ctx["page_title"] = "Audit Logs"
        return ctx
