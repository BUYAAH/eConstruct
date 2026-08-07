"""Mothership — the internal console for running the SaaS itself.

Everything in `core` answers "what can this customer see?"; everything here
answers "what customers are there?". That is a different question with a
different gate, which is why it is a separate app with its own base template
rather than another `Administration` section in the customer sidebar.

Two rules hold throughout:

- **`is_superuser` only.** Not `is_staff` — that flag also opens Django admin
  and is the kind of thing you hand a support person one day. A non-superuser
  gets a 404, not a 403, so a logged-in customer poking at URLs learns
  nothing about what lives here.
- **Counts and project names, never content.** D6 says organizations are 100%
  separated. Mothership is the one place that reads across that line, and it
  is kept to the metadata needed to run the business — how many users, how
  many registrations, what the sites are called. No registration text, no
  photos, no drawings, and no way to act inside a client's data.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.emails import invitation_link, send_invitation
from accounts.models import Invitation
from core.defaults import seed_disciplines
from core.models import Organization, Project, Registration

from .forms import ClientCreateForm, ClientForm

User = get_user_model()


def superuser_required(view):
    """404 rather than 403 for everyone else — see the module docstring."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper


def _clients():
    """Every organization with the numbers the list shows, in one query.

    distinct=True on all of them: users, projects and registrations join
    independently, so without it each count comes back multiplied by the
    others' row counts.
    """
    return Organization.objects.annotate(
        user_count=models.Count("users", distinct=True),
        project_count=models.Count("projects", distinct=True),
        registration_count=models.Count("projects__registrations", distinct=True),
        last_activity=models.Max("projects__registrations__created_at"),
    ).order_by("-is_active", "name")


@superuser_required
def clients(request):
    qs = _clients()
    query = request.GET.get("q", "").strip()
    if query:
        qs = qs.filter(name__icontains=query)
    clients_list = list(qs)

    return render(
        request,
        "mothership/clients.html",
        {
            "clients": clients_list,
            "query": query,
            # Totals are over every client, not the filtered list — a figure
            # that changed as you typed in the search box would be a lie.
            "total_active": Organization.objects.filter(is_active=True).count(),
            "total_users": User.objects.filter(organization__isnull=False).count(),
            "total_projects": Project.objects.count(),
            "total_registrations": Registration.objects.count(),
        },
    )


@superuser_required
def client_create(request):
    if request.method != "POST":
        return render(request, "mothership/client_form.html", {"form": ClientCreateForm()})

    form = ClientCreateForm(request.POST)
    if not form.is_valid():
        return render(request, "mothership/client_form.html", {"form": form})

    data = form.cleaned_data
    invitation = None

    # The organization, its disciplines and the admin land together or not at
    # all. A half-created client — an org with no way to log into it — is
    # exactly the state this whole page exists to prevent.
    with transaction.atomic():
        organization = Organization.objects.create(name=data["name"], slug=form.slug)
        if data["seed_disciplines"]:
            seed_disciplines(organization)

        if data["access"] == ClientCreateForm.PASSWORD:
            User.objects.create_user(
                username=data["admin_email"],
                email=data["admin_email"],
                password=data["password"],
                first_name=data["admin_first_name"],
                last_name=data["admin_last_name"],
                organization=organization,
                is_org_admin=True,
            )
        else:
            invitation = Invitation.objects.create(
                organization=organization,
                email=data["admin_email"],
                first_name=data["admin_first_name"],
                last_name=data["admin_last_name"],
                as_org_admin=True,
                invited_by=request.user,
            )

    if invitation is None:
        messages.success(
            request,
            f"{organization.name} er oprettet. {data['admin_email']} kan logge ind med det samme.",
        )
    else:
        # Sent outside the transaction: the client should exist even if the
        # mail server is down, and the link is on the detail page either way.
        try:
            send_invitation(invitation)
        except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
            messages.warning(
                request,
                f"{organization.name} er oprettet, men invitationen kunne ikke sendes "
                f"({exc}). Kopiér linket herunder og send det manuelt.",
            )
        else:
            messages.success(
                request,
                f"{organization.name} er oprettet. Invitation sendt til {data['admin_email']}.",
            )

    return redirect("mothership:client_detail", slug=organization.slug)


@superuser_required
def client_detail(request, slug):
    organization = get_object_or_404(_clients(), slug=slug)
    today = timezone.localdate()

    registrations = Registration.objects.filter(project__organization=organization)
    invitations = organization.invitations.filter(accepted_at__isnull=True).order_by("-created_at")

    return render(
        request,
        "mothership/client_detail.html",
        {
            "client": organization,
            "form": ClientForm(instance=organization),
            # Project names and status only — no drawings, no registration
            # text. See the module docstring on how far this deliberately goes.
            "projects": organization.projects.with_stats().order_by("-updated_at"),
            "users": organization.users.order_by("-is_active", "-is_org_admin", "first_name"),
            "invitations": [
                (invitation, invitation_link(invitation)) for invitation in invitations
            ],
            "open_count": registrations.filter(status=Registration.OPEN).count(),
            "overdue_count": registrations.exclude(status=Registration.APPROVED)
            .filter(deadline__lt=today)
            .count(),
            "discipline_count": organization.disciplines.count(),
            "contractor_count": organization.contractors.count(),
            "drawing_count": organization.projects.aggregate(
                n=models.Count("drawings")
            )["n"],
        },
    )


@superuser_required
@require_POST
def client_edit(request, slug):
    organization = get_object_or_404(Organization, slug=slug)
    form = ClientForm(request.POST, instance=organization)
    if form.is_valid():
        form.save()
        messages.success(request, "Navnet er opdateret.")
    else:
        messages.error(request, "Navnet kunne ikke opdateres.")
    return redirect("mothership:client_detail", slug=organization.slug)


@superuser_required
@require_POST
def client_toggle(request, slug):
    """Suspend or reactivate a client.

    Suspension is enforced two ways (accounts.middleware): login is refused,
    and any session already open is ended on its next request. Sessions last
    30 days and slide forward, so login-time enforcement alone would leave a
    suspended client working for up to a month.
    """
    organization = get_object_or_404(Organization, slug=slug)
    organization.is_active = not organization.is_active
    organization.save(update_fields=["is_active", "updated_at"])

    if organization.is_active:
        messages.success(request, f"{organization.name} er aktiveret igen.")
    else:
        messages.warning(
            request,
            f"{organization.name} er suspenderet. Deres brugere logges ud ved næste kald.",
        )
    return redirect("mothership:client_detail", slug=organization.slug)
