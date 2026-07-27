from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseForbidden, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import json
import uuid

from django.contrib.auth import get_user_model
from django.http import FileResponse

from . import graph
from .forms import LayerForm, NoteForm
from .images import process_upload
from .models import Document, FolderLink, Layer, Note
from .pdf_export import stamp_notes


def company_admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_company_admin:
            return HttpResponseForbidden("Company admin access required.")
        return view(request, *args, **kwargs)

    return wrapper


@login_required
def home(request):
    folder_links = request.user.company.folder_links.all() if request.user.company else []
    return render(request, "core/home.html", {"folder_links": folder_links})


# --- Folder picking (admin) -------------------------------------------------


@company_admin_required
def folder_picker(request):
    return render(request, "core/folder_picker.html")


@company_admin_required
def browse(request):
    """HTMX partial: drill down sites -> document libraries -> folders."""
    site_id = request.GET.get("site_id")
    drive_id = request.GET.get("drive_id")
    item_id = request.GET.get("item_id", "root")
    path = request.GET.get("path", "")

    try:
        if drive_id:
            items = graph.list_children(request.user, drive_id, item_id)
            folders = [i for i in items if "folder" in i]
            pdf_count = sum(
                1 for i in items if "file" in i and i["name"].lower().endswith(".pdf")
            )
            return render(
                request,
                "core/partials/browse_folders.html",
                {
                    "folders": folders,
                    "pdf_count": pdf_count,
                    "drive_id": drive_id,
                    "item_id": item_id,
                    "path": path,
                },
            )
        if site_id:
            drives = graph.list_drives(request.user, site_id)
            return render(
                request, "core/partials/browse_drives.html", {"drives": drives, "path": path}
            )
        sites = graph.list_sites(request.user)
        return render(request, "core/partials/browse_sites.html", {"sites": sites})
    except graph.GraphError as e:
        return render(request, "core/partials/graph_error.html", {"error": e}, status=200)


@company_admin_required
@require_POST
def link_folder(request):
    drive_id = request.POST["drive_id"]
    item_id = request.POST["item_id"]
    display_path = request.POST["display_path"]

    # "root" is an alias, not a stable id — resolve it before storing.
    if item_id == "root":
        item_id = graph.get_item(request.user, drive_id)["id"]

    FolderLink.objects.get_or_create(
        company=request.user.company,
        drive_id=drive_id,
        item_id=item_id,
        defaults={"display_path": display_path, "added_by": request.user},
    )
    return redirect("core:home")


@company_admin_required
@require_POST
def unlink_folder(request, pk):
    link = get_object_or_404(FolderLink, pk=pk, company=request.user.company)
    link.delete()
    return redirect("core:home")


# --- Document browsing (members) --------------------------------------------


@login_required
def folder_detail(request, pk):
    """List a linked folder's contents; navigate subfolders via ?item_id."""
    link = get_object_or_404(FolderLink, pk=pk, company=request.user.company)
    item_id = request.GET.get("item_id", link.item_id)

    context = {"link": link, "item_id": item_id, "at_root": item_id == link.item_id}
    try:
        items = graph.list_children(request.user, link.drive_id, item_id)
        context["folders"] = [i for i in items if "folder" in i]
        context["pdfs"] = [
            i for i in items if "file" in i and i["name"].lower().endswith(".pdf")
        ]
    except graph.GraphError as e:
        context["graph_error"] = e

    template = (
        "core/partials/folder_items.html" if request.headers.get("HX-Request") else "core/folder_detail.html"
    )
    return render(request, template, context)


@login_required
def open_document(request, pk, item_id):
    """Get-or-create the Document registry row for a PDF, then open the viewer."""
    link = get_object_or_404(FolderLink, pk=pk, company=request.user.company)
    try:
        item = graph.get_item(request.user, link.drive_id, item_id)
    except graph.GraphError:
        return render(request, "core/document_missing.html", status=404)

    document, _ = Document.objects.get_or_create(
        company=request.user.company,
        drive_id=link.drive_id,
        item_id=item["id"],
        defaults={"folder_link": link, "name": item["name"], "etag": item.get("eTag", "")},
    )
    if document.name != item["name"] or document.is_missing:
        document.name = item["name"]
        document.is_missing = False
        document.save()
    return redirect("core:viewer", pk=document.pk)


@login_required
def viewer(request, pk):
    document = get_object_or_404(Document, pk=pk, company=request.user.company)
    layers = request.user.company.layers.all()
    return render(request, "core/viewer.html", {"document": document, "layers": layers})


# --- Company management (admins) ---------------------------------------------


def _layers_section(request, form=None):
    return render(
        request,
        "core/partials/layers_section.html",
        {"layers": request.user.company.layers.all(), "form": form or LayerForm()},
    )


@company_admin_required
def manage(request):
    users = request.user.company.users.order_by("-is_active", "-is_company_admin", "first_name")
    return render(
        request,
        "core/manage.html",
        {
            "layers": request.user.company.layers.all(),
            "form": LayerForm(),
            "users": users,
        },
    )


@company_admin_required
@require_POST
def layer_create(request):
    form = LayerForm(request.POST)
    if form.is_valid():
        layer = form.save(commit=False)
        layer.company = request.user.company
        layer.save()
        form = None
    return _layers_section(request, form)


@company_admin_required
def layer_edit(request, pk):
    layer = get_object_or_404(Layer, pk=pk, company=request.user.company)
    if request.method == "POST":
        form = LayerForm(request.POST, instance=layer)
        if form.is_valid():
            form.save()
            return _layers_section(request)
    else:
        form = LayerForm(instance=layer)
    return render(request, "core/partials/layer_row_edit.html", {"layer": layer, "form": form})


