from django import forms

from .models import Discipline, Drawing, Note


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


class DrawingUploadForm(forms.ModelForm):
    class Meta:
        model = Drawing
        fields = ["name", "file"]
        labels = {"name": "Navn", "file": "PDF-fil"}
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Tomt felt = filnavnet"}
            ),
            "file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".pdf"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].required = False

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith(".pdf"):
            raise forms.ValidationError("Kun PDF-filer kan bruges som tegning.")
        return uploaded


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["discipline", "text", "photo"]
        widgets = {
            "discipline": forms.Select(attrs={"class": "form-select"}),
            "text": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Skriv din note…"}
            ),
            "photo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
        }

    def __init__(self, organization, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["discipline"].queryset = organization.disciplines.all()
