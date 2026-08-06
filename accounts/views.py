from django.contrib.auth import get_user_model, login as auth_login
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import AcceptInvitationForm
from .models import Invitation

User = get_user_model()

# Login/logout are Django's own class-based views, wired in urls.py — only
# the invite-acceptance flow needs custom handling.


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
            invitation.save(update_fields=["accepted_at"])
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("core:overview")
    else:
        form = AcceptInvitationForm(
            initial={"first_name": invitation.first_name, "last_name": invitation.last_name}
        )

    return render(
        request, "accounts/accept_invitation.html", {"form": form, "invitation": invitation}
    )
