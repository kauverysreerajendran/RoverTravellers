from rest_framework.permissions import SAFE_METHODS, BasePermission

from . import services


class IsSalesUser(BasePermission):
    message = "This account does not have access to the Sales app."

    def has_permission(self, request, view):
        return services.is_sales_user(request.user)


class IsSalesAdmin(BasePermission):
    message = "Admin only."

    def has_permission(self, request, view):
        return services.is_sales_admin(request.user)


class AdminWritesOthersRead(BasePermission):
    """Reads for every sales user; writes for Admin only."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return services.is_sales_user(request.user)
        return services.is_sales_admin(request.user)
