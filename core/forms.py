"""Forms.

Every form that references another model takes the organization (or the
project) and narrows its querysets to it. Doing this in `__init__` rather
than at the view layer means a crafted POST cannot reach across tenants
even if a view forgets to check — the field simply won't validate.
"""

from django import forms
from django.utils.text import slugify

from .models import Contractor, Discipline, Drawing, Project, Registration

_TEXT = {"class": "form-control"}
_SELECT = {"class": "form-select"}


class DisciplineForm(forms.ModelForm):
    class Meta:
        model = Discipline
        fields = ["name", "color", "sort_order"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Faggruppe"}),
            "color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color form-control-sm"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width: 5rem;"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sort_order"].required = False

    def clean_sort_order(self):
        value = self.cleaned_data.get("sort_order")
        return 0 if value is None else value


class ContractorForm(forms.ModelForm):
    class Meta:
        model = Contractor
        fields = ["name", "contact_name", "contact_email", "contact_phone"]
        labels = {
            "name": "Firmanavn",
            "contact_name": "Kontaktperson",
            "contact_email": "E-mail",
            "contact_phone": "Telefon",
        }
        widgets = {
            "name": forms.TextInput(attrs={**_TEXT, "placeholder": "F.eks. Nord El A/S"}),
            "contact_name": forms.TextInput(attrs=_TEXT),
            "contact_email": forms.EmailInput(attrs=_TEXT),
            "contact_phone": forms.TextInput(attrs=_TEXT),
        }


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "case_no", "address", "status", "manager", "members", "contractors"]
        labels = {
            "name": "Projektnavn",
            "case_no": "Sagsnr.",
            "address": "Adresse",
            "status": "Status",
            "manager": "Projektleder",
            "members": "Deltagere",
            "contractors": "Firmaer",
        }
        widgets = {
            "name": forms.TextInput(attrs=_TEXT),
            "case_no": forms.TextInput(attrs=_TEXT),
            "address": forms.TextInput(attrs=_TEXT),
            "status": forms.Select(attrs=_SELECT),
            "manager": forms.Select(attrs=_SELECT),
            "members": forms.SelectMultiple(attrs={**_SELECT, "size": 8}),
            "contractors": forms.SelectMultiple(attrs={**_SELECT, "size": 6}),
        }

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields["manager"].queryset = organization.users.filter(is_active=True)
        self.fields["members"].queryset = organization.users.filter(is_active=True)
        self.fields["contractors"].queryset = organization.contractors.filter(is_active=True)
        for name in ("case_no", "address", "manager", "members", "contractors"):
            self.fields[name].required = False

    def clean_name(self):
        """Derive the slug here so a duplicate name surfaces as a field error
        rather than an IntegrityError from the per-org unique constraint."""
        name = self.cleaned_data["name"].strip()
        slug = slugify(name)
        if not slug:
            raise forms.ValidationError("Navnet skal indeholde mindst ét bogstav eller tal.")
        clash = Project.objects.filter(organization=self.organization, slug=slug)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("Der findes allerede et projekt med dette navn.")
        self.instance.slug = slug
        return name


class DrawingUploadForm(forms.ModelForm):
    class Meta:
        model = Drawing
        fields = ["name", "file"]
        labels = {"name": "Navn", "file": "PDF-fil"}
        widgets = {
            "name": forms.TextInput(attrs={**_TEXT, "placeholder": "Tomt felt = filnavnet"}),
            "file": forms.ClearableFileInput(attrs={**_TEXT, "accept": ".pdf"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Kun PDF-filer kan bruges som tegning.")
        return uploaded


class RegistrationForm(forms.ModelForm):
    """Everything except the pin location, which comes from the tap on the
    drawing and is written by the view."""

    class Meta:
        model = Registration
        fields = [
            "subject", "description", "discipline",
            "assigned_contractor", "responsible", "deadline",
        ]
        labels = {
            "subject": "Emne",
            "description": "Beskrivelse",
            "discipline": "Faggruppe",
            "assigned_contractor": "Firma",
            "responsible": "Ansvarlig",
            "deadline": "Frist",
        }
        widgets = {
            "subject": forms.TextInput(
                attrs={**_TEXT, "placeholder": "F.eks. Revne i betonvæg ved akse D/4"}
            ),
            "description": forms.Textarea(
                attrs={**_TEXT, "rows": 3, "placeholder": "Uddybende beskrivelse (valgfri)"}
            ),
            "discipline": forms.Select(attrs=_SELECT),
            "assigned_contractor": forms.Select(attrs=_SELECT),
            "responsible": forms.Select(attrs=_SELECT),
            "deadline": forms.DateInput(attrs={**_TEXT, "type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, project, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        organization = project.organization
        self.fields["discipline"].queryset = organization.disciplines.all()
        # Only firms actually attached to this project — assigning work to a
        # contractor who isn't on the site is a data-entry error, not a feature.
        self.fields["assigned_contractor"].queryset = project.contractors.filter(is_active=True)
        self.fields["responsible"].queryset = project.members.filter(is_active=True)
        self.fields["responsible"].required = False
        self.fields["deadline"].required = False
        self.fields["description"].required = False


class PhotoUploadForm(forms.Form):
    """Separate from RegistrationForm so photos can be added to an existing
    registration without re-submitting the whole thing."""

    photo = forms.ImageField(
        label="Foto",
        widget=forms.ClearableFileInput(
            # capture= opens the camera directly on a phone, which is where
            # these are taken.
            attrs={"class": "form-control", "accept": "image/*", "capture": "environment"}
        ),
    )
