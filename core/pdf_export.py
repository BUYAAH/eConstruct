"""Stamp registrations into a PDF so they can leave the app.

This is how work reaches a subcontractor: they have no login (ROADMAP.md
D7), so they get a stamped drawing rather than a link.

Two modes:
- "summary": a numbered coloured dot at each pin (visible in every viewer,
  including limited web previews), a sticky-note annotation for full PDF
  apps, and appended summary page(s) listing every registration.
- "inline": the text drawn directly on the page in a small coloured box
  next to each pin. Fully flattened, no annotations.

Numbers are the registration's own per-project number (D12), not a running
count, so a dot on the page matches what people call it on site.
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


def _meta_line(reg):
    author = str(reg.author) if reg.author else "Ukendt"
    return f"{reg.discipline.name} — {reg.assigned_contractor.name} — {author}"


def _body_text(reg):
    """Subject carries the meaning; description is extra when it exists."""
    return f"{reg.subject}\n{reg.description}".strip() if reg.description else reg.subject


def _overlay(width, height, draw):
    """Render draw(canvas) onto a single transparent page of the given size."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    draw(c)
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _pin_xy(reg, width, height):
    """We store pct from top-left; PDF coords are points from bottom-left.

    Returns coordinates in a 0-based space; pages whose boxes don't start at
    (0, 0) — CAD exports centred on the origin — are handled by translating
    the merged overlay and offsetting annotation rects.
    """
    x = float(reg.x_pct) / 100 * width
    y = height - float(reg.y_pct) / 100 * height
    return x, y


def _draw_numbered_dot(c, x, y, number, rgb):
    c.setFillColorRGB(*rgb)
    c.setStrokeColorRGB(1, 1, 1)
    c.setLineWidth(1.2)
    c.circle(x, y, DOT_RADIUS, stroke=1, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x, y - 3, str(number))


def _draw_inline_box(c, x, y, reg, rgb, page_width, page_height):
    all_lines = simpleSplit(_body_text(reg), "Helvetica", 7.5, 165)
    lines = all_lines[:8]
    if len(all_lines) > 8:
        lines[-1] += " …"
    header = f"{reg.label} {_meta_line(reg)}"
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


def _summary_pages(document_name, registrations):
    """One or more A4-ish pages listing every registration."""
    width, height = 595, 842
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    y = height - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, f"Registreringer — {document_name}"[:70])
    y -= 30

    for reg in registrations:
        deadline = f"  ·  frist {reg.deadline:%d-%m-%Y}" if reg.deadline else ""
        meta = (
            f"{reg.label}  Side {reg.page_number}  ·  {_meta_line(reg)}  ·  "
            f"{reg.get_status_display()}{deadline}"
        )
        lines = simpleSplit(_body_text(reg), "Helvetica", 10, width - 130)
        needed = 16 + len(lines) * 13 + 12
        if y - needed < 50:
            c.showPage()
            y = height - 60
        c.setFillColorRGB(*_hex_to_rgb(reg.discipline.color))
        c.circle(58, y + 3, 4, stroke=0, fill=1)
        c.setFont("Helvetica-Bold", 9)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(70, y, meta[:95])
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


def stamp_registrations(pdf_bytes, registrations, mode="summary", document_name=""):
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)

    ordered = sorted(
        (r for r in registrations if r.page_number and r.x_pct is not None),
        key=lambda r: (r.page_number, r.number),
    )
    on_page = [r for r in ordered if 0 < r.page_number <= len(writer.pages)]

    by_page = {}
    for reg in on_page:
        by_page.setdefault(reg.page_number - 1, []).append(reg)

    for page_index, page_regs in by_page.items():
        page = writer.pages[page_index]
        box = page.cropbox  # what viewers — and thus our percentages — show
        width, height = float(box.width), float(box.height)
        left, bottom = float(box.left), float(box.bottom)

        def draw(c, page_regs=page_regs, width=width, height=height):
            for reg in page_regs:
                x, y = _pin_xy(reg, width, height)
                rgb = _hex_to_rgb(reg.discipline.color)
                if mode == "inline":
                    _draw_inline_box(c, x, y, reg, rgb, width, height)
                else:
                    _draw_numbered_dot(c, x, y, reg.number, rgb)

        # Translate the 0-based overlay into the page's own coordinate space.
        page.merge_transformed_page(
            _overlay(width, height, draw), Transformation().translate(tx=left, ty=bottom)
        )

        if mode == "summary":
            for reg in page_regs:
                x, y = _pin_xy(reg, width, height)
                x, y = x + left, y + bottom  # annotation rects use page space
                annotation = Text(
                    rect=(
                        x + DOT_RADIUS + 2, y - ICON_SIZE / 2,
                        x + DOT_RADIUS + 2 + ICON_SIZE, y + ICON_SIZE / 2,
                    ),
                    text=_body_text(reg),
                    open=False,
                )
                annotation[NameObject("/T")] = TextStringObject(f"{reg.label} {_meta_line(reg)}")
                annotation[NameObject("/C")] = ArrayObject(
                    FloatObject(c) for c in _hex_to_rgb(reg.discipline.color)
                )
                writer.add_annotation(page_number=page_index, annotation=annotation)

    if mode == "summary" and on_page:
        writer.append(_summary_pages(document_name, on_page))

    out = BytesIO()
    writer.write(out)
    return out.getvalue()
