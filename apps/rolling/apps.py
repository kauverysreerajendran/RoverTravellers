from django.apps import AppConfig


class RollingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.rolling"
    label = "rolling"
    verbose_name = "Rolling"
