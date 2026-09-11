from django import forms
from django.contrib.auth.forms import AuthenticationForm


class RoverLoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control login-input", "placeholder": "Enter your email or username", "autofocus": True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control login-input", "placeholder": "Enter your password"})
    )
    remember_me = forms.BooleanField(required=False, initial=True)


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "you@company.com"}))


class ResetPasswordForm(forms.Form):
    new_password1 = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))
    new_password2 = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_password1") != cleaned.get("new_password2"):
            raise forms.ValidationError("Passwords do not match.")
        return cleaned
