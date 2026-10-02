from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Invitation, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Rebuilt rather than extended, because `UserAdmin`'s own fieldsets name
    `username`, which no longer exists — inheriting them raises at admin
    check time. `add_fieldsets` matters most: it is the page that used to let
    a second account be created on an existing address.
    """

    list_display = ("email", "first_name", "last_name", "organization", "is_org_admin", "is_active")
    list_filter = ("organization", "is_org_admin", "is_active")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Organisation", {"fields": ("organization", "is_org_admin")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "usable_password", "password1", "password2"),
            },
        ),
        ("Organisation", {"fields": ("organization", "is_org_admin")}),
    )


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "organization", "as_org_admin", "invited_by", "created_at", "accepted_at")
    list_filter = ("organization", "as_org_admin")
    search_fields = ("email",)
    readonly_fields = ("token", "created_at", "accepted_at")
