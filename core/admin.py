from django import forms
from django.contrib import admin

from .models import Discipline, Drawing, Note, Organization


class DisciplineAdminForm(forms.ModelForm):
    class Meta:
        model = Discipline
        fields = "__all__"
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class DisciplineInline(admin.TabularInline):
    model = Discipline
    form = DisciplineAdminForm
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [DisciplineInline]


@admin.register(Discipline)
class DisciplineAdmin(admin.ModelAdmin):
    form = DisciplineAdminForm
    list_display = ("name", "organization", "color", "sort_order")
    list_filter = ("organization",)


@admin.register(Drawing)
class DrawingAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "page_count", "uploaded_by", "created_at")
    list_filter = ("organization",)
    search_fields = ("name",)


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("drawing", "page_number", "discipline", "author", "created_at")
    list_filter = ("discipline__organization",)
    search_fields = ("text",)