@company_admin_required
@require_POST
def layer_delete(request, pk):
    layer = get_object_or_404(Layer, pk=pk, company=request.user.company)
    if layer.notes.exists():
        return render(
            request,
            "core/partials/layer_row.html",
            {"layer": layer, "error": f"In use by {layer.notes.count()} note(s) — can't delete."},
        )
    layer.delete()
    return _layers_section(request)


@company_admin_required
@require_POST
def user_toggle(request, pk, field):
    if field not in ("is_active", "is_company_admin"):
        raise Http404
    target = get_object_or_404(get_user_model(), pk=pk, company=request.user.company)
    if target == request.user:
        return render(
            request,
            "core/partials/user_row.html",
            {"u": target, "error": "You can't change your own access."},
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
    return note.author_id == user.id or user.is_company_admin


@login_required
def pins(request, pk):
    """HTMX partial: all pins for one page of a document."""
    document = get_object_or_404(Document, pk=pk, company=request.user.company)
    page = int(request.GET.get("page", 1))
    notes = document.notes.filter(page_number=page).select_related("layer", "author")
    return render(request, "core/partials/pins.html", {"notes": notes})


@login_required
def notes_list(request, pk):
    """HTMX partial: every note on the document, grouped for the list below the viewer."""
    document = get_object_or_404(Document, pk=pk, company=request.user.company)
    notes = document.notes.select_related("layer", "author")
    return render(request, "core/partials/notes_list.html", {"notes": notes})


def _attach_photo(note, request):
    """Replace the note's photo with a downscaled JPEG when a new file arrived."""
    if request.FILES.get("photo"):
        note.photo.save(f"{uuid.uuid4().hex}.jpg", process_upload(request.FILES["photo"]), save=False)


@login_required
def note_new(request, pk):
    document = get_object_or_404(Document, pk=pk, company=request.user.company)
    if request.method == "POST":
        form = NoteForm(request.user.company, request.POST, request.FILES)
        if form.is_valid():
            note = form.save(commit=False)
            note.document = document
            note.page_number = int(request.POST["page"])
            note.x_pct = request.POST["x"]
            note.y_pct = request.POST["y"]
            note.author = request.user
            _attach_photo(note, request)
            note.save()
            return _close_and_refresh(render(request, "core/partials/note_saved.html"))
    else:
        form = NoteForm(request.user.company)
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
        Note.objects.select_related("layer", "author"), pk=pk, document__company=request.user.company
    )
    return render(
        request,
        "core/partials/note_detail.html",
        {"note": note, "can_edit": _can_edit(request.user, note)},
    )


@login_required
def note_edit(request, pk):
    note = get_object_or_404(Note, pk=pk, document__company=request.user.company)
    if not _can_edit(request.user, note):
        return HttpResponseForbidden()
    if request.method == "POST":
        form = NoteForm(request.user.company, request.POST, request.FILES, instance=note)
        if form.is_valid():
            note = form.save(commit=False)
            _attach_photo(note, request)
            note.save()
            return _close_and_refresh(render(request, "core/partials/note_saved.html"))
    else:
        form = NoteForm(request.user.company, instance=note)
    return render(request, "core/partials/note_form.html", {"form": form, "action": request.path})


@login_required
def note_photo(request, pk):
    note = get_object_or_404(Note, pk=pk, document__company=request.user.company)
    if not note.photo:
        raise Http404
    return FileResponse(note.photo.open("rb"), content_type="image/jpeg")


@login_required
@require_POST
def note_delete(request, pk):
    note = get_object_or_404(Note, pk=pk, document__company=request.user.company)
    if not _can_edit(request.user, note):
        return HttpResponseForbidden()
    note.delete()
    return _close_and_refresh(render(request, "core/partials/note_saved.html"))


EXPORT_MODES = {"summary": "annotated", "inline": "inline notes"}


@login_required
@require_POST
def export_document(request, pk, mode):
    """Stamp all notes into the PDF and upload it next to the original in
    SharePoint as '<name> (<suffix>).pdf' (replaced on re-export)."""
    if mode not in EXPORT_MODES:
        raise Http404
    document = get_object_or_404(Document, pk=pk, company=request.user.company)
    notes = document.notes.select_related("layer", "author").all()
    try:
        original = graph.stream_content(request.user, document.drive_id, document.item_id).content
        stamped = stamp_notes(original, notes, mode=mode, document_name=document.name)
        item = graph.get_item(request.user, document.drive_id, document.item_id)
        parent_id = item["parentReference"]["id"]
        stem = document.name[:-4] if document.name.lower().endswith(".pdf") else document.name
        result = graph.upload_file(
            request.user, document.drive_id, parent_id, f"{stem} ({EXPORT_MODES[mode]}).pdf", stamped
        )
    except graph.GraphError as e:
        return render(request, "core/partials/export_result.html", {"error": e})
    return render(
        request,
        "core/partials/export_result.html",
        {"item": result, "note_count": len(notes)},
    )


@login_required
def document_pdf(request, pk):
    """Stream the PDF bytes from SharePoint through us, so the browser never
    needs a Graph token. Range headers pass through for PDF.js chunking."""
    document = get_object_or_404(Document, pk=pk, company=request.user.company)
    try:
        upstream = graph.stream_content(
            request.user,
            document.drive_id,
            document.item_id,
            range_header=request.headers.get("Range"),
        )
    except graph.GraphError as e:
        if e.status_code == 404 and not document.is_missing:
            document.is_missing = True
            document.save()
        raise Http404("PDF not available from SharePoint")

    response = StreamingHttpResponse(
        upstream.iter_content(chunk_size=64 * 1024),
        content_type="application/pdf",
        status=upstream.status_code,  # 200, or 206 for range responses
    )
    for header in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if header in upstream.headers:
            response[header] = upstream.headers[header]
    return response
