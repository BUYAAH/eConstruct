from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    # Ours, not Django's: a superuser lands in Mothership, a customer in the
    # app. See accounts.views.LoginView.
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("invite/<str:token>/", views.accept_invitation, name="accept_invitation"),
]
