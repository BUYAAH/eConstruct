from django.urls import path

from . import views

app_name = "mothership"

# Paths stay English like the rest of the app, even though the UI is Danish.
# "client" rather than "organization": in here they are customers, and the
# word keeps this vocabulary distinct from the tenant model the customer app
# talks about.
urlpatterns = [
    path("", views.clients, name="clients"),
    path("clients/new/", views.client_create, name="client_create"),
    path("clients/<slug:slug>/", views.client_detail, name="client_detail"),
    path("clients/<slug:slug>/edit/", views.client_edit, name="client_edit"),
    path("clients/<slug:slug>/toggle/", views.client_toggle, name="client_toggle"),
]
