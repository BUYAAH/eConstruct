import json
import re
import uuid
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.emails import send_invitation
from accounts.forms import InvitationForm
from accounts.models import Invitation

from .forms import (
    ContractorForm, DisciplineForm, DrawingUploadForm, PhotoUploadForm,
    ProjectForm, RegistrationForm,
)
from .images import process_photo
from .models import (
    Contractor, Discipline, Drawing, Project, Registration, RegistrationPhoto,
)
from .pdf_export import stamp_registrations


def org_admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_org_admin:
            return HttpResponseForbidden("Kræver administratoradgang.")
        return view(request, *args, **kwargs)

    return wrapper


# --- Scoping -----------------------------------------------------------------
#
# Everything organization-owned is reached through these. Organizations are
# 100% separated (ROADMAP.md D6) and project access is by explicit membership
# (D9), so a view that builds its own queryset is a bug waiting to leak data.
# Object lookups filter in the same query rather than fetching then checking.


def _projects(request):
    """Projects the user may see: their own, or all of them for an org admin."""
    user = request.user
    qs = Project.objects.filter(organization=user.organization)
    if not user.is_org_admin:
        qs = qs.filter(members=user)
    return qs


def _get_project(request, slug):
    return get_object_or_404(_projects(request), slug=slug)


def _drawings(request):
    return Drawing.objects.filter(project__in=_projects(request))


def _registrations(request):
    return Registration.objects.filter(project__in=_projects(request))


# --- Overview ----------------------------------------------------------------


@login_required
def overview(request):
    today = timezone.localdate()
    registrations = _registrations(request)
    open_qs = registrations.exclude(status=Registration.APPROVED)

    return render(
        request,
        "core/overview.html",
        {
            "project_count": _projects(request).filter(status=Project.ACTIVE).count(),
            "open_count": registrations.filter(status=Registration.OPEN).count(),
            "resolved_count": registrations.filter(status=Registration.RESOLVED).count(),
            "overdue_count": open_qs.filter(deadline__lt=today).count(),
            "recent": registrations.select_related(
                "project", "discipline", "assigned_contractor", "author"
            )[:8],
        },
    )


# --- Projects ----------------------------------------------------------------


@login_required
def projects(request):
    qs = _projects(request).select_related("manager").annotate(
        drawing_count=Count("drawings", distinct=True),
        registration_count=Count("registrations", distinct=True),
        open_count=Count(
            "registrations",
            filter=Q(registrations__status=Registration.OPEN),
            distinct=True,
        ),
        contractor_count=Count("contractors", distinct=True),
    )
    return render(request, "core/projects.html", {"projects": qs})


