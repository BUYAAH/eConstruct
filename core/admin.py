from django import forms
from django.contrib import admin

from .models import Company, Document, FolderLink, Layer, Note


class LayerAdminForm(forms.ModelForm):
    class Meta:
        model = Layer
        fields = "__all__"
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class LayerInline(admin.TabularInline):
    model = Layer
    form = LayerAdminForm
    extra = 0


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "ms_tenant_id", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "ms_tenant_id")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [LayerInline]


@admin.register(Layer)
class LayerAdmin(admin.ModelAdmin):
    form = LayerAdminForm
    list_display = ("name", "company", "color", "sort_order")
    list_filter = ("company",)


@admin.register(FolderLink)
class FolderLinkAdmin(admin.ModelAdmin):
    list_display = ("display_path", "company", "added_by", "created_at")
    list_filter = ("company",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "folder_link", "is_missing", "created_at")
    list_filter = ("company", "is_missing")
    search_fields = ("name",)


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("document", "page_number", "layer", "author", "created_at")
    list_filter = ("layer__company",)
    search_fields = ("text",)
