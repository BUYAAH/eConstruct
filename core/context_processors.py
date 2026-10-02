"""Template context shared by every page.

`nav_section` — which sidebar entry to highlight, derived from the resolved
URL name, so no view has to remember to pass it.
`nav_overdue_count` — the red number beside Registreringer. Lazy, so pages
that never render the nav (HTMX partials, the login page) never pay for the
query; the rail, the offcanvas and the tab bar all read it, and the proxy
runs it once.
`brand` — the product name, from one settings constant (it has changed once
and is expected to change again).
"""

from django.conf import settings
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from .models import Project, Registration

_SECTION_BY_URL_NAME = {
    "overview": "overview",
    "projects": "projects",
    "project_create": "projects",
    "project_detail": "projects",
    "project_edit": "projects",
    "drawing_upload": "projects",
    "drawing_delete": "projects",
    "viewer": "projects",
    "registrations": "registrations",
    "registration_new": "registrations",
    "registration_detail": "registrations",
    "registration_edit": "registrations",
    "reports": "reports",
    "users": "users",
    "user_toggle": "users",
    "invite_create": "users",
    "invite_revoke": "users",
    "settings": "settings",
    "discipline_create": "settings",
    "discipline_edit": "settings",
    "discipline_delete": "settings",
    "contractor_create": "settings",
    "contractor_delete": "settings",
}


def brand(request):
    return {"brand": settings.BRAND_NAME}


def _overdue_count(user):
    if not user.is_authenticated or user.organization_id is None:
        return 0
    return (
        Registration.objects.filter(project__in=Project.objects.for_user(user))
        .exclude(status=Registration.APPROVED)
        .filter(deadline__lt=timezone.localdate())
        .count()
    )


def nav(request):
    match = request.resolver_match
    section = ""
    if match is not None and match.app_name == "core":
        section = _SECTION_BY_URL_NAME.get(match.url_name, "")
    return {
        "nav_section": section,
        "nav_overdue_count": SimpleLazyObject(lambda: _overdue_count(request.user)),
    }
