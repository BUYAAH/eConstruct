"""Forms for the internal console.

Unlike `core.forms`, nothing here is scoped to the requesting user's
organization — Mothership is deliberately outside the tenancy boundary and
its only gate is `is_superuser`. That asymmetry is the whole point of keeping
these forms in a separate module from the customer-facing ones: a form that
takes no `organization` argument should never be importable into `core`.
"""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils.text import slugify

from core.models import Organization

User = get_user_model()

_TEXT = {"class": "form-control"}


class ClientForm(forms.ModelForm):
    """Rename an existing client.

    The slug is not editable: it's in the Mothership URL of every client
    page, and nothing about a customer's data depends on it, so letting it
    change would only break bookmarks.
    """

    class Meta:
        model = Organization
        fields = ["name"]
        labels = {"name": "Firmanavn"}
        widgets = {"name": forms.TextInput(attrs={**_TEXT, "autofocus": True})}


class ClientCreateForm(forms.Form):
    """Create a client and its first admin in one submit.

    Django's own *Add user* page can't do this — it offers username and
    password only, so organisation and `is_org_admin` need a second save
    (ROADMAP.md §7, friction 1). Worse, `username` must equal the email
    address or the user cannot log in at all (friction 2), which is invisible
    on that page and permanent here: `username` is set from `email`, never
    typed.

    Two ways in for the admin, because they serve different situations:
    *invitation* is the normal path and keeps D1 intact (nobody but the owner
    of an account ever knows its password); *password* is for handing a login
    to someone across a table, and for testing.
    """

    INVITE = "invite"
    PASSWORD = "password"
    ACCESS_CHOICES = [
        (INVITE, "Send invitation på e-mail — brugeren vælger selv adgangskode"),
        (PASSWORD, "Sæt en adgangskode nu"),
    ]

    name = forms.CharField(
        label="Firmanavn",
        max_length=200,
        widget=forms.TextInput(attrs={**_TEXT, "autofocus": True, "placeholder": "F.eks. Nordjysk Byg A/S"}),
    )
    admin_first_name = forms.CharField(
        label="Fornavn", max_length=150, widget=forms.TextInput(attrs=_TEXT)
    )
    admin_last_name = forms.CharField(
        label="Efternavn", max_length=150, required=False, widget=forms.TextInput(attrs=_TEXT)
    )
    admin_email = forms.EmailField(
        label="E-mail",
        widget=forms.EmailInput(attrs={**_TEXT, "placeholder": "navn@firma.dk"}),
    )
    access = forms.ChoiceField(
        label="Adgang",
        choices=ACCESS_CHOICES,
        initial=INVITE,
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
    )
    password = forms.CharField(
        label="Adgangskode",
        required=False,
        widget=forms.PasswordInput(attrs={**_TEXT, "autocomplete": "new-password"}),
    )
    seed_disciplines = forms.BooleanField(
        label="Opret standard faggrupper (Konstruktion, Brand, El, VVS, Kvalitet)",
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def clean_name(self):
        """Derive the slug here so a duplicate surfaces as a field error
        rather than an IntegrityError from Organization.slug's uniqueness."""
        name = self.cleaned_data["name"].strip()
        slug = slugify(name)
        if not slug:
            raise forms.ValidationError("Navnet skal indeholde mindst ét bogstav eller tal.")
        if Organization.objects.filter(slug=slug).exists():
            raise forms.ValidationError("Der findes allerede en kunde med dette navn.")
        self.slug = slug
        return name

    def clean_admin_email(self):
        email = self.cleaned_data["admin_email"].strip().lower()
        # Username *is* the email and is globally unique, so an address
        # belongs to exactly one organization. Checked here so it's a field
        # error at create time rather than an IntegrityError.
        if User.objects.filter(username=email).exists():
            raise forms.ValidationError("Der findes allerede en bruger med denne e-mail.")
        return email

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("access") == self.PASSWORD:
            password = cleaned.get("password") or ""
            if not password:
                self.add_error("password", "Vælg en adgangskode, eller send en invitation i stedet.")
            else:
                # Validate against the admin's own details, so "nordjyskbyg"
                # for nordjyskbyg.dk is caught the same way it would be if
                # they had chosen it themselves.
                probe = User(
                    username=cleaned.get("admin_email", ""),
                    email=cleaned.get("admin_email", ""),
                    first_name=cleaned.get("admin_first_name", ""),
                    last_name=cleaned.get("admin_last_name", ""),
                )
                try:
                    validate_password(password, probe)
                except forms.ValidationError as exc:
                    self.add_error("password", exc)
        return cleaned
