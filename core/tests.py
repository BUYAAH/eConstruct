"""Tests for the parts that are expensive to get wrong.

The bulk of this file is tenant isolation. Organizations are 100% separated
(ROADMAP.md D6), so a single missing `organization=` filter is a data leak
rather than a cosmetic bug — that is what these assert.
"""

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import Invitation
from core.models import Discipline, Drawing, Note, Organization

User = get_user_model()

def _one_page_pdf():
    """A real single-page PDF.

    Built with pypdf rather than hand-written bytes: a literal without a
    proper xref/EOF parses as zero pages, which quietly tests the upload
    view's error path instead of its happy path.
    """
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


MINIMAL_PDF = _one_page_pdf()


def make_org(name, slug):
    """One organization with an admin, a discipline, a drawing and a note."""
    org = Organization.objects.create(name=name, slug=slug)
    discipline = Discipline.objects.create(organization=org, name="El", color="#0d6efd")
    admin = User.objects.create_user(
        username=f"admin@{slug}.dk", password="pw-for-tests-123", organization=org, is_org_admin=True
    )
    drawing = Drawing.objects.create(
        organization=org,
        name=f"{slug} drawing",
        file=SimpleUploadedFile(f"{slug}.pdf", MINIMAL_PDF, content_type="application/pdf"),
        page_count=1,
    )
    note = Note.objects.create(
        drawing=drawing, page_number=1, x_pct=10, y_pct=10, discipline=discipline,
        author=admin, text=f"note in {slug}",
    )
    return {"org": org, "admin": admin, "drawing": drawing, "note": note, "discipline": discipline}


class TenantIsolationTests(TestCase):
    """Org A must not be able to see or touch anything belonging to org B."""

    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("Alpha Byg", "alpha")
        cls.b = make_org("Beta Entreprise", "beta")

    def setUp(self):
        self.client.force_login(self.a["admin"])

    def test_cannot_open_another_orgs_drawing(self):
        for name in ("core:viewer", "core:drawing_pdf", "core:pins", "core:notes_list"):
            with self.subTest(url=name):
                response = self.client.get(reverse(name, args=[self.b["drawing"].pk]))
                self.assertEqual(response.status_code, 404)

    def test_cannot_read_another_orgs_note(self):
        response = self.client.get(reverse("core:note_detail", args=[self.b["note"].pk]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_delete_another_orgs_note(self):
        response = self.client.post(reverse("core:note_delete", args=[self.b["note"].pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Note.objects.filter(pk=self.b["note"].pk).exists())

    def test_cannot_delete_another_orgs_drawing(self):
        response = self.client.post(reverse("core:drawing_delete", args=[self.b["drawing"].pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Drawing.objects.filter(pk=self.b["drawing"].pk).exists())

    def test_cannot_export_another_orgs_drawing(self):
        response = self.client.get(
            reverse("core:export_drawing", args=[self.b["drawing"].pk, "summary"])
        )
        self.assertEqual(response.status_code, 404)

    def test_cannot_edit_another_orgs_discipline(self):
        response = self.client.get(reverse("core:discipline_edit", args=[self.b["discipline"].pk]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_toggle_another_orgs_user(self):
        response = self.client.post(
            reverse("core:user_toggle", args=[self.b["admin"].pk, "is_active"])
        )
        self.assertEqual(response.status_code, 404)
        self.b["admin"].refresh_from_db()
        self.assertTrue(self.b["admin"].is_active)

    def test_lists_show_only_own_organization(self):
        response = self.client.get(reverse("core:drawings"))
        self.assertContains(response, "alpha drawing")
        self.assertNotContains(response, "beta drawing")

    def test_note_form_offers_only_own_disciplines(self):
        from core.forms import NoteForm

        form = NoteForm(self.a["org"])
        self.assertNotIn(self.b["discipline"], form.fields["discipline"].queryset)


class PermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("Alpha Byg", "alpha")
        cls.member = User.objects.create_user(
            username="member@alpha.dk", password="pw-for-tests-123", organization=cls.a["org"]
        )

    def test_admin_only_pages_reject_plain_members(self):
        self.client.force_login(self.member)
        for name in ("core:users", "core:settings", "core:drawing_upload"):
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_member_can_view_drawings(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("core:drawings")).status_code, 200)

    def test_member_cannot_delete_someone_elses_note(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("core:note_delete", args=[self.a["note"].pk]))
        self.assertEqual(response.status_code, 403)


class InvitationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("Alpha Byg", "alpha")

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

    def test_admin_cannot_invite_into_another_organization(self):
        """The form has no organization field — it comes from the inviting
        user — so a posted organization must be ignored."""
        other = make_org("Beta", "beta")
        self.client.force_login(self.a["admin"])
        self.client.post(
            reverse("core:invite_create"),
            {"email": "ny@alpha.dk", "organization": other["org"].pk},
        )
        self.assertEqual(Invitation.objects.get(email="ny@alpha.dk").organization, self.a["org"])


class DrawingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("Alpha Byg", "alpha")

    def setUp(self):
        self.client.force_login(self.a["admin"])

    def test_upload_sets_page_count_and_defaults_name_to_filename(self):
        response = self.client.post(
            reverse("core:drawing_upload"),
            {"name": "", "file": SimpleUploadedFile("Plan E1.pdf", MINIMAL_PDF)},
        )
        self.assertEqual(response.status_code, 302)
        drawing = Drawing.objects.get(name="Plan E1")
        self.assertEqual(drawing.page_count, 1)
        self.assertEqual(drawing.organization, self.a["org"])

    def test_non_pdf_upload_is_rejected(self):
        response = self.client.post(
            reverse("core:drawing_upload"),
            {"name": "", "file": SimpleUploadedFile("photo.jpg", b"not a pdf")},
        )
        self.assertEqual(response.status_code, 200)  # redisplayed with errors
        self.assertFalse(Drawing.objects.filter(name="photo").exists())

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


class DisciplineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_org("Alpha Byg", "alpha")

    def setUp(self):
        self.client.force_login(self.a["admin"])

    def test_discipline_in_use_cannot_be_deleted(self):
        response = self.client.post(
            reverse("core:discipline_delete", args=[self.a["discipline"].pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Discipline.objects.filter(pk=self.a["discipline"].pk).exists())

    def test_created_discipline_belongs_to_the_creators_org(self):
        self.client.post(reverse("core:discipline_create"), {"name": "Brand", "color": "#fd7e14"})
        self.assertEqual(Discipline.objects.get(name="Brand").organization, self.a["org"])
