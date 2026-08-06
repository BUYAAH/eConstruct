from django.urls import path

from . import views

app_name = "core"

# URL paths stay English even though the UI is Danish — same rule as the
# internal `micki:*` identifiers.
urlpatterns = [
    path("", views.overview, name="overview"),
    path("projects/", views.projects, name="projects"),
    path("projects/<slug:slug>/", views.project_detail, name="project_detail"),
    path("registrations/", views.registrations, name="registrations"),
    path("reports/", views.reports, name="reports"),
    path("users/", views.users, name="users"),
    path("users/invite/", views.invite_create, name="invite_create"),
    path("users/invite/<int:pk>/revoke/", views.invite_revoke, name="invite_revoke"),
    path("users/<int:pk>/toggle/<str:field>/", views.user_toggle, name="user_toggle"),
    path("settings/", views.settings, name="settings"),
    path("settings/disciplines/new/", views.discipline_create, name="discipline_create"),
    path("settings/disciplines/<int:pk>/edit/", views.discipline_edit, name="discipline_edit"),
    path("settings/disciplines/<int:pk>/delete/", views.discipline_delete, name="discipline_delete"),
    path("drawings/", views.drawings, name="drawings"),
    path("drawings/upload/", views.drawing_upload, name="drawing_upload"),
    path("drawings/<int:pk>/", views.viewer, name="viewer"),
    path("drawings/<int:pk>/delete/", views.drawing_delete, name="drawing_delete"),
    path("drawings/<int:pk>/pdf/", views.drawing_pdf, name="drawing_pdf"),
    path("drawings/<int:pk>/pins/", views.pins, name="pins"),
    path("drawings/<int:pk>/notes/", views.notes_list, name="notes_list"),
    path("drawings/<int:pk>/notes/new/", views.note_new, name="note_new"),
    path("drawings/<int:pk>/export/<str:mode>/", views.export_drawing, name="export_drawing"),
    path("notes/<int:pk>/", views.note_detail, name="note_detail"),
    path("notes/<int:pk>/photo/", views.note_photo, name="note_photo"),
    path("notes/<int:pk>/edit/", views.note_edit, name="note_edit"),
    path("notes/<int:pk>/delete/", views.note_delete, name="note_delete"),
]
