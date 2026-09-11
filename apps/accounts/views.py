from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views import View

from .forms import ForgotPasswordForm, ResetPasswordForm, RoverLoginForm

User = get_user_model()


class RoverLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = RoverLoginForm
    # Always render the login screen when this URL is visited directly,
    # even for an already-authenticated session, instead of bouncing to
    # the dashboard. Submitting valid credentials still redirects normally
    # via get_success_url()/LOGIN_REDIRECT_URL.
    redirect_authenticated_user = False

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(0)
        return response

    def form_invalid(self, form):
        messages.error(self.request, "Invalid credentials. Please check your username and password.")
        return super().form_invalid(form)


def logout_view(request):
    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect("accounts:login")


class ForgotPasswordView(View):
    template_name = "accounts/forgot_password.html"

    def get(self, request):
        return render(request, self.template_name, {"form": ForgotPasswordForm()})

    def post(self, request):
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user = User.objects.filter(email__iexact=email).first()
            if user:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_link = request.build_absolute_uri(
                    reverse_lazy("accounts:reset_password", kwargs={"uidb64": uid, "token": token})
                )
                messages.success(
                    request,
                    f"A password reset link has been generated (dev mode, no email sent): {reset_link}",
                )
            else:
                messages.success(request, "If an account exists for that email, a reset link has been sent.")
            return redirect("accounts:login")
        return render(request, self.template_name, {"form": form})


class ResetPasswordView(View):
    template_name = "accounts/reset_password.html"

    def _get_user(self, uidb64):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            return User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None

    def get(self, request, uidb64, token):
        user = self._get_user(uidb64)
        if user is None or not default_token_generator.check_token(user, token):
            messages.error(request, "This password reset link is invalid or has expired.")
            return redirect("accounts:forgot_password")
        return render(request, self.template_name, {"form": ResetPasswordForm(), "uidb64": uidb64, "token": token})

    def post(self, request, uidb64, token):
        user = self._get_user(uidb64)
        if user is None or not default_token_generator.check_token(user, token):
            messages.error(request, "This password reset link is invalid or has expired.")
            return redirect("accounts:forgot_password")
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data["new_password1"])
            user.save()
            messages.success(request, "Password has been reset. Please sign in.")
            return redirect("accounts:login")
        return render(request, self.template_name, {"form": form, "uidb64": uidb64, "token": token})
