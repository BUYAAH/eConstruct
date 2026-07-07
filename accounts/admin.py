from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import MsToken, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "company", "is_company_admin", "is_active")
    list_filter = ("company", "is_company_admin", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Micki", {"fields": ("company", "is_company_admin", "ms_object_id")}),
    )


@admin.register(MsToken)
class MsTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "updated_at")
    readonly_fields = ("user", "updated_at")

    def has_add_permission(self, request):
        return False
