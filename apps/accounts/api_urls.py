from django.urls import path
from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register("users", api_views.UserViewSet, basename="api-user")
router.register("roles", api_views.RoleViewSet, basename="api-role")

urlpatterns = [
    path("auth/login/", api_views.ApiLoginView.as_view(), name="api-login"),
    path("auth/logout/", api_views.ApiLogoutView.as_view(), name="api-logout"),
    path("auth/me/", api_views.CurrentUserView.as_view(), name="api-me"),
] + router.urls
