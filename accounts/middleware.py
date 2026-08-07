"""Middleware that decides who belongs where.

Two separate rules, kept as two classes because they answer different
questions: whether a customer may still be here at all, and which half of the
app an account belongs in.

Request-time enforcement of a suspended client.

Sessions last 30 days and slide forward on every request (settings.py), which
is right for a field worker on a scaffold and wrong for a customer we have
just switched off: checking `Organization.is_active` only at login would leave
a suspended client working for up to a month. So it is checked per request and
the session is ended the moment it fails.

Costs one indexed lookup per authenticated request. That is the price of the
suspension being immediate rather than eventual, and on a table with one row
per customer it is not a real cost.
"""

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from core.models import Organization

SUSPENDED_MESSAGE = (
    "Din organisations adgang er sat på pause. Kontakt din leverandør."
)


class SuspendedOrganizationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        # Superusers run Mothership and have no organization of their own;
        # an unauthenticated request has nothing to check.
        if (
            user is not None
            and user.is_authenticated
            and not user.is_superuser
            and user.organization_id is not None
            and Organization.objects.filter(
                pk=user.organization_id, is_active=False
            ).exists()
        ):
            login_url = reverse("accounts:login")
            # Never bounce the login page itself back to the login page.
            if request.path != login_url:
                logout(request)
                messages.error(request, SUSPENDED_MESSAGE)
                return redirect(login_url)

        return self.get_response(request)


class SuperuserHomeMiddleware:
    """Keep superusers out of the customer app.

    An account is either ours or a customer's. A superuser belongs to no
    organization, so every page in `core` is scoped to nothing and renders
    empty — there is nothing there for them to look at, and a screen of
    zeros invites the question of whether something is broken.

    Enforced here rather than on the landing page alone, so the rule holds
    for a stale bookmark and a hand-typed URL too. Only `core` is redirected:
    login, logout, invitation acceptance and Django admin are all still
    reachable, and Mothership itself is untouched.

    To look inside the customer app while developing, use a seeded account
    (`manage.py seed_demo` prints them) rather than the superuser.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """process_view, not __call__: `resolver_match` is what identifies the
        customer app, and it isn't set until after URL resolution."""
        match = request.resolver_match
        user = getattr(request, "user", None)
        if (
            match is not None
            and match.app_name == "core"
            and user is not None
            and user.is_authenticated
            and user.is_superuser
        ):
            return redirect("mothership:clients")
        return None
