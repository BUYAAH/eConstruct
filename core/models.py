from django.conf import settings
from django.db import models


class Company(models.Model):
    """A customer organisation. Created manually in Django admin for v0.1."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    # Entra tenant id; set when known so SSO can match new users to the company.
    ms_tenant_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name


class Layer(models.Model):
    """A note audience (e.g. Sales, Technicians), defined per company."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="layers")
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default="#0d6efd")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_layer_name_per_company"),
        ]

    def __str__(self):
        return f"{self.name} ({self.company})"


class FolderLink(models.Model):
    """A SharePoint folder a company admin selected for annotation."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="folder_links")
    drive_id = models.CharField(max_length=255)
    item_id = models.CharField(max_length=255)
    display_path = models.CharField(max_length=500)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "drive_id", "item_id"], name="unique_folder_per_company"),
        ]

    def __str__(self):
        return self.display_path


class Document(models.Model):
    """Registry row for a SharePoint PDF, created on first open.

    Anchors notes to the file's stable (drive_id, item_id) identity.
    No file contents are stored.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="documents")
    folder_link = models.ForeignKey(
        FolderLink, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    drive_id = models.CharField(max_length=255)
    item_id = models.CharField(max_length=255)
    name = models.CharField(max_length=500)
    etag = models.CharField(max_length=255, blank=True)
    # Set when the file can no longer be found in SharePoint; notes are kept.
    is_missing = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "drive_id", "item_id"], name="unique_document_per_company"),
        ]

    def __str__(self):
        return self.name


class Note(models.Model):
    """A pin-note on a document page, targeted at one layer.

    Coordinates are percentages of the rendered page (origin top-left),
    so pins are zoom- and device-independent.
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="notes")
    page_number = models.PositiveIntegerField()
    x_pct = models.DecimalField(max_digits=6, decimal_places=3)
    y_pct = models.DecimalField(max_digits=6, decimal_places=3)
    layer = models.ForeignKey(Layer, on_delete=models.PROTECT, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="notes"
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_number", "created_at"]

    def __str__(self):
        return f"p{self.page_number} on {self.document}: {self.text[:40]}"
