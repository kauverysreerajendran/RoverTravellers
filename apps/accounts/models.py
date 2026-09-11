from django.contrib.auth.models import AbstractUser
from django.db import models

ROLE_CHOICES = [
    ("super_admin", "Super Admin"),
    ("admin", "Admin"),
    ("production_manager", "Production Manager"),
    ("rolling_operator", "Rolling Operator"),
    ("forming_operator", "Forming Operator"),
    ("heat_treatment_operator", "Heat Treatment Operator"),
    ("finishing_operator", "Finishing Operator"),
    ("finished_goods_operator", "Finished Goods Operator"),
    ("quality_inspector", "Quality Inspector"),
    ("inventory_manager", "Inventory Manager"),
    ("viewer", "Viewer"),
]

# Roles allowed to complete / approve production transactions.
APPROVAL_ROLES = {
    "super_admin",
    "admin",
    "production_manager",
    "quality_inspector",
}

OPERATOR_ROLE_BY_STAGE = {
    "rolling": {"rolling_operator", "production_manager", "admin", "super_admin"},
    "forming": {"forming_operator", "production_manager", "admin", "super_admin"},
    "heat_treatment": {"heat_treatment_operator", "production_manager", "admin", "super_admin"},
    "finishing": {"finishing_operator", "production_manager", "admin", "super_admin"},
    "finished_goods": {"finished_goods_operator", "production_manager", "admin", "super_admin"},
}


class Role(models.Model):
    code = models.CharField(max_length=40, choices=ROLE_CHOICES, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    employee_code = models.CharField(max_length=30, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active_employee = models.BooleanField(default=True)
    roles = models.ManyToManyField(Role, through="UserRole", related_name="users", blank=True)

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def role_codes(self):
        return set(self.roles.values_list("code", flat=True))

    def has_role(self, *codes):
        return bool(self.role_codes.intersection(codes))

    def can_approve(self):
        return self.is_superuser or self.has_role(*APPROVAL_ROLES)

    def can_operate_stage(self, stage: str):
        allowed = OPERATOR_ROLE_BY_STAGE.get(stage, set())
        return self.is_superuser or self.has_role(*allowed)


class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "role")

    def __str__(self):
        return f"{self.user} - {self.role}"
