from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Role, User, UserRole


class UserRoleInline(admin.TabularInline):
    model = UserRole
    extra = 1


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserRoleInline]
    list_display = ("username", "email", "first_name", "last_name", "is_active", "is_staff")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Employee Info", {"fields": ("employee_code", "phone", "is_active_employee")}),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "assigned_at")
    list_filter = ("role",)
