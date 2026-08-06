import json
import re
import uuid
from datetime import timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.emails import send_invitation
from accounts.forms import InvitationForm
from accounts.models import Invitation

from .forms import DisciplineForm, DrawingUploadForm, NoteForm
from .images import process_upload
from .models import Discipline, Drawing, Note
from .pdf_export import stamp_notes


def org_admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_org_admin:
            return HttpResponseForbidden("Kræver administratoradgang.")
        return view(request, *args, **kwargs)

    return wrapper


# Every organization-owned queryset below goes through one of these, so the
# tenant filter is never something an individual view has to remember.
# Organizations are 100% separated (ROADMAP.md D6) — a missing filter here is
# a cross-tenant leak, not a cosmetic bug.
def _drawings(request):
    return Drawing.objects.filter(organization=request.user.organization)


def _notes(request):
    return Note.objects.filter(drawing__organization=request.user.organization)


@login_required
def overview(request):
    """Landing page. Gets KPI tiles + recent activity in phase 5."""
    return render(request, "core/placeholder.html", {"heading": "Oversigt", "icon": "i-overview"})


@login_required
def registrations(request):
    return render(
        request, "core/placeholder.html", {"heading": "Registreringer", "icon": "i-registrations"}
    )


@login_required
def reports(request):
    return render(request, "core/placeholder.html", {"heading": "Rapporter", "icon": "i-reports"})


# Stand-in for the Project model that doesn't exist yet, so we can agree on
# the Projekter layout before building it. `updated` is relative to now so the
# demo never goes stale. Templates read only from these dicts — wiring a real
# queryset in phase 2 should be a view-only change.
_DEMO_PROJECTS = [
    {
        "slug": "sygehus-nord",
        "name": "Sygehus Nord",
        "case_no": "2024-0417",
        "address": "Hobrovej 18, 9000 Aalborg",
        "status": "Aktiv",
        "status_class": "success",
        "drawings": 34,
        "documents": 18,
        "registrations": 23,
        "reports": 12,
        "companies": 4,
        "open_registrations": 7,
        "manager": "Lene Bak",
        "progress": 62,
        "updated_delta": timedelta(hours=3),
    },
    {
        "slug": "hasserisvej-31",
        "name": "Hasserisvej 31",
        "case_no": "2024-0392",
        "address": "Hasserisvej 31, 9000 Aalborg",
        "status": "Aktiv",
        "status_class": "success",
        "drawings": 9,
        "documents": 6,
        "registrations": 11,
        "reports": 5,
        "companies": 2,
        "open_registrations": 1,
        "manager": "Jonas Overgaard",
        "progress": 88,
        "updated_delta": timedelta(days=2),
    },
    {
        "slug": "vester-hassing-skole",
        "name": "Vester Hassing Skole",
        "case_no": "2023-1184",
        "address": "Halvvejen 5, 9310 Vodskov",
        "status": "Afsluttet",
        "status_class": "secondary",
        "drawings": 41,
        "documents": 27,
        "registrations": 56,
        "reports": 21,
        "companies": 5,
        "open_registrations": 0,
        "manager": "Mette Kjær",
        "progress": 100,
        "updated_delta": timedelta(days=34),
    },
]


def _demo_projects():
    now = timezone.now()
    return [{**p, "updated": now - p["updated_delta"]} for p in _DEMO_PROJECTS]


# Shaped after the real Note rows (discipline + author + page + optional
# photo) with construction-realistic content. Becomes a Registration queryset
# in phase 4.
_DEMO_REGISTRATIONS = [
    {
        "text": "Revne i betonvæg ved akse D/4",
        "category": "Konstruktion",
        "color": "#dc3545",
        "open": True,
        "location": "3 - 1. etage · s. 1",
        "assignee": "Jonas Overgaard",
        "deadline_delta": timedelta(days=5),
        "author": "Lene Bak",
        "photo": True,
        "created_delta": timedelta(hours=2),
    },
    {
        "text": "Manglende brandtætning omkring rørgennemføring",
        "category": "Brand",
        "color": "#fd7e14",
        "open": True,
        "location": "3 - 1. etage · s. 1",
        "assignee": "Søren Dahl",
        "deadline_delta": timedelta(days=-1),
        "author": "Jonas Overgaard",
        "photo": True,
        "created_delta": timedelta(hours=6),
    },
    {
        "text": "El-dåse placeret forkert ift. tegning",
        "category": "El",
        "color": "#0d6efd",
        "open": True,
        "location": "3 - 1. etage · s. 2",
        "assignee": "",
        "deadline_delta": None,
        "author": "Søren Dahl",
        "photo": False,
        "created_delta": timedelta(days=1),
    },
    {
        "text": "Vandskade i loft ved teknikrum",
        "category": "VVS",
        "color": "#0dcaf0",
        "open": True,
        "location": "3 - 1. etage · s. 3",
        "assignee": "Anders Precht",
        "deadline_delta": timedelta(days=1),
        "author": "Mette Kjær",
        "photo": True,
        "created_delta": timedelta(days=2),
    },
    {
        "text": "Loftshøjde målt til 2,80 m mod 3,00 m projekteret",
        "category": "Konstruktion",
        "color": "#dc3545",
        "open": False,
        "location": "3 - 1. etage · s. 2",
        "assignee": "Mette Kjær",
        "deadline_delta": timedelta(days=-3),
        "author": "Lene Bak",
        "photo": False,
        "created_delta": timedelta(days=5),
    },
    {
        "text": "Manglende isolering i ydervæg mod nord",
        "category": "Kvalitet",
        "color": "#198754",
        "open": False,
        "location": "3 - 1. etage · s. 4",
        "assignee": "",
        "deadline_delta": None,
        "author": "Anders Precht",
        "photo": True,
        "created_delta": timedelta(days=9),
    },
]


