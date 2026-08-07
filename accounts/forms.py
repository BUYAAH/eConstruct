from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from .models import Invitation

User = get_user_model()

_TEXT = {"class": "form-control"}


class OrgAuthenticationForm(AuthenticationForm):
    """Login form, styled for the dashboard shell and labelled in Danish."""

    username = forms.CharField(
        label="E-mail",
        widget=forms.TextInput(attrs={**_TEXT, "autofocus": True, "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="Adgangskode",
        widget=forms.PasswordInput(attrs={**_TEXT, "autocomplete": "current-password"}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Forkert e-mail eller adgangskode.",
        "inactive": "Din konto er deaktiveret. Kontakt din administrator.",
        "suspended": "Din organisations adgang er sat på pause. Kontakt din leverandør.",
    }

    def confirm_login_allowed(self, user):
        """Refuse a user whose organization has been suspended from Mothership.

        The deliberate wording difference from "inactive": a deactivated user
        is their own admin's doing and their admin can undo it; a suspended
        organization is ours, and their admin cannot.

        This is the front door only. An already-open session is ended by
        accounts.middleware.SuspendedOrganizationMiddleware — sessions last 30
        days, so this check alone would not stop anyone already logged in.
        """
        super().confirm_login_allowed(user)
        if (
            not user.is_superuser
            and user.organization_id is not None
            and not user.organization.is_active
        ):
            raise forms.ValidationError(
                self.error_messages["suspended"], code="suspended"
            )


class InvitationForm(forms.ModelForm):
    """An org admin invites one address. The organization is never a form
    field — it's taken from the inviting user, so an admin cannot invite
    into an organization they don't belong to."""

    class Meta:
        model = Invitation
        fields = ["email", "first_name", "last_name", "as_org_admin"]
        labels = {
            "email": "E-mail",
            "first_name": "Fornavn",
            "last_name": "Efternavn",
            "as_org_admin": "Giv administratoradgang",
        }
        widgets = {
            "email": forms.EmailInput(attrs={**_TEXT, "placeholder": "navn@firma.dk"}),
            "first_name": forms.TextInput(attrs=_TEXT),
            "last_name": forms.TextInput(attrs=_TEXT),
            "as_org_admin": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        # Usernames are the email address and globally unique, so an address
        # can belong to only one organization. Checking here turns what would
        # be an IntegrityError on accept into a form error on invite.
        if User.objects.filter(username=email).exists():
            raise forms.ValidationError("Der findes allerede en bruger med denne e-mail.")
        open_invite = Invitation.objects.filter(
            organization=self.organization, email=email, accepted_at__isnull=True
        ).exists()
        if open_invite:
            raise forms.ValidationError("Der er allerede sendt en invitation til denne e-mail.")
        return email


class AcceptInvitationForm(forms.Form):
    """Where an invitee sets their own password. Name fields are prefilled
    from the invitation but stay editable — the admin typed them, not the
    person they belong to."""

    first_name = forms.CharField(label="Fornavn", max_length=150, widget=forms.TextInput(attrs=_TEXT))
    last_name = forms.CharField(
        label="Efternavn", max_length=150, required=False, widget=forms.TextInput(attrs=_TEXT)
    )
    password1 = forms.CharField(
        label="Vælg adgangskode",
        widget=forms.PasswordInput(attrs={**_TEXT, "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Gentag adgangskode",
        widget=forms.PasswordInput(attrs={**_TEXT, "autocomplete": "new-password"}),
    )

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data["password2"]
        if p1 and p1 != p2:
            raise forms.ValidationError("De to adgangskoder er ikke ens.")
        validate_password(p2)
        return p2
