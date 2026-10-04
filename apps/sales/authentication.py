"""Token auth for the mobile app, layered on the existing Django users.

The web app keeps session authentication; the phone gets a DRF token from
the same username/password (apps.accounts User). Tokens expire after
SALES_TOKEN_TTL_HOURS (default 12) so a lost phone does not stay signed in
forever; the app then sees 401 and returns to the login screen."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication


def token_ttl():
    return timedelta(hours=int(getattr(settings, "SALES_TOKEN_TTL_HOURS", 12)))


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token.created < timezone.now() - token_ttl():
            token.delete()
            raise exceptions.AuthenticationFailed("Session expired. Please sign in again.")
        return user, token
