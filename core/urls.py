from django.urls import path

from . import views

app_name = "core"

# URL paths stay English even though the UI is Danish — same rule as the
# internal `micki:*` identifiers.
urlpatterns = [
    path("", views.overview, name="overview"),

    # Projects — the spine. Drawings and registrations are created under one.
    path("projects/", views.projects, name="projects"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<slug:slug>/", views.project_detail, name="project_detail"),
    path("projects/<slug:slug>/edit/", views.project_edit, name="project_edit"),
    path("projects/<slug:slug>/drawings/upload/", views.drawing_upload, name="drawing_upload"),
    path("projects/<slug:slug>/registrations/new/", views.registration_new, name="registration_new"),

    path("drawings/<int:pk>/", views.viewer, name="viewer"),
    path("drawings/<int:pk>/delete/", views.drawing_delete, name="drawing_delete"),
    path("drawings/<int:pk>/pdf/", views.drawing_pdf, name="drawing_pdf"),
    path("drawings/<int:pk>/pins/", views.pins, name="pins"),
    path("drawings/<int:pk>/registrations/", views.drawing_registrations, name="drawing_registrations"),
    path("drawings/<int:pk>/export/<str:mode>/", views.export_drawing, name="export_drawing"),

    path("registrations/", views.registrations, name="registrations"),
    path("registrations/<int:pk>/", views.registration_detail, name="registration_detail"),
    path("registrations/<int:pk>/edit/", views.registration_edit, name="registration_edit"),
    path("registrations/<int:pk>/delete/", views.registration_delete, name="registration_delete"),
    path("registrations/<int:pk>/<str:action>/", views.registration_status, name="registration_status"),
    path("registrations/<int:pk>/photos/add/", views.registration_photo_add, name="registration_photo_add"),
    path("photos/<int:pk>/delete/", views.registration_photo_delete, name="registration_photo_delete"),
    path("photos/<int:pk>/<str:size>/", views.registration_photo, name="registration_photo"),

    path("reports/", views.reports, name="reports"),

    path("users/", views.users, name="users"),
    path("users/invite/", views.invite_create, name="invite_create"),
    path("users/invite/<int:pk>/revoke/", views.invite_revoke, name="invite_revoke"),
    path("users/<int:pk>/toggle/<str:field>/", views.user_toggle, name="user_toggle"),

    path("settings/", views.settings, name="settings"),
    path("settings/disciplines/new/", views.discipline_create, name="discipline_create"),
    path("settings/disciplines/<int:pk>/edit/", views.discipline_edit, name="discipline_edit"),
    path("settings/disciplines/<int:pk>/delete/", views.discipline_delete, name="discipline_delete"),
    path("settings/contractors/new/", views.contractor_create, name="contractor_create"),
    path("settings/contractors/<int:pk>/delete/", views.contractor_delete, name="contractor_delete"),
]
