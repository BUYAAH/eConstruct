"""Template context shared by every page.

`nav_section` — which sidebar entry to highlight, derived from the resolved
URL name, so no view has to remember to pass it.
`brand` — the product name, from one settings constant (it has changed once
and is expected to change again).
"""

from django.conf import settings

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


def nav(request):
    match = request.resolver_match
    if match is None or match.app_name != "core":
        return {"nav_section": ""}
    return {"nav_section": _SECTION_BY_URL_NAME.get(match.url_name, "")}
