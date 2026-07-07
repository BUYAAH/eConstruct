from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    company = models.ForeignKey(
        "core.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    is_company_admin = models.BooleanField(default=False)
    # Entra ID object id ("oid" claim); the stable identity for SSO matching.
    ms_object_id = models.CharField(max_length=64, unique=True, null=True, blank=True)

    def __str__(self):
        return self.get_full_name() or self.username


class MsToken(models.Model):
    """Fernet-encrypted MSAL token cache blob, one per user."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="ms_token")
    blob = models.BinaryField()
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"MSAL cache for {self.user}"
