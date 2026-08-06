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
    "project_detail": "projects",
    "folders": "folders",
    "folder_picker": "folders",
    "browse": "folders",
    "link_folder": "folders",
    "unlink_folder": "folders",
    "folder_detail": "folders",
    "open_document": "folders",
    "viewer": "folders",
    "registrations": "registrations",
    "reports": "reports",
    "users": "users",
    "user_toggle": "users",
    "settings": "settings",
    "layer_create": "settings",
    "layer_edit": "settings",
    "layer_delete": "settings",
}


def brand(request):
    return {"brand": settings.BRAND_NAME}


def nav(request):
    match = request.resolver_match
    if match is None or match.app_name != "core":
        return {"nav_section": ""}
    return {"nav_section": _SECTION_BY_URL_NAME.get(match.url_name, "")}
