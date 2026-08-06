import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    organization = models.ForeignKey(
        "core.Organization", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    is_org_admin = models.BooleanField(
        default=False, verbose_name="organization admin"
    )

    def __str__(self):
        return self.get_full_name() or self.username


def _make_token():
    return secrets.token_urlsafe(32)


class Invitation(models.Model):
    """An emailed invite to join one organization.

    Users never self-register: an org admin invites an address, and the
    invitee sets their own password through the link. The token is the
    credential, so it's generated with `secrets` and single-use — accepting
    stamps `accepted_at` and creates the User.
    """

    EXPIRY_DAYS = 14

    organization = models.ForeignKey(
        "core.Organization", on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    # Whether the invitee becomes an admin of the inviting organization.
    as_org_admin = models.BooleanField(default=False)

    token = models.CharField(max_length=64, unique=True, default=_make_token, editable=False)
    invited_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One live invite per address per organization; accepted ones are
            # kept as history and don't block a re-invite.
            models.UniqueConstraint(
                fields=["organization", "email"],
                condition=models.Q(accepted_at__isnull=True),
                name="one_open_invitation_per_email_per_org",
            ),
        ]

    def __str__(self):
        return f"{self.email} -> {self.organization}"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=self.EXPIRY_DAYS)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self):
        return self.accepted_at is None and not self.is_expired
