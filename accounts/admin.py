from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Invitation, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "organization", "is_org_admin", "is_active")
    list_filter = ("organization", "is_org_admin", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Organisation", {"fields": ("organization", "is_org_admin")}),
    )


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "organization", "as_org_admin", "invited_by", "created_at", "accepted_at")
    list_filter = ("organization", "as_org_admin")
    search_fields = ("email",)
    readonly_fields = ("token", "created_at", "accepted_at")
