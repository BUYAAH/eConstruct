"""Tests for the parts that are expensive to get wrong.

Most of this is isolation. Organizations are 100% separated (ROADMAP.md D6)
and project access is by explicit membership (D9), so a missing filter is a
data leak rather than a cosmetic bug — that is what these assert.
"""

import atexit
import shutil
import tempfile
from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Invitation
from core.models import (
    Contractor, Discipline, Drawing, Organization, Project, Registration,
    RegistrationPhoto,
)

User = get_user_model()


def _one_page_pdf():
    """A real single-page PDF.

    Built with pypdf rather than hand-written bytes: a literal without a
    proper xref/EOF parses as zero pages, which would quietly exercise the
    upload view's error path instead of its happy path.
    """
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _tiny_jpeg():
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (900, 600), "#888").save(buffer, "JPEG")
    return buffer.getvalue()


MINIMAL_PDF = _one_page_pdf()

# Uploads go to a throwaway directory: the database rolls back between tests
# but the filesystem does not, so without this a test run leaves junk in the
# project's media/ and the delete tests interfere with the rest.
_TEST_MEDIA = tempfile.mkdtemp(prefix="micki-test-media-")
atexit.register(shutil.rmtree, _TEST_MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class MediaTestCase(TestCase):
    """Base for anything that writes a file. Subclasses inherit the override."""


def make_org(slug, name=None):
    """One organization with an admin, a member, a discipline, a contractor,
    a project (both users on it), a drawing and one registration."""
    org = Organization.objects.create(name=name or slug.title(), slug=slug)
    discipline = Discipline.objects.create(organization=org, name="El", color="#0d6efd")
    contractor = Contractor.objects.create(organization=org, name=f"{slug} El A/S")
    admin = User.objects.create_user(
        username=f"admin@{slug}.dk", password="pw-for-tests-123",
        organization=org, is_org_admin=True,
    )
    member = User.objects.create_user(
        username=f"member@{slug}.dk", password="pw-for-tests-123", organization=org,
    )
    project = Project.objects.create(organization=org, name=f"{slug} projekt", slug=f"{slug}-projekt")
    project.members.set([admin, member])
    project.contractors.set([contractor])

    drawing = Drawing.objects.create(
        project=project, name=f"{slug} tegning",
        file=SimpleUploadedFile(f"{slug}.pdf", MINIMAL_PDF, content_type="application/pdf"),
        page_count=1,
    )
    registration = Registration.objects.create(
        project=project, drawing=drawing, page_number=1, x_pct=10, y_pct=10,
        discipline=discipline, subject=f"fejl i {slug}",
        assigned_contractor=contractor, author=admin,
    )
    return {
        "org": org, "admin": admin, "member": member, "project": project,
        "drawing": drawing, "registration": registration,
        "discipline": discipline, "contractor": contractor,
    }


class TenantIsolationTests(MediaTestCase):
    """Org A must not see or touch anything belonging to org B."""

    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("alpha")
        cls.b = make_org("beta")

    def setUp(self):
        self.client.force_login(self.a["admin"])

    def test_cannot_open_another_orgs_project(self):
        for name in ("core:project_detail", "core:project_edit", "core:registration_new"):
            with self.subTest(url=name):
                response = self.client.get(reverse(name, args=[self.b["project"].slug]))
                self.assertEqual(response.status_code, 404)

    def test_cannot_open_another_orgs_drawing(self):
        for name in ("core:viewer", "core:drawing_pdf", "core:pins", "core:drawing_registrations"):
            with self.subTest(url=name):
                response = self.client.get(reverse(name, args=[self.b["drawing"].pk]))
                self.assertEqual(response.status_code, 404)

    def test_cannot_read_another_orgs_registration(self):
        response = self.client.get(
            reverse("core:registration_detail", args=[self.b["registration"].pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_cannot_change_another_orgs_registration_status(self):
        response = self.client.post(
            reverse("core:registration_status", args=[self.b["registration"].pk, "resolve"])
        )
        self.assertEqual(response.status_code, 404)
        self.b["registration"].refresh_from_db()
        self.assertEqual(self.b["registration"].status, Registration.OPEN)

    def test_cannot_delete_another_orgs_registration(self):
        response = self.client.post(
            reverse("core:registration_delete", args=[self.b["registration"].pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Registration.objects.filter(pk=self.b["registration"].pk).exists())

    def test_cannot_export_another_orgs_drawing(self):
        response = self.client.get(
            reverse("core:export_drawing", args=[self.b["drawing"].pk, "summary"])
        )
        self.assertEqual(response.status_code, 404)

    def test_cannot_edit_another_orgs_discipline_or_contractor(self):
        self.assertEqual(
            self.client.get(
                reverse("core:discipline_edit", args=[self.b["discipline"].pk])
            ).status_code,
            404,
        )
        self.client.post(reverse("core:contractor_delete", args=[self.b["contractor"].pk]))
        self.assertTrue(Contractor.objects.filter(pk=self.b["contractor"].pk).exists())

    def test_cannot_toggle_another_orgs_user(self):
        response = self.client.post(
            reverse("core:user_toggle", args=[self.b["admin"].pk, "is_active"])
        )
        self.assertEqual(response.status_code, 404)

    def test_lists_show_only_own_organization(self):
        response = self.client.get(reverse("core:projects"))
        self.assertContains(response, "alpha projekt")
        self.assertNotContains(response, "beta projekt")

        response = self.client.get(reverse("core:registrations"))
        self.assertContains(response, "fejl i alpha")
        self.assertNotContains(response, "fejl i beta")

    def test_registration_form_offers_only_own_project_contractors(self):
        from core.forms import RegistrationForm

        form = RegistrationForm(self.a["project"])
        self.assertNotIn(self.b["contractor"], form.fields["assigned_contractor"].queryset)
        self.assertNotIn(self.b["discipline"], form.fields["discipline"].queryset)
        self.assertNotIn(self.b["member"], form.fields["responsible"].queryset)

    def test_cannot_pin_a_registration_to_another_projects_drawing(self):
        """A posted drawing id from another project is ignored, not honoured."""
        self.client.post(
            reverse("core:registration_new", args=[self.a["project"].slug]) + "?x=1",
            {
                "subject": "forsøg", "discipline": self.a["discipline"].pk,
                "assigned_contractor": self.a["contractor"].pk,
                "drawing": self.b["drawing"].pk, "page": 1, "x": "10", "y": "10",
            },
        )
        created = Registration.objects.get(subject="forsøg")
        self.assertIsNone(created.drawing)


class ProjectMembershipTests(MediaTestCase):
    """D9 — a plain member sees only the projects they're on."""

    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("alpha")
        cls.outsider = User.objects.create_user(
            username="outsider@alpha.dk", password="pw-for-tests-123",
            organization=cls.a["org"],
        )

    def test_non_member_cannot_reach_the_project(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("core:project_detail", args=[self.a["project"].slug]))
        self.assertEqual(response.status_code, 404)

    def test_non_member_cannot_reach_its_drawings_or_registrations(self):
        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(reverse("core:viewer", args=[self.a["drawing"].pk])).status_code, 404
        )
        self.assertEqual(
            self.client.get(
                reverse("core:registration_detail", args=[self.a["registration"].pk])
            ).status_code,
            404,
        )

    def test_member_can(self):
        self.client.force_login(self.a["member"])
        self.assertEqual(
            self.client.get(
                reverse("core:project_detail", args=[self.a["project"].slug])
            ).status_code,
            200,
        )

    def test_org_admin_reaches_projects_they_are_not_a_member_of(self):
        """Otherwise a site becomes unreachable when its last member leaves."""
        self.a["project"].members.remove(self.a["admin"])
        self.client.force_login(self.a["admin"])
        self.assertEqual(
            self.client.get(
                reverse("core:project_detail", args=[self.a["project"].slug])
            ).status_code,
            200,
        )

    def test_creator_is_added_as_a_member(self):
        self.client.force_login(self.a["admin"])
        self.client.post(
            reverse("core:project_create"),
            {"name": "Nyt Byggeri", "status": Project.ACTIVE},
        )
        project = Project.objects.get(name="Nyt Byggeri")
        self.assertIn(self.a["admin"], project.members.all())


class NumberingTests(MediaTestCase):
    """D12 — sequential per project, independent between projects."""

    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("alpha")
        cls.b = make_org("beta")

    def _add(self, fixture, subject):
        return Registration.objects.create(
            project=fixture["project"], discipline=fixture["discipline"],
            subject=subject, assigned_contractor=fixture["contractor"],
        )

    def test_numbers_increment_within_a_project(self):
        self.assertEqual(self.a["registration"].number, 1)
        self.assertEqual(self._add(self.a, "to").number, 2)
        self.assertEqual(self._add(self.a, "tre").number, 3)

    def test_numbering_is_independent_per_project(self):
        self.assertEqual(self.a["registration"].number, 1)
        self.assertEqual(self.b["registration"].number, 1)

    def test_number_survives_a_later_save(self):
        registration = self._add(self.a, "to")
        registration.subject = "ændret"
        registration.save()
        registration.refresh_from_db()
        self.assertEqual(registration.number, 2)

    def test_label_is_zero_padded(self):
        self.assertEqual(self.a["registration"].label, "#001")


class WorkflowTests(MediaTestCase):
    """D8 — Åben → Løst → Godkendt."""

    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("alpha")

    def test_member_can_resolve(self):
        self.client.force_login(self.a["member"])
        self.client.post(
            reverse("core:registration_status", args=[self.a["registration"].pk, "resolve"])
        )
        self.a["registration"].refresh_from_db()
        self.assertEqual(self.a["registration"].status, Registration.RESOLVED)
        self.assertIsNotNone(self.a["registration"].resolved_at)

    def test_member_cannot_approve_someone_elses_registration(self):
        """A fix must not be signed off by the hand that made it."""
        self.client.force_login(self.a["member"])
        response = self.client.post(
            reverse("core:registration_status", args=[self.a["registration"].pk, "approve"])
        )
        self.assertEqual(response.status_code, 403)
        self.a["registration"].refresh_from_db()
        self.assertEqual(self.a["registration"].status, Registration.OPEN)

    def test_author_can_approve(self):
        self.client.force_login(self.a["admin"])  # the fixture's author
        self.client.post(
            reverse("core:registration_status", args=[self.a["registration"].pk, "approve"])
        )
        self.a["registration"].refresh_from_db()
        self.assertEqual(self.a["registration"].status, Registration.APPROVED)
        self.assertIsNotNone(self.a["registration"].approved_at)

    def test_reopen_clears_the_timestamps(self):
        registration = self.a["registration"]
        registration.mark_resolved()
        registration.mark_approved()
        registration.reopen()
        registration.refresh_from_db()
        self.assertEqual(registration.status, Registration.OPEN)
        self.assertIsNone(registration.resolved_at)
        self.assertIsNone(registration.approved_at)

    def test_overdue_is_derived_and_ignores_approved(self):
        registration = self.a["registration"]
        registration.deadline = timezone.localdate() - timedelta(days=1)
        registration.save()
        self.assertTrue(registration.overdue)
        registration.mark_approved()
        self.assertFalse(registration.overdue)

    def test_unknown_action_is_404(self):
        self.client.force_login(self.a["admin"])
        response = self.client.post(
            reverse("core:registration_status", args=[self.a["registration"].pk, "sabotage"])
        )
        self.assertEqual(response.status_code, 404)


class ProgressTests(MediaTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("alpha")

    def test_empty_project_reads_zero_not_complete(self):
        empty = Project.objects.create(
            organization=self.a["org"], name="Tom", slug="tom"
        )
        self.assertEqual(empty.progress, 0)

    def test_progress_is_the_approved_share(self):
        project = self.a["project"]
        for i in range(3):
            Registration.objects.create(
                project=project, discipline=self.a["discipline"], subject=f"r{i}",
                assigned_contractor=self.a["contractor"],
            )
        # 4 registrations total; approve one.
        self.a["registration"].mark_approved()
        self.assertEqual(project.progress, 25)


class PermissionTests(MediaTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("alpha")

    def test_admin_only_pages_reject_plain_members(self):
        self.client.force_login(self.a["member"])
        for name, args in [
            ("core:users", []), ("core:settings", []),
            ("core:project_create", []),
            ("core:drawing_upload", [self.a["project"].slug]),
            ("core:project_edit", [self.a["project"].slug]),
        ]:
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)

    def test_member_can_create_a_registration(self):
        self.client.force_login(self.a["member"])
        response = self.client.post(
            reverse("core:registration_new", args=[self.a["project"].slug]),
            {
                "subject": "ny fejl", "discipline": self.a["discipline"].pk,
                "assigned_contractor": self.a["contractor"].pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Registration.objects.filter(subject="ny fejl").exists())

    def test_member_cannot_delete_someone_elses_registration(self):
        self.client.force_login(self.a["member"])
        response = self.client.post(
            reverse("core:registration_delete", args=[self.a["registration"].pk])
        )
        self.assertEqual(response.status_code, 403)


class DrawingTests(MediaTestCase):
    # Per-test, not setUpTestData: these delete and add files, and the
    # filesystem does not roll back with the transaction.
    def setUp(self):
        self.a = make_org("alpha")
        self.client.force_login(self.a["admin"])

    def test_upload_sets_page_count_and_defaults_name_to_filename(self):
        response = self.client.post(
            reverse("core:drawing_upload", args=[self.a["project"].slug]),
            {"name": "", "file": SimpleUploadedFile("Plan E1.pdf", MINIMAL_PDF)},
        )
        self.assertEqual(response.status_code, 302)
        drawing = Drawing.objects.get(name="Plan E1")
        self.assertEqual(drawing.page_count, 1)
        self.assertEqual(drawing.project, self.a["project"])

    def test_non_pdf_upload_is_rejected(self):
        response = self.client.post(
            reverse("core:drawing_upload", args=[self.a["project"].slug]),
            {"name": "", "file": SimpleUploadedFile("photo.jpg", b"not a pdf")},
        )
        self.assertEqual(response.status_code, 200)  # redisplayed with errors
        self.assertFalse(Drawing.objects.filter(name="photo").exists())

    def test_deleting_a_drawing_keeps_its_registrations(self):
        """The observation outlives the drawing it was pinned to — SET_NULL,
        not CASCADE, or deleting a superseded revision erases site history."""
        self.client.post(reverse("core:drawing_delete", args=[self.a["drawing"].pk]))
        self.a["registration"].refresh_from_db()
        self.assertIsNone(self.a["registration"].drawing)

    def test_range_request_returns_partial_content(self):
        url = reverse("core:drawing_pdf", args=[self.a["drawing"].pk])
        response = self.client.get(url, headers={"range": "bytes=0-9"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 10)
        self.assertEqual(response.headers["Content-Range"], f"bytes 0-9/{len(MINIMAL_PDF)}")

    def test_unsatisfiable_range_returns_416(self):
        url = reverse("core:drawing_pdf", args=[self.a["drawing"].pk])
        self.assertEqual(self.client.get(url, headers={"range": "bytes=99999-"}).status_code, 416)

    def test_suffix_range_returns_final_bytes(self):
        url = reverse("core:drawing_pdf", args=[self.a["drawing"].pk])
        response = self.client.get(url, headers={"range": "bytes=-5"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, MINIMAL_PDF[-5:])

    def test_export_returns_a_pdf(self):
        for mode in ("summary", "inline"):
            with self.subTest(mode=mode):
                response = self.client.get(
                    reverse("core:export_drawing", args=[self.a["drawing"].pk, mode])
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content.startswith(b"%PDF-"))


class PhotoTests(MediaTestCase):
    # Per-test, not setUpTestData: these delete and add files, and the
    # filesystem does not roll back with the transaction.
    def setUp(self):
        self.a = make_org("alpha")
        self.client.force_login(self.a["admin"])

    def test_upload_creates_both_renditions(self):
        self.client.post(
            reverse("core:registration_photo_add", args=[self.a["registration"].pk]),
            {"photo": SimpleUploadedFile("site.jpg", _tiny_jpeg(), content_type="image/jpeg")},
        )
        photo = RegistrationPhoto.objects.get()
        self.assertTrue(photo.image.name)
        self.assertTrue(photo.thumbnail.name)
        self.assertLess(photo.thumbnail.size, photo.image.size)

    def test_photos_of_another_org_are_not_served(self):
        b = make_org("beta")
        photo = RegistrationPhoto.objects.create(
            registration=b["registration"],
            image=SimpleUploadedFile("x.jpg", _tiny_jpeg()),
            thumbnail=SimpleUploadedFile("x-t.jpg", _tiny_jpeg()),
        )
        response = self.client.get(reverse("core:registration_photo", args=[photo.pk, "full"]))
        self.assertEqual(response.status_code, 404)


class InvitationTests(MediaTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("alpha")

    def test_invite_creates_row_and_sends_mail(self):
        self.client.force_login(self.a["admin"])
        response = self.client.post(
            reverse("core:invite_create"),
            {"email": "ny@alpha.dk", "first_name": "Ny", "last_name": "Bruger"},
        )
        self.assertEqual(response.status_code, 200)
        invitation = Invitation.objects.get(email="ny@alpha.dk")
        self.assertEqual(invitation.organization, self.a["org"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(invitation.token, mail.outbox[0].body)

    def test_accepting_creates_user_in_the_inviting_org(self):
        invitation = Invitation.objects.create(organization=self.a["org"], email="ny@alpha.dk")
        response = self.client.post(
            reverse("accounts:accept_invitation", args=[invitation.token]),
            {"first_name": "Ny", "last_name": "Bruger",
             "password1": "korrekt-hest-batteri", "password2": "korrekt-hest-batteri"},
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="ny@alpha.dk")
        self.assertEqual(user.organization, self.a["org"])
        self.assertFalse(user.is_org_admin)

    def test_token_is_single_use(self):
        invitation = Invitation.objects.create(organization=self.a["org"], email="ny@alpha.dk")
        payload = {"first_name": "Ny", "last_name": "B",
                   "password1": "korrekt-hest-batteri", "password2": "korrekt-hest-batteri"}
        url = reverse("accounts:accept_invitation", args=[invitation.token])
        self.client.post(url, payload)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 410)

    def test_expired_token_is_refused(self):
        invitation = Invitation.objects.create(
            organization=self.a["org"], email="ny@alpha.dk",
            expires_at=timezone.now() - timedelta(days=1),
        )
        url = reverse("accounts:accept_invitation", args=[invitation.token])
        self.assertEqual(self.client.get(url).status_code, 410)

    def test_admin_cannot_invite_into_another_organization(self):
        other = make_org("beta")
        self.client.force_login(self.a["admin"])
        self.client.post(
            reverse("core:invite_create"),
            {"email": "ny@alpha.dk", "organization": other["org"].pk},
        )
        self.assertEqual(Invitation.objects.get(email="ny@alpha.dk").organization, self.a["org"])


class DisciplineTests(MediaTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("alpha")

    def setUp(self):
        self.client.force_login(self.a["admin"])

    def test_discipline_in_use_cannot_be_deleted(self):
        response = self.client.post(
            reverse("core:discipline_delete", args=[self.a["discipline"].pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Discipline.objects.filter(pk=self.a["discipline"].pk).exists())

    def test_contractor_in_use_cannot_be_deleted(self):
        self.client.post(reverse("core:contractor_delete", args=[self.a["contractor"].pk]))
        self.assertTrue(Contractor.objects.filter(pk=self.a["contractor"].pk).exists())

    def test_created_records_belong_to_the_creators_org(self):
        self.client.post(reverse("core:discipline_create"), {"name": "Brand", "color": "#fd7e14"})
        self.assertEqual(Discipline.objects.get(name="Brand").organization, self.a["org"])
        self.client.post(reverse("core:contractor_create"), {"name": "Ny Entreprise"})
        self.assertEqual(Contractor.objects.get(name="Ny Entreprise").organization, self.a["org"])
