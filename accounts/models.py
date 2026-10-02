import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.utils import timezone

from core.base import BaseModel


def normalize_email(email):
    """Lower-case the whole address, not just the domain.

    Django's own `normalize_email` lower-cases the domain only, because the
    local part is case-sensitive per RFC 5321. No mail provider in use here
    honours that, and the address is now the login credential, so
    `Anna@byg.dk` and `anna@byg.dk` have to be one account rather than two
    that each own half of someone's history.
    """
    return (email or "").strip().lower()


class UserManager(DjangoUserManager):
    """Creates users keyed on email instead of username.

    Django's signature is `create_user(username, email, password)`. With
    `USERNAME_FIELD = "email"` there is no username left to pass, so it
    collapses to a single identifier — which is the point of the change: the
    old shape let `createsuperuser` and Django admin invent a username
    unrelated to the email, and that is how two accounts ended up sharing an
    address.
    """

    def _create_user(self, email, password=None, **extra_fields):
        email = normalize_email(email)
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """The email address *is* the account.

    `username` is removed rather than kept in sync with the email. Holding
    both meant the "username is the email" rule lived in two form validators,
    which `createsuperuser` and Django admin's add-user page walked straight
    past — so the database happily held two accounts on one address, while the
    login page, which is labelled E-mail, could log in neither of them.
    """

    username = None
    email = models.EmailField("email address", unique=True)
    organization = models.ForeignKey(
        "core.Organization", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    is_org_admin = models.BooleanField(
        default=False, verbose_name="organization admin"
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def save(self, *args, **kwargs):
        # Last line of defence. The forms normalise too, but a shell session,
        # a fixture or a future view bypasses those, and one stray capital is
        # a duplicate account that `unique=True` cannot see.
        self.email = normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.email


def _make_token():
    return secrets.token_urlsafe(32)


class Invitation(BaseModel):
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