@org_admin_required
def project_create(request):
    org = request.user.organization
    if request.method == "POST":
        form = ProjectForm(org, request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.organization = org
            project.save()
            form.save_m2m()
            # The creator is always a member, or an admin can lock themselves
            # out of a project they just made.
            project.members.add(request.user)
            return redirect("core:project_detail", slug=project.slug)
    else:
        form = ProjectForm(org, initial={"manager": request.user})
    return render(request, "core/project_form.html", {"form": form, "heading": "Nyt projekt"})


@org_admin_required
def project_edit(request, slug):
    project = _get_project(request, slug)
    org = request.user.organization
    if request.method == "POST":
        form = ProjectForm(org, request.POST, instance=project)
        if form.is_valid():
            form.save()
            return redirect("core:project_detail", slug=project.slug)
    else:
        form = ProjectForm(org, instance=project)
    return render(
        request,
        "core/project_form.html",
        {"form": form, "heading": f"Redigér {project.name}", "project": project},
    )


@login_required
def project_detail(request, slug):
    project = _get_project(request, slug)
    registrations = project.registrations.select_related(
        "discipline", "assigned_contractor", "responsible", "author", "drawing"
    ).prefetch_related("photos")

    return render(
        request,
        "core/project_detail.html",
        {
            "project": project,
            "registrations": registrations,
            "drawings": project.drawings.all(),
            "open_count": registrations.filter(status=Registration.OPEN).count(),
            "preview_drawing": project.drawings.first(),
        },
    )


# --- Drawings ----------------------------------------------------------------


@org_admin_required
def drawing_upload(request, slug):
    project = _get_project(request, slug)
    if request.method == "POST":
        form = DrawingUploadForm(request.POST, request.FILES)
        if form.is_valid():
            drawing = form.save(commit=False)
            drawing.project = project
            drawing.uploaded_by = request.user
            if not drawing.name:
                drawing.name = request.FILES["file"].name.rsplit(".", 1)[0]
            drawing.save()
            drawing.page_count = _count_pages(drawing)
            drawing.save(update_fields=["page_count"])
            return redirect("core:project_detail", slug=project.slug)
    else:
        form = DrawingUploadForm()
    return render(request, "core/drawing_upload.html", {"form": form, "project": project})


def _count_pages(drawing):
    """Read the page count once at upload so the viewer needn't reparse."""
    from pypdf import PdfReader

    try:
        with drawing.file.open("rb") as fh:
            return len(PdfReader(fh).pages)
    except Exception:
        # A file pypdf can't parse still uploads; the viewer surfaces the
        # problem. Better than losing the upload over a page count.
        return 0


@org_admin_required
@require_POST
def drawing_delete(request, pk):
    drawing = get_object_or_404(_drawings(request), pk=pk)
    slug = drawing.project.slug
    drawing.file.delete(save=False)
    drawing.delete()
    return redirect("core:project_detail", slug=slug)


@login_required
def viewer(request, pk):
    drawing = get_object_or_404(_drawings(request).select_related("project"), pk=pk)
    return render(
        request,
        "core/viewer.html",
        {
            "drawing": drawing,
            "project": drawing.project,
            "disciplines": request.user.organization.disciplines.all(),
        },
    )


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


@login_required
def drawing_pdf(request, pk):
    """Serve the PDF bytes, login- and access-checked.

    Range support is implemented by hand: Django 6.0's FileResponse doesn't
    do it, and PDF.js relies on it to fetch a large CAD drawing in chunks
    rather than downloading the whole file before showing page 1 — which
    matters on a phone, the primary device.
    """
    drawing = get_object_or_404(_drawings(request), pk=pk)
    try:
        size = drawing.file.size
    except (FileNotFoundError, ValueError):
        raise Http404("Tegningen findes ikke længere på serveren.")

    match = _RANGE_RE.match(request.headers.get("Range", ""))
    if not match:
        response = FileResponse(drawing.file.open("rb"), content_type="application/pdf")
        response["Accept-Ranges"] = "bytes"
        return response

    start_raw, end_raw = match.groups()
    if start_raw:
        start = int(start_raw)
        end = int(end_raw) if end_raw else size - 1
    else:
        # "bytes=-N" means the final N bytes.
        start = max(size - int(end_raw), 0) if end_raw else 0
        end = size - 1
    end = min(end, size - 1)

    if start > end or start >= size:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response

    with drawing.file.open("rb") as fh:
        fh.seek(start)
        chunk = fh.read(end - start + 1)

    response = HttpResponse(chunk, status=206, content_type="application/pdf")
    response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["Content-Length"] = str(len(chunk))
    response["Accept-Ranges"] = "bytes"
    return response


EXPORT_MODES = {"summary": "kommenteret", "inline": "noter i tekst"}


@login_required
def export_drawing(request, pk, mode):
    """Stamp this drawing's registrations into the PDF and hand it back.

    This is what a contractor without a login receives (D7)."""
    if mode not in EXPORT_MODES:
        raise Http404
    drawing = get_object_or_404(_drawings(request), pk=pk)
    registrations = drawing.registrations.select_related(
        "discipline", "author", "assigned_contractor"
    ).filter(x_pct__isnull=False)

    with drawing.file.open("rb") as fh:
        stamped = stamp_registrations(
            fh.read(), registrations, mode=mode, document_name=drawing.name
        )

    response = HttpResponse(stamped, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{drawing.name} ({EXPORT_MODES[mode]}).pdf"'
    )
    return response


# --- Registrations -----------------------------------------------------------


def _close_and_refresh(response):
    """Tell the viewer to close the sheet and re-fetch the pin layer."""
    response["HX-Trigger"] = json.dumps({"micki:close-sheet": True, "micki:refresh-pins": True})
    return response


def _can_edit(user, registration):
    return registration.author_id == user.id or user.is_org_admin


@login_required
def registrations(request):
    """Cross-project list with filters."""
    qs = _registrations(request).select_related(
        "project", "discipline", "assigned_contractor", "responsible", "author"
    )

    status = request.GET.get("status", "")
    if status in dict(Registration.STATUS_CHOICES):
        qs = qs.filter(status=status)
    if request.GET.get("overdue") == "1":
        qs = qs.exclude(status=Registration.APPROVED).filter(
            deadline__lt=timezone.localdate()
        )
    project_slug = request.GET.get("project", "")
    if project_slug:
        qs = qs.filter(project__slug=project_slug)
    discipline_id = request.GET.get("discipline", "")
    if discipline_id.isdigit():
        qs = qs.filter(discipline_id=int(discipline_id))

    return render(
        request,
        "core/registrations.html",
        {
            "registrations": qs,
            "projects": _projects(request),
            "disciplines": request.user.organization.disciplines.all(),
            "status_choices": Registration.STATUS_CHOICES,
            "selected": {
                "status": status,
                "project": project_slug,
                "discipline": discipline_id,
                "overdue": request.GET.get("overdue", ""),
            },
        },
    )


@login_required
def registration_new(request, slug):
    """Create a registration, optionally pinned to a drawing page.

    Reached two ways: from the viewer with drawing/page/x/y in the query
    string, or from the project page with none of them (D3 — a registration
    doesn't need a drawing).
    """
    project = _get_project(request, slug)
    from_viewer = bool(request.GET.get("x") or request.POST.get("x"))

    if request.method == "POST":
        form = RegistrationForm(project, request.POST)
        if form.is_valid():
            registration = form.save(commit=False)
            registration.project = project
            registration.author = request.user
            _apply_pin(registration, request, project)
            registration.save()
            if request.FILES.get("photo"):
                _add_photo(registration, request.FILES["photo"], request.user)
            if from_viewer:
                return _close_and_refresh(render(request, "core/partials/sheet_saved.html"))
            return redirect("core:registration_detail", pk=registration.pk)
    else:
        form = RegistrationForm(project)

    context = {
        "form": form,
        "photo_form": PhotoUploadForm(),
        "project": project,
        "action": request.get_full_path(),
        "from_viewer": from_viewer,
    }
    template = (
        "core/partials/registration_form.html" if from_viewer else "core/registration_form.html"
    )
    return render(request, template, context)


def _apply_pin(registration, request, project):
    """Attach the tapped location, when the form came from the viewer."""
    drawing_id = request.POST.get("drawing")
    if not drawing_id:
        return
    # Scoped to the project, so a posted id can't reach another project's drawing.
    drawing = project.drawings.filter(pk=drawing_id).first()
    if drawing is None:
        return
    registration.drawing = drawing
    registration.page_number = int(request.POST.get("page") or 1)
    registration.x_pct = request.POST["x"]
    registration.y_pct = request.POST["y"]


@login_required
def registration_detail(request, pk):
    registration = get_object_or_404(
        _registrations(request).select_related(
            "project", "discipline", "assigned_contractor", "responsible", "author", "drawing"
        ),
        pk=pk,
    )
    context = {
        "registration": registration,
        "can_edit": _can_edit(request.user, registration),
        "photo_form": PhotoUploadForm(),
    }
    if request.headers.get("HX-Request"):
        return render(request, "core/partials/registration_sheet.html", context)
    return render(request, "core/registration_detail.html", context)


@login_required
def registration_edit(request, pk):
    registration = get_object_or_404(_registrations(request), pk=pk)
    if not _can_edit(request.user, registration):
        return HttpResponseForbidden()
    if request.method == "POST":
        form = RegistrationForm(registration.project, request.POST, instance=registration)
        if form.is_valid():
            form.save()
            return redirect("core:registration_detail", pk=registration.pk)
    else:
        form = RegistrationForm(registration.project, instance=registration)
    return render(
        request,
        "core/registration_form.html",
        {
            "form": form,
            "photo_form": PhotoUploadForm(),
            "project": registration.project,
            "registration": registration,
            "action": request.path,
        },
    )


@login_required
@require_POST
def registration_status(request, pk, action):
    """Åben → Løst → Godkendt, and back (D8).

    Anyone on the project can mark something Løst; only the person who
    raised it (or an admin) may approve, so a fix isn't signed off by the
    same hand that made it.
    """
    registration = get_object_or_404(_registrations(request), pk=pk)

    if action == "resolve":
        registration.mark_resolved()
    elif action == "approve":
        if not _can_edit(request.user, registration):
            return HttpResponseForbidden("Kun opretteren eller en administrator kan godkende.")
        registration.mark_approved()
    elif action == "reopen":
        registration.reopen()
    else:
        raise Http404

    if request.headers.get("HX-Request"):
        return render(
            request,
            "core/partials/registration_status.html",
            {"registration": registration, "can_edit": _can_edit(request.user, registration)},
        )
    return redirect("core:registration_detail", pk=registration.pk)


@login_required
@require_POST
def registration_delete(request, pk):
    registration = get_object_or_404(_registrations(request), pk=pk)
    if not _can_edit(request.user, registration):
        return HttpResponseForbidden()
    slug = registration.project.slug
    registration.delete()
    if request.headers.get("HX-Request"):
        return _close_and_refresh(render(request, "core/partials/sheet_saved.html"))
    return redirect("core:project_detail", slug=slug)


def _add_photo(registration, uploaded, user):
    full, thumb = process_photo(uploaded)
    photo = RegistrationPhoto(registration=registration, uploaded_by=user)
    stem = uuid.uuid4().hex
    photo.image.save(f"{stem}.jpg", full, save=False)
    photo.thumbnail.save(f"{stem}-thumb.jpg", thumb, save=False)
    photo.save()
    return photo


@login_required
@require_POST
def registration_photo_add(request, pk):
    registration = get_object_or_404(_registrations(request), pk=pk)
    form = PhotoUploadForm(request.POST, request.FILES)
    if form.is_valid():
        _add_photo(registration, form.cleaned_data["photo"], request.user)
    return render(
        request,
        "core/partials/registration_photos.html",
        {"registration": registration, "photo_form": PhotoUploadForm(),
         "can_edit": _can_edit(request.user, registration)},
    )


@login_required
@require_POST
def registration_photo_delete(request, pk):
    photo = get_object_or_404(
        RegistrationPhoto, pk=pk, registration__project__in=_projects(request)
    )
    registration = photo.registration
    if not _can_edit(request.user, registration):
        return HttpResponseForbidden()
    photo.image.delete(save=False)
    photo.thumbnail.delete(save=False)
    photo.delete()
    return render(
        request,
        "core/partials/registration_photos.html",
        {"registration": registration, "photo_form": PhotoUploadForm(),
         "can_edit": _can_edit(request.user, registration)},
    )


@login_required
def registration_photo(request, pk, size):
    """Serve photo bytes. Nothing under MEDIA_ROOT is web-reachable, so this
    is the only path to an image and it is access-checked."""
    photo = get_object_or_404(
        RegistrationPhoto, pk=pk, registration__project__in=_projects(request)
    )
    field = photo.thumbnail if size == "thumb" else photo.image
    if not field:
        raise Http404
    return FileResponse(field.open("rb"), content_type="image/jpeg")


@login_required
def pins(request, pk):
    """HTMX partial: pinned registrations on one page of a drawing."""
    drawing = get_object_or_404(_drawings(request), pk=pk)
    page = int(request.GET.get("page", 1))
    return render(
        request,
        "core/partials/pins.html",
        {
            "registrations": drawing.registrations.filter(
                page_number=page, x_pct__isnull=False
            ).select_related("discipline")
        },
    )


@login_required
def drawing_registrations(request, pk):
    """HTMX partial: every registration on a drawing, listed under the viewer."""
    drawing = get_object_or_404(_drawings(request), pk=pk)
    return render(
        request,
        "core/partials/registration_rows.html",
        {
            "registrations": drawing.registrations.select_related(
                "discipline", "assigned_contractor", "author"
            ).prefetch_related("photos"),
        },
    )


# --- Organization management (admins) ----------------------------------------


@org_admin_required
def users(request):
    org = request.user.organization
    return render(
        request,
        "core/users.html",
        {
            "users": org.users.order_by("-is_active", "-is_org_admin", "first_name"),
            "invitations": org.invitations.filter(accepted_at__isnull=True),
            "form": InvitationForm(org),
        },
    )


def _invitations_response(request, form=None, sent=False):
    org = request.user.organization
    return render(
        request,
        "core/partials/invitations_section.html",
        {
            "invitations": org.invitations.filter(accepted_at__isnull=True),
            "form": form or InvitationForm(org),
            "sent": sent,
        },
    )


@org_admin_required
@require_POST
def invite_create(request):
    org = request.user.organization
    form = InvitationForm(org, request.POST)
    if form.is_valid():
        invitation = form.save(commit=False)
        invitation.organization = org
        invitation.invited_by = request.user
        invitation.save()
        send_invitation(invitation)
        return _invitations_response(request, sent=True)
    return _invitations_response(request, form)


@org_admin_required
@require_POST
def invite_revoke(request, pk):
    get_object_or_404(
        Invitation, pk=pk, organization=request.user.organization, accepted_at__isnull=True
    ).delete()
    return _invitations_response(request)


@org_admin_required
@require_POST
def user_toggle(request, pk, field):
    if field not in ("is_active", "is_org_admin"):
        raise Http404
    target = get_object_or_404(
        get_user_model(), pk=pk, organization=request.user.organization
    )
    if target == request.user:
        return render(
            request,
            "core/partials/user_row.html",
            {"u": target, "error": "Du kan ikke ændre din egen adgang."},
        )
    setattr(target, field, not getattr(target, field))
    target.save()
    return render(request, "core/partials/user_row.html", {"u": target})


@org_admin_required
def settings(request):
    org = request.user.organization
    return render(
        request,
        "core/settings.html",
        {
            "disciplines": org.disciplines.all(),
            "form": DisciplineForm(),
            "contractors": org.contractors.all(),
            "contractor_form": ContractorForm(),
        },
    )


def _disciplines_section(request, form=None):
    return render(
        request,
        "core/partials/disciplines_section.html",
        {"disciplines": request.user.organization.disciplines.all(), "form": form or DisciplineForm()},
    )


@org_admin_required
@require_POST
def discipline_create(request):
    form = DisciplineForm(request.POST)
    if form.is_valid():
        discipline = form.save(commit=False)
        discipline.organization = request.user.organization
        discipline.save()
        form = None
    return _disciplines_section(request, form)


@org_admin_required
def discipline_edit(request, pk):
    discipline = get_object_or_404(Discipline, pk=pk, organization=request.user.organization)
    if request.method == "POST":
        form = DisciplineForm(request.POST, instance=discipline)
        if form.is_valid():
            form.save()
            return _disciplines_section(request)
    else:
        form = DisciplineForm(instance=discipline)
    return render(
        request, "core/partials/discipline_row_edit.html", {"discipline": discipline, "form": form}
    )


@org_admin_required
@require_POST
def discipline_delete(request, pk):
    discipline = get_object_or_404(Discipline, pk=pk, organization=request.user.organization)
    if discipline.registrations.exists():
        return render(
            request,
            "core/partials/discipline_row.html",
            {
                "discipline": discipline,
                "error": f"Bruges af {discipline.registrations.count()} registrering(er).",
            },
        )
    discipline.delete()
    return _disciplines_section(request)


def _contractors_section(request, form=None):
    return render(
        request,
        "core/partials/contractors_section.html",
        {
            "contractors": request.user.organization.contractors.all(),
            "contractor_form": form or ContractorForm(),
        },
    )


@org_admin_required
@require_POST
def contractor_create(request):
    form = ContractorForm(request.POST)
    if form.is_valid():
        contractor = form.save(commit=False)
        contractor.organization = request.user.organization
        contractor.save()
        form = None
    return _contractors_section(request, form)


@org_admin_required
@require_POST
def contractor_delete(request, pk):
    contractor = get_object_or_404(
        Contractor, pk=pk, organization=request.user.organization
    )
    if contractor.registrations.exists():
        return _contractors_section(request)
    contractor.delete()
    return _contractors_section(request)


# --- Placeholder -------------------------------------------------------------


@login_required
def reports(request):
    """Rapporter — generated PDFs of filtered registrations. Phase 5."""
    return render(request, "core/placeholder.html", {"heading": "Rapporter", "icon": "i-reports"})
