from django import forms
from django.contrib import admin

from .models import (
    Contractor, Discipline, Drawing, Organization, Project, Registration,
    RegistrationPhoto,
)


class DisciplineAdminForm(forms.ModelForm):
    class Meta:
        model = Discipline
        fields = "__all__"
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class DisciplineInline(admin.TabularInline):
    model = Discipline
    form = DisciplineAdminForm
    extra = 0


class ContractorInline(admin.TabularInline):
    model = Contractor
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [DisciplineInline, ContractorInline]


@admin.register(Discipline)
class DisciplineAdmin(admin.ModelAdmin):
    form = DisciplineAdminForm
    list_display = ("name", "organization", "color", "sort_order")
    list_filter = ("organization",)


@admin.register(Contractor)
class ContractorAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "contact_name", "contact_email", "is_active")
    list_filter = ("organization", "is_active")
    search_fields = ("name", "contact_name", "contact_email")


class DrawingInline(admin.TabularInline):
    model = Drawing
    extra = 0
    fields = ("name", "file", "page_count")
    readonly_fields = ("page_count",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "case_no", "status", "manager", "updated_at")
    list_filter = ("organization", "status")
    search_fields = ("name", "case_no", "address")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("members", "contractors")
    inlines = [DrawingInline]


@admin.register(Drawing)
class DrawingAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "page_count", "uploaded_by", "created_at")
    list_filter = ("project__organization", "project")
    search_fields = ("name",)


class RegistrationPhotoInline(admin.TabularInline):
    model = RegistrationPhoto
    extra = 0
    fields = ("image", "thumbnail", "uploaded_by", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = (
        "__str__", "project", "discipline", "assigned_contractor",
        "status", "deadline", "created_at",
    )
    list_filter = ("project__organization", "project", "status", "discipline")
    search_fields = ("subject", "description")
    # number is allocated on save under a project lock — never editable.
    readonly_fields = ("number", "resolved_at", "approved_at")
    inlines = [RegistrationPhotoInline]
