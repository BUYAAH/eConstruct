from django import forms

from .models import Layer, Note


class LayerForm(forms.ModelForm):
    class Meta:
        model = Layer
        fields = ["name", "color", "sort_order"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Lagnavn"}),
            "color": forms.TextInput(attrs={"type": "color", "class": "form-control form-control-color form-control-sm"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "width: 5rem;"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sort_order"].required = False

    def clean_sort_order(self):
        value = self.cleaned_data.get("sort_order")
        return 0 if value is None else value


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ["layer", "text", "photo"]
        widgets = {
            "layer": forms.Select(attrs={"class": "form-select"}),
            "text": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Skriv din note…"}
            ),
            "photo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
        }

    def __init__(self, company, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["layer"].queryset = company.layers.all()
