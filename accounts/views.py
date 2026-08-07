from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth import views as auth_views
from django.shortcuts import get_object_or_404, redirect, render
from django.shortcuts import resolve_url
from django.utils import timezone

from .forms import AcceptInvitationForm, OrgAuthenticationForm
from .models import Invitation

User = get_user_model()


class LoginView(auth_views.LoginView):
    """Django's login, sending each kind of account to its own home.

    An account is either ours or a customer's — there is no third kind and
    nobody holds both roles. A superuser has no organization, so the customer
    app has literally nothing to show them; landing there and then hunting for
    a way across is friction with no upside.

    Only the *default* destination changes. An explicit `?next=` still wins,
    which is what makes a bookmarked deep link work after a session expires.
    """

    template_name = "accounts/login.html"
    authentication_form = OrgAuthenticationForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        if self.request.user.is_superuser:
            return resolve_url("mothership:clients")
        return super().get_default_redirect_url()


# Logout is Django's own view, wired in urls.py — only login and the
# invite-acceptance flow need custom handling.


def accept_invitation(request, token):
    """Set a password against an emailed invitation and log straight in.

    The token is the only credential, so an unusable one (already accepted,
    or past its expiry) must not reveal anything about the invitation — it
    renders the same dead-end page either way.
    """
    invitation = get_object_or_404(Invitation, token=token)
    if not invitation.is_usable or not invitation.organization.is_active:
        return render(request, "accounts/invitation_invalid.html", status=410)

    if request.method == "POST":
        form = AcceptInvitationForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=invitation.email,
                email=invitation.email,
                password=form.cleaned_data["password2"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                organization=invitation.organization,
                is_org_admin=invitation.as_org_admin,
            )
            invitation.accepted_at = timezone.now()
            # updated_at must be listed explicitly: auto_now is skipped for
            # fields absent from update_fields, silently.
            invitation.save(update_fields=["accepted_at", "updated_at"])
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("core:overview")
    else:
        form = AcceptInvitationForm(
            initial={"first_name": invitation.first_name, "last_name": invitation.last_name}
        )

    return render(
        request, "accounts/accept_invitation.html", {"form": form, "invitation": invitation}
    )
