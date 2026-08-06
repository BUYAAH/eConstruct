from django.conf import settings
from django.db import models


class Organization(models.Model):
    """A customer tenant. Every other model here hangs off exactly one.

    This is the isolation boundary: organizations are 100% separated from
    each other, so every queryset touching the models below must filter on
    the requesting user's organization. See ROADMAP.md decision D6.

    Named Organization rather than Company because "firma"/company is
    already taken in this domain by the subcontractors working on a
    project ("Firmaer" on the project cards).
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Discipline(models.Model):
    """A trade group (faggruppe) — Konstruktion, Brand, El, VVS, Kvalitet.

    Defined per organization; the colour is what tints a note's pin on the
    drawing and its dot in the registration list.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="disciplines"
    )
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default="#0d6efd")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="unique_discipline_name_per_org"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.organization})"


class Drawing(models.Model):
    """An uploaded PDF drawing that notes get pinned to.

    Replaces the pitch-era Document, which was a pointer at a SharePoint
    item (drive_id/item_id) rather than a file we hold. We now own the
    bytes, so `file` is a plain FileField: local disk today, S3 later via
    the STORAGES setting with no model change (see storage_plan.md).

    Gets a `project` FK in phase 2 — until Project exists it belongs
    directly to the organization.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="drawings"
    )
    name = models.CharField(max_length=500)
    file = models.FileField(upload_to="drawings/%Y/%m/")
    # Read once with pypdf on upload so the viewer doesn't reparse per request.
    page_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Note(models.Model):
    """A pin-note on a drawing page, tagged with one discipline.

    Coordinates are percentages of the rendered page (origin top-left),
    so pins are zoom- and device-independent.

    Becomes Registration in phase 4, when it gains assignee, deadline and
    open/resolved status — that rename is deferred because it comes with
    those fields, unlike the Organization/Discipline renames.
    """

    drawing = models.ForeignKey(Drawing, on_delete=models.CASCADE, related_name="notes")
    page_number = models.PositiveIntegerField()
    x_pct = models.DecimalField(max_digits=6, decimal_places=3)
    y_pct = models.DecimalField(max_digits=6, decimal_places=3)
    discipline = models.ForeignKey(Discipline, on_delete=models.PROTECT, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )
    text = models.TextField()
    # Optional photo; uploads are downscaled and re-encoded to JPEG on save.
    photo = models.ImageField(upload_to="note_photos/%Y/%m/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_number", "created_at"]

    def __str__(self):
        return f"p{self.page_number} on {self.drawing}: {self.text[:40]}"
