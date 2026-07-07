"""MSAL helpers: app factory, encrypted per-user token cache, silent token refresh."""

import msal
from cryptography.fernet import Fernet
from django.conf import settings

from .models import MsToken


class ReauthRequired(Exception):
    """Raised when a Graph token can't be acquired silently; user must log in again."""


def _fernet():
    return Fernet(settings.TOKEN_ENC_KEY.encode())


def build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        settings.MS_CLIENT_ID,
        authority=settings.MS_AUTHORITY,
        client_credential=settings.MS_CLIENT_SECRET,
        token_cache=cache,
    )


def load_cache(user):
    cache = msal.SerializableTokenCache()
    token_row = MsToken.objects.filter(user=user).first()
    if token_row:
        cache.deserialize(_fernet().decrypt(bytes(token_row.blob)).decode())
    return cache


def save_cache(user, cache):
    if cache.has_state_changed:
        blob = _fernet().encrypt(cache.serialize().encode())
        MsToken.objects.update_or_create(user=user, defaults={"blob": blob})


def get_graph_token(user):
    """Return a valid Graph access token for the user, refreshing silently if needed.

    Raises ReauthRequired when the refresh token is gone/expired/revoked.
    """
    cache = load_cache(user)
    app = build_msal_app(cache)
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(settings.GRAPH_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            save_cache(user, cache)
            return result["access_token"]
    raise ReauthRequired()