def _demo_registrations():
    """Materialise the relative deltas. `overdue` is computed here rather than
    in the template — Django templates can't compare datetimes."""
    now = timezone.now()
    out = []
    for r in _DEMO_REGISTRATIONS:
        deadline = now + r["deadline_delta"] if r["deadline_delta"] is not None else None
        out.append({
            **r,
            "created": now - r["created_delta"],
            "deadline": deadline,
            "overdue": bool(deadline and r["open"] and deadline < now),
        })
    return out


@login_required
def projects(request):
    """Target layout for the coming project concept (demo data — see above)."""
    return render(request, "core/projects.html", {"projects": _demo_projects()})


@login_required
def project_detail(request, slug):
    project = next((p for p in _demo_projects() if p["slug"] == slug), None)
    if project is None:
        raise Http404("Ukendt projekt")
    return render(
        request,
        "core/project_detail.html",
        {
            "project": project,
            "registrations": _demo_registrations(),
            # The inline preview shows a real uploaded drawing when there is
            # one; the template falls back to an empty state otherwise.
            "preview_drawing": _drawings(request).first(),
        },
    )


# --- Drawings ----------------------------------------------------------------


@login_required
def drawings(request):
    return render(request, "core/drawings.html", {"drawings": _drawings(request)})


@org_admin_required
def drawing_upload(request):
    if request.method == "POST":
        form = DrawingUploadForm(request.POST, request.FILES)
        if form.is_valid():
            drawing = form.save(commit=False)
            drawing.organization = request.user.organization
            drawing.uploaded_by = request.user
            if not drawing.name:
                drawing.name = request.FILES["file"].name.rsplit(".", 1)[0]
            drawing.save()
            drawing.page_count = _count_pages(drawing)
            drawing.save(update_fields=["page_count"])
            return redirect("core:drawings")
    else:
        form = DrawingUploadForm()
    return render(request, "core/drawing_upload.html", {"form": form})


def _count_pages(drawing):
    """Read the page count once at upload so the viewer needn't reparse."""
    from pypdf import PdfReader

    try:
        with drawing.file.open("rb") as fh:
            return len(PdfReader(fh).pages)
    except Exception:
        # A file PdfReader can't parse still uploads; the viewer will show the
        # error. Better than losing the upload over a page count.
        return 0


@org_admin_required
@require_POST
def drawing_delete(request, pk):
    drawing = get_object_or_404(_drawings(request), pk=pk)
    drawing.file.delete(save=False)
    drawing.delete()
    return redirect("core:drawings")


@login_required
def viewer(request, pk):
    drawing = get_object_or_404(_drawings(request), pk=pk)
    return render(
        request,
        "core/viewer.html",
        {"drawing": drawing, "disciplines": request.user.organization.disciplines.all()},
    )


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


