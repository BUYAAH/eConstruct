from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from .base import BaseModel


class Organization(BaseModel):
    """A customer tenant. Everything else here hangs off exactly one.

    This is the isolation boundary: organizations are 100% separated from
    each other (ROADMAP.md D6), so every queryset touching the models below
    must filter on the requesting user's organization. There is deliberately
    no model anywhere that is shared between two organizations.

    Named Organization rather than Company because "firma" is already taken
    in this domain by Contractor — the subcontractors on a project.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Discipline(BaseModel):
    """A trade group (faggruppe) — Konstruktion, Brand, El, VVS, Kvalitet.

    Defined per organization; the colour tints the pin on the drawing and
    the dot in the registration list.
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
        return self.name


class Contractor(BaseModel):
    """A subcontractor firm — the "Firmaer" on a project card.

    Owned by the organization and has no login (ROADMAP.md D7). Work is
    assigned to a contractor, and they receive it as an exported PDF or an
    email; they never get an account, which is what keeps tenancy sealed.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="contractors"
    )
    name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="unique_contractor_name_per_org"
            ),
        ]

    def __str__(self):
        return self.name


class ProjectQuerySet(models.QuerySet):
    def with_stats(self):
        """The counts every project card shows, in one query.

        distinct=True on each: contractors is a M2M and registrations a
        reverse FK, so joining both multiplies rows and the counts would be
        each other's multiple without it.
        """
        return self.annotate(
            drawing_count=models.Count("drawings", distinct=True),
            contractor_count=models.Count("contractors", distinct=True),
            registration_count=models.Count("registrations", distinct=True),
            open_count=models.Count(
                "registrations",
                filter=models.Q(registrations__status=Registration.OPEN),
                distinct=True,
            ),
            approved_count=models.Count(
                "registrations",
                filter=models.Q(registrations__status=Registration.APPROVED),
                distinct=True,
            ),
        )


class Project(BaseModel):
    """A building site. The spine of the app — drawings and registrations
    both hang off a project, and access is granted per project (D9)."""

    objects = ProjectQuerySet.as_manager()

    PLANNED = "planned"
    ACTIVE = "active"
    DONE = "done"
    STATUS_CHOICES = [
        (PLANNED, "Planlagt"),
        (ACTIVE, "Aktiv"),
        (DONE, "Afsluttet"),
    ]
    # Bootstrap contextual class per status, so templates don't branch.
    STATUS_CLASSES = {PLANNED: "secondary", ACTIVE: "success", DONE: "secondary"}

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    case_no = models.CharField("sagsnr.", max_length=50, blank=True)
    address = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)

    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_projects",
    )
    # Explicit membership (D9): a user sees only the projects they're on.
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="projects"
    )
    contractors = models.ManyToManyField(Contractor, blank=True, related_name="projects")

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            # Slugs are per organization, not global — two customers may both
            # have a "Sygehus Nord".
            models.UniqueConstraint(
                fields=["organization", "slug"], name="unique_project_slug_per_org"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def status_class(self):
        return self.STATUS_CLASSES.get(self.status, "secondary")

    @property
    def progress(self):
        """Share of registrations signed off, as a whole percent.

        Deliberately derived rather than a field someone maintains by hand —
        a manually-set percentage is the first thing to go stale on a
        project board. A project with no registrations reads 0, not 100:
        nothing has been verified yet.

        Uses the annotations from with_stats() when they're there; falls back
        to two queries otherwise. Without that, a page of cards would issue
        two extra queries per card.
        """
        total = getattr(self, "registration_count", None)
        approved = getattr(self, "approved_count", None)
        if total is None or approved is None:
            total = self.registrations.count()
            approved = self.registrations.filter(status=Registration.APPROVED).count()
        if not total:
            return 0
        return round(approved / total * 100)

    def visible_to(self, user):
        """Membership OR org admin. Admins can reach every project in their
        own organization so a site never becomes unreachable when its only
        member leaves."""
        return user.organization_id == self.organization_id and (
            user.is_org_admin or self.members.filter(pk=user.pk).exists()
        )


class Drawing(BaseModel):
    """An uploaded PDF drawing that registrations get pinned to.

    We own the bytes, so this is a plain FileField: local disk today, S3
    later via the STORAGES setting with no model change.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="drawings")
    name = models.CharField(max_length=500)
    file = models.FileField(upload_to="drawings/%Y/%m/")
    # Read once with pypdf on upload so the viewer needn't reparse per request.
    page_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def organization_id(self):
        return self.project.organization_id


