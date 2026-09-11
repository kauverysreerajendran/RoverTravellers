from django.apps import AppConfig


class ProductionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.production"
    label = "production"
    verbose_name = "Production"
