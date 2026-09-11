import uuid

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base adding UUID id, audit timestamps and audit users."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        abstract = True


class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class MasterDataModel(TimeStampedModel):
    """Abstract base for master data with soft-delete via is_active flag."""

    is_active = models.BooleanField(default=True, db_index=True)

    objects = models.Manager()
    active = ActiveManager()

    class Meta:
        abstract = True


def generate_business_number(prefix: str, model_cls, field_name: str = "number") -> str:
    """Generate a readable business number like RM-2026-00001."""
    from django.utils import timezone

    year = timezone.now().year
    scoped_prefix = f"{prefix}-{year}-"
    last = (
        model_cls.objects.filter(**{f"{field_name}__startswith": scoped_prefix})
        .order_by(f"-{field_name}")
        .first()
    )
    if last:
        last_value = getattr(last, field_name)
        last_seq = int(last_value.split("-")[-1])
        next_seq = last_seq + 1
    else:
        next_seq = 1
    return f"{scoped_prefix}{next_seq:05d}"
