from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.RoverLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("forgot-password/", views.ForgotPasswordView.as_view(), name="forgot_password"),
    path("reset-password/<uidb64>/<token>/", views.ResetPasswordView.as_view(), name="reset_password"),
]