class Registration(BaseModel):
    """A defect or observation on site — the actual domain object.

    Usually created by tapping a point on a drawing, which is where the
    page/coordinate fields come from; but a registration can exist without a
    drawing (D3), so those four fields travel together and are all nullable.

    Numbered sequentially within its project (D12) because that is how one
    gets referred to on site and in reports.
    """

    OPEN = "open"
    RESOLVED = "resolved"
    APPROVED = "approved"
    STATUS_CHOICES = [
        (OPEN, "Åben"),
        (RESOLVED, "Løst"),
        (APPROVED, "Godkendt"),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="registrations")
    number = models.PositiveIntegerField(editable=False)

    # Pin location. All four are null together for a registration with no drawing.
    drawing = models.ForeignKey(
        Drawing, null=True, blank=True, on_delete=models.SET_NULL, related_name="registrations"
    )
    page_number = models.PositiveIntegerField(null=True, blank=True)
    # Percentages of the rendered page, origin top-left, so pins are zoom-
    # and device-independent.
    x_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    y_pct = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)

    discipline = models.ForeignKey(
        Discipline, on_delete=models.PROTECT, related_name="registrations"
    )
    subject = models.CharField("emne", max_length=200)
    description = models.TextField("beskrivelse", blank=True)

    # The firm owes the fix; the responsible person chases it (D11).
    assigned_contractor = models.ForeignKey(
        Contractor, on_delete=models.PROTECT, related_name="registrations"
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL, related_name="responsible_for",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL, related_name="registrations",
    )

    deadline = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=OPEN)
    resolved_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "number"], name="unique_registration_number_per_project"
            ),
        ]

    def __str__(self):
        return f"#{self.number:03d} {self.subject}"

    @property
    def label(self):
        return f"#{self.number:03d}"

    @property
    def is_open(self):
        return self.status == self.OPEN

    @property
    def overdue(self):
        """Derived, never stored (D8) — a stored flag would need a nightly job
        and would be wrong between runs."""
        return bool(
            self.deadline and self.status != self.APPROVED
            and self.deadline < timezone.localdate()
        )

    @property
    def has_pin(self):
        return self.drawing_id is not None and self.x_pct is not None

    def save(self, *args, **kwargs):
        if self.number is None:
            self._assign_number()
        super().save(*args, **kwargs)

    def _assign_number(self):
        """Take the next number within the project, under a lock on the
        project row so two concurrent creates can't claim the same one.

        select_for_update is a no-op on SQLite (writes are serialized
        anyway) but is what makes this correct once we move to Postgres.
        """
        with transaction.atomic():
            Project.objects.select_for_update().filter(pk=self.project_id).first()
            highest = Registration.objects.filter(project_id=self.project_id).aggregate(
                models.Max("number")
            )["number__max"]
            self.number = (highest or 0) + 1

    def mark_resolved(self):
        self.status = self.RESOLVED
        self.resolved_at = timezone.now()
        self.approved_at = None
        self.save(update_fields=["status", "resolved_at", "approved_at", "updated_at"])

    def mark_approved(self):
        self.status = self.APPROVED
        self.approved_at = timezone.now()
        self.save(update_fields=["status", "approved_at", "updated_at"])

    def reopen(self):
        self.status = self.OPEN
        self.resolved_at = None
        self.approved_at = None
        self.save(update_fields=["status", "resolved_at", "approved_at", "updated_at"])


class RegistrationPhoto(BaseModel):
    """A site photo on a registration. Several per registration.

    Both renditions are generated at upload (core/images.py): the full image
    is downscaled from the phone original, and the thumbnail keeps list views
    fast on mobile data. Nothing is served directly from MEDIA_ROOT.
    """

    registration = models.ForeignKey(
        Registration, on_delete=models.CASCADE, related_name="photos"
    )
    image = models.ImageField(upload_to="registrations/%Y/%m/")
    thumbnail = models.ImageField(upload_to="registrations/%Y/%m/thumbs/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Foto til {self.registration}"
