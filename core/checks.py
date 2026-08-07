"""Deployment checks that Django's own `check --deploy` cannot know about.

These run on every `manage.py` command, so a misconfiguration surfaces when
deploying rather than the first time a client can't use their invitation.
"""

from django.conf import settings
from django.core.checks import Error, register


@register(deploy=True)
def site_url_is_set(app_configs, **kwargs):
    """SITE_URL must not still be localhost on a deployed instance.

    Invitation links are built from it, and they are the only way a client
    ever gets an account (D1). Left at the default they point at the
    developer's own machine — the invite sends fine, the page looks fine, and
    the recipient gets a connection error with nothing to explain it. That is
    a bad failure to discover from a customer, so it is an Error rather than a
    Warning: with DEBUG off there is no legitimate reason for it.
    """
    if settings.DEBUG:
        return []
    host = settings.SITE_URL.lower()
    if "localhost" in host or "127.0.0.1" in host:
        return [
            Error(
                f"SITE_URL is still {settings.SITE_URL!r} with DEBUG off.",
                hint=(
                    "Set SITE_URL in .env to the deployed address, e.g. "
                    "https://yourname.pythonanywhere.com — invitation links "
                    "are built from it and would otherwise point at localhost."
                ),
                id="core.E001",
            )
        ]
    return []
