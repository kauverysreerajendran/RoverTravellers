import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("create", "Create"),
        ("update", "Update"),
        ("complete", "Complete"),
        ("cancel", "Cancel"),
        ("approve", "Approve"),
        ("reject", "Reject"),
        ("transfer", "Transfer"),
        ("adjust", "Adjust"),
        ("login", "Login"),
        ("logout", "Logout"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    entity_type = models.CharField(max_length=100, db_index=True)
    entity_id = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self):
        return f"{self.action} {self.entity_type} {self.entity_id}"


def log_action(user, action, instance, description="", metadata=None, ip_address=None):
    return AuditLog.objects.create(
        user=user if user and getattr(user, "is_authenticated", False) else None,
        action=action,
        entity_type=instance.__class__.__name__,
        entity_id=str(getattr(instance, "pk", "")),
        description=description,
        metadata=metadata or {},
        ip_address=ip_address,
    )
