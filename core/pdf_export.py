"""Stamp notes into a PDF so they are visible outside the app.

Two modes:
- "summary": a numbered colored dot drawn at each pin (visible in every
  viewer, incl. SharePoint's limited web preview), a sticky-note annotation
  for full PDF apps, and appended summary page(s) listing all notes.
- "inline": the note text drawn directly on the page in a small colored box
  next to each pin. Fully flattened, no annotations.
"""

from io import BytesIO

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.annotations import Text
from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

ICON_SIZE = 20  # sticky-note icon size, points
DOT_RADIUS = 9


def _hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _author_line(note):
    author = str(note.author) if note.author else "Ukendt"
    return f"{note.discipline.name} — {author}"


def _overlay(width, height, draw):
    """Render draw(canvas) onto a single transparent page of the given size."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    draw(c)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _note_xy(note, width, height):
    """Notes store pct from top-left; PDF coords are points from bottom-left.

    Returns coordinates in a 0-based space; pages whose boxes don't start at
    (0, 0) (e.g. CAD exports centered on the origin) are handled by
    translating the merged overlay / offsetting annotation rects.
    """
    x = float(note.x_pct) / 100 * width
    y = height - float(note.y_pct) / 100 * height
    return x, y


def _draw_numbered_dot(c, x, y, number, rgb):
    c.setFillColorRGB(*rgb)
    c.setStrokeColorRGB(1, 1, 1)
    c.setLineWidth(1.2)
    c.circle(x, y, DOT_RADIUS, stroke=1, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x, y - 3, str(number))


def _draw_inline_box(c, x, y, note, rgb, page_width, page_height):
    text = note.text
    lines = simpleSplit(text, "Helvetica", 7.5, 165)[:8]
    if len(simpleSplit(text, "Helvetica", 7.5, 165)) > 8:
        lines[-1] += " …"
    header = _author_line(note)
    box_w = 180
    box_h = 16 + len(lines) * 9.5

    bx = min(max(x + 12, 4), page_width - box_w - 4)
    by = min(max(y - box_h / 2, 4), page_height - box_h - 4)

    # pin dot + connector
    c.setFillColorRGB(*rgb)
    c.circle(x, y, 4, stroke=0, fill=1)
    c.setStrokeColorRGB(*rgb)
    c.setLineWidth(0.8)
    c.line(x, y, bx if bx > x else bx + box_w, by + box_h / 2)

    # box
    c.setFillColorRGB(1, 1, 1)
    c.roundRect(bx, by, box_w, box_h, 4, stroke=1, fill=1)
    c.setFillColorRGB(*rgb)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(bx + 6, by + box_h - 11, header[:48])
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.setFont("Helvetica", 7.5)
    for i, line in enumerate(lines):
        c.drawString(bx + 6, by + box_h - 21 - i * 9.5, line)


def _summary_pages(document_name, numbered_notes):
    """One or more A4-ish pages listing all notes."""
    width, height = 595, 842
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    y = height - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, f"Noter — {document_name}"[:70])
    y -= 30

    for number, note in numbered_notes:
        meta = f"{number}.  Side {note.page_number}  ·  {_author_line(note)}  ·  {note.created_at:%d %b %Y %H:%M}"
        lines = simpleSplit(note.text, "Helvetica", 10, width - 130)
        needed = 16 + len(lines) * 13 + 12
        if y - needed < 50:
            c.showPage()
            y = height - 60
        rgb = _hex_to_rgb(note.discipline.color)
        c.setFillColorRGB(*rgb)
        c.circle(58, y + 3, 4, stroke=0, fill=1)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(70, y, meta)
        y -= 16
        c.setFont("Helvetica", 10)
        c.setFillColorRGB(0.15, 0.15, 0.15)
        for line in lines:
            c.drawString(70, y, line)
            y -= 13
        y -= 12
        c.setFillColorRGB(0, 0, 0)

    c.save()
    buf.seek(0)
    return PdfReader(buf)


def stamp_notes(pdf_bytes, notes, mode="summary", document_name=""):
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)

    ordered = sorted(notes, key=lambda n: (n.page_number, n.created_at))
    numbered = [(i, n) for i, n in enumerate(ordered, start=1) if 0 < n.page_number <= len(writer.pages)]

    # group per page and merge one overlay per page
    by_page = {}
    for number, note in numbered:
        by_page.setdefault(note.page_number - 1, []).append((number, note))

    for page_index, page_notes in by_page.items():
        page = writer.pages[page_index]
        box = page.cropbox  # what viewers (and thus our percentages) show
        width, height = float(box.width), float(box.height)
        left, bottom = float(box.left), float(box.bottom)

        def draw(c, page_notes=page_notes, width=width, height=height):
            for number, note in page_notes:
                x, y = _note_xy(note, width, height)
                rgb = _hex_to_rgb(note.discipline.color)
                if mode == "inline":
                    _draw_inline_box(c, x, y, note, rgb, width, height)
                else:
                    _draw_numbered_dot(c, x, y, number, rgb)

        # translate the 0-based overlay into the page's own coordinate space
        page.merge_transformed_page(
            _overlay(width, height, draw), Transformation().translate(tx=left, ty=bottom)
        )

        if mode == "summary":
            for number, note in page_notes:
                x, y = _note_xy(note, width, height)
                x, y = x + left, y + bottom  # annotation rects use page space
                annotation = Text(
                    rect=(x + DOT_RADIUS + 2, y - ICON_SIZE / 2, x + DOT_RADIUS + 2 + ICON_SIZE, y + ICON_SIZE / 2),
                    text=note.text,
                    open=False,
                )
                annotation[NameObject("/T")] = TextStringObject(f"#{number} {_author_line(note)}")
                annotation[NameObject("/C")] = ArrayObject(
                    FloatObject(c) for c in _hex_to_rgb(note.discipline.color)
                )
                writer.add_annotation(page_number=page_index, annotation=annotation)

    if mode == "summary" and numbered:
        writer.append(_summary_pages(document_name, numbered))

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
