"""Outgoing mail. One message so far: the invitation."""

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

SUBJECT = "Du er inviteret til {brand}"

BODY = """\
Hej{name}

{inviter} har inviteret dig til at bruge {brand} for {organization}.

Følg linket her for at vælge en adgangskode og komme i gang:

{link}

Linket udløber om {days} dage.
"""


def invitation_link(invitation):
    """The absolute accept URL. Uses SITE_URL because the email is built with
    no request in hand, and Mothership shows the same link to support a client
    whose mail never arrived."""
    path = reverse("accounts:accept_invitation", args=[invitation.token])
    return f"{settings.SITE_URL.rstrip('/')}{path}"


def send_invitation(invitation):
    """Email the accept link.

    Failures are not swallowed — an invite that silently doesn't arrive is
    worse than a visible error, since the admin would have no way to tell.
    """
    link = invitation_link(invitation)
    name = f" {invitation.first_name}," if invitation.first_name else ","

    send_mail(
        subject=SUBJECT.format(brand=settings.BRAND_NAME),
        message=BODY.format(
            name=name,
            inviter=invitation.invited_by or "En administrator",
            brand=settings.BRAND_NAME,
            organization=invitation.organization.name,
            link=link,
            days=invitation.EXPIRY_DAYS,
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[invitation.email],
        fail_silently=False,
    )