@login_required
def drawing_pdf(request, pk):
    """Serve the PDF bytes, login- and organization-checked.

    Range support is implemented by hand: Django 6.0's FileResponse doesn't
    do it, and PDF.js relies on it to fetch large CAD drawings in chunks
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
    """Stamp all notes into the PDF and hand it back as a download.

    Pre-pivot this uploaded the result back into SharePoint; the stamping
    itself (including the CAD non-zero-origin page fix) is unchanged.
    """
    if mode not in EXPORT_MODES:
        raise Http404
    drawing = get_object_or_404(_drawings(request), pk=pk)
    notes = drawing.notes.select_related("discipline", "author").all()

    with drawing.file.open("rb") as fh:
        stamped = stamp_notes(fh.read(), notes, mode=mode, document_name=drawing.name)

    filename = f"{drawing.name} ({EXPORT_MODES[mode]}).pdf"
    response = HttpResponse(stamped, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# --- Organization management (admins) ----------------------------------------


def _disciplines_section(request, form=None):
    return render(
        request,
        "core/partials/disciplines_section.html",
        {
            "disciplines": request.user.organization.disciplines.all(),
            "form": form or DisciplineForm(),
        },
    )


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


@org_admin_required
@require_POST
def invite_create(request):
    org = request.user.organization
    form = InvitationForm(org, request.POST)
    sent = False
    if form.is_valid():
        invitation = form.save(commit=False)
        invitation.organization = org
        invitation.invited_by = request.user
        invitation.save()
        send_invitation(invitation)
        form = None
        sent = True
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
def invite_revoke(request, pk):
    org = request.user.organization
    get_object_or_404(Invitation, pk=pk, organization=org, accepted_at__isnull=True).delete()
    return render(
        request,
        "core/partials/invitations_section.html",
        {
            "invitations": org.invitations.filter(accepted_at__isnull=True),
            "form": InvitationForm(org),
        },
    )


@org_admin_required
def settings(request):
    """Organization settings — disciplines only, for now."""
    return render(
        request,
        "core/settings.html",
        {"disciplines": request.user.organization.disciplines.all(), "form": DisciplineForm()},
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
    discipline = get_object_or_404(
        Discipline, pk=pk, organization=request.user.organization
    )
    if request.method == "POST":
        form = DisciplineForm(request.POST, instance=discipline)
        if form.is_valid():
            form.save()
            return _disciplines_section(request)
    else:
        form = DisciplineForm(instance=discipline)
    return render(
        request,
        "core/partials/discipline_row_edit.html",
        {"discipline": discipline, "form": form},
    )


@org_admin_required
@require_POST
def discipline_delete(request, pk):
    discipline = get_object_or_404(
        Discipline, pk=pk, organization=request.user.organization
    )
    if discipline.notes.exists():
        return render(
            request,
            "core/partials/discipline_row.html",
            {
                "discipline": discipline,
                "error": f"Bruges af {discipline.notes.count()} note(r) — kan ikke slettes.",
            },
        )
    discipline.delete()
    return _disciplines_section(request)


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


# --- Notes -------------------------------------------------------------------


def _close_and_refresh(response):
    """Tell the viewer to close the note sheet and re-fetch the pin layer."""
    response["HX-Trigger"] = json.dumps({"micki:close-sheet": True, "micki:refresh-pins": True})
    return response


def _can_edit(user, note):
    return note.author_id == user.id or user.is_org_admin


@login_required
def pins(request, pk):
    """HTMX partial: all pins for one page of a drawing."""
    drawing = get_object_or_404(_drawings(request), pk=pk)
    page = int(request.GET.get("page", 1))
    notes = drawing.notes.filter(page_number=page).select_related("discipline", "author")
    return render(request, "core/partials/pins.html", {"notes": notes})


@login_required
def notes_list(request, pk):
    """HTMX partial: every note on the drawing, for the list below the viewer."""
    drawing = get_object_or_404(_drawings(request), pk=pk)
    notes = drawing.notes.select_related("discipline", "author")
    return render(request, "core/partials/notes_list.html", {"notes": notes})


def _attach_photo(note, request):
    """Replace the note's photo with a downscaled JPEG when a new file arrived."""
    if request.FILES.get("photo"):
        note.photo.save(f"{uuid.uuid4().hex}.jpg", process_upload(request.FILES["photo"]), save=False)


@login_required
def note_new(request, pk):
    drawing = get_object_or_404(_drawings(request), pk=pk)
    if request.method == "POST":
        form = NoteForm(request.user.organization, request.POST, request.FILES)
        if form.is_valid():
            note = form.save(commit=False)
            note.drawing = drawing
            note.page_number = int(request.POST["page"])
            note.x_pct = request.POST["x"]
            note.y_pct = request.POST["y"]
            note.author = request.user
            _attach_photo(note, request)
            note.save()
            return _close_and_refresh(render(request, "core/partials/note_saved.html"))
    else:
        form = NoteForm(request.user.organization)
    context = {
        "form": form,
        "action": request.path,
        "x": request.GET.get("x", request.POST.get("x")),
        "y": request.GET.get("y", request.POST.get("y")),
        "page": request.GET.get("page", request.POST.get("page")),
    }
    return render(request, "core/partials/note_form.html", context)


@login_required
def note_detail(request, pk):
    note = get_object_or_404(
        _notes(request).select_related("discipline", "author"), pk=pk
    )
    return render(
        request,
        "core/partials/note_detail.html",
        {"note": note, "can_edit": _can_edit(request.user, note)},
    )


@login_required
def note_edit(request, pk):
    note = get_object_or_404(_notes(request), pk=pk)
    if not _can_edit(request.user, note):
        return HttpResponseForbidden()
    if request.method == "POST":
        form = NoteForm(request.user.organization, request.POST, request.FILES, instance=note)
        if form.is_valid():
            note = form.save(commit=False)
            _attach_photo(note, request)
            note.save()
            return _close_and_refresh(render(request, "core/partials/note_saved.html"))
    else:
        form = NoteForm(request.user.organization, instance=note)
    return render(request, "core/partials/note_form.html", {"form": form, "action": request.path})


@login_required
def note_photo(request, pk):
    note = get_object_or_404(_notes(request), pk=pk)
    if not note.photo:
        raise Http404
    return FileResponse(note.photo.open("rb"), content_type="image/jpeg")


@login_required
@require_POST
def note_delete(request, pk):
    note = get_object_or_404(_notes(request), pk=pk)
    if not _can_edit(request.user, note):
        return HttpResponseForbidden()
    note.delete()
    return _close_and_refresh(render(request, "core/partials/note_saved.html"))
