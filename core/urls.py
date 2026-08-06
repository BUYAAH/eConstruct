from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "core"

# URL paths stay English even though the UI is Danish — same rule as the
# internal `micki:*` identifiers (PLAN.md "Known decisions still open" #4).
urlpatterns = [
    path("", views.overview, name="overview"),
    path("projects/", views.projects, name="projects"),
    path("projects/<slug:slug>/", views.project_detail, name="project_detail"),
    path("folders/", views.folders, name="folders"),
    path("registrations/", views.registrations, name="registrations"),
    path("reports/", views.reports, name="reports"),
    path("users/", views.users, name="users"),
    path("settings/", views.settings, name="settings"),
    # /manage/ was users + layers on one page before the dashboard split.
    path("manage/", RedirectView.as_view(pattern_name="core:users"), name="manage"),
    path("settings/layers/new/", views.layer_create, name="layer_create"),
    path("settings/layers/<int:pk>/edit/", views.layer_edit, name="layer_edit"),
    path("settings/layers/<int:pk>/delete/", views.layer_delete, name="layer_delete"),
    path("users/<int:pk>/toggle/<str:field>/", views.user_toggle, name="user_toggle"),
    path("folders/add/", views.folder_picker, name="folder_picker"),
    path("folders/browse/", views.browse, name="browse"),
    path("folders/link/", views.link_folder, name="link_folder"),
    path("folders/<int:pk>/unlink/", views.unlink_folder, name="unlink_folder"),
    path("folders/<int:pk>/", views.folder_detail, name="folder_detail"),
    path("folders/<int:pk>/open/<str:item_id>/", views.open_document, name="open_document"),
    path("documents/<int:pk>/", views.viewer, name="viewer"),
    path("documents/<int:pk>/pdf/", views.document_pdf, name="document_pdf"),
    path("documents/<int:pk>/pins/", views.pins, name="pins"),
    path("documents/<int:pk>/notes/", views.notes_list, name="notes_list"),
    path("documents/<int:pk>/export/<str:mode>/", views.export_document, name="export_document"),
    path("documents/<int:pk>/notes/new/", views.note_new, name="note_new"),
    path("notes/<int:pk>/", views.note_detail, name="note_detail"),
    path("notes/<int:pk>/photo/", views.note_photo, name="note_photo"),
    path("notes/<int:pk>/edit/", views.note_edit, name="note_edit"),
    path("notes/<int:pk>/delete/", views.note_delete, name="note_delete"),
]
