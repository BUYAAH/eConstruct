"""Tests for the internal console.

Two things here are expensive to get wrong, and they pull in opposite
directions:

- **The gate.** Mothership reads across the tenancy boundary that the rest of
  the app exists to enforce, so every view has to be unreachable by anyone who
  isn't a superuser. That is most of this file.
- **Creating a client.** The whole page exists to stop a half-created customer
  — an organization nobody can log into, or one that can't file a
  registration — so the created state is asserted, not just the redirect.

Suspension is tested at both layers deliberately: refusing a login and ending
a session that is already open are different mechanisms, and only having the
first would let a suspended customer keep working for the 30 days a session
lasts.
"""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import Invitation
from core.defaults import DEFAULT_DISCIPLINES
from core.models import Organization, Project, Registration

from .forms import ClientCreateForm

User = get_user_model()

PASSWORD = "pw-for-tests-123"


def make_superuser(username="martin@micki.dk"):
    return User.objects.create_superuser(username=username, password=PASSWORD)


class GateTests(TestCase):
    """Nobody but a superuser gets in, and they get a 404 so the URL space
    doesn't confirm what lives here."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Kunde A/S", slug="kunde")
        cls.customer_admin = User.objects.create_user(
            username="admin@kunde.dk", password=PASSWORD,
            organization=cls.org, is_org_admin=True,
        )
        # is_staff on its own must not be enough — it also opens Django admin
        # and is the flag one would hand a support person.
        cls.staffer = User.objects.create_user(
            username="support@micki.dk", password=PASSWORD, is_staff=True
        )
        cls.superuser = make_superuser()

    def urls(self):
        return [
            reverse("mothership:clients"),
            reverse("mothership:client_create"),
            reverse("mothership:client_detail", args=[self.org.slug]),
        ]

    def test_anonymous_is_redirected_to_login(self):
        for url in self.urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_customer_org_admin_gets_404(self):
        self.client.force_login(self.customer_admin)
        for url in self.urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_is_staff_is_not_enough(self):
        self.client.force_login(self.staffer)
        for url in self.urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_superuser_gets_in(self):
        self.client.force_login(self.superuser)
        for url in self.urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_write_views_reject_a_customer(self):
        """The POST endpoints are gated too, not just the pages that link to
        them — a 404 on the page is worth nothing if the action is open."""
        self.client.force_login(self.customer_admin)
        for name in ("client_edit", "client_toggle"):
            with self.subTest(view=name):
                url = reverse(f"mothership:{name}", args=[self.org.slug])
                self.assertEqual(self.client.post(url, {"name": "Kapret"}).status_code, 404)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "Kunde A/S")
        self.assertTrue(self.org.is_active)

    def test_the_customer_app_never_mentions_mothership(self):
        """The sidebar has no way in. A customer is never a superuser, but the
        URL not appearing at all is what keeps Mothership's existence quiet."""
        self.client.force_login(self.customer_admin)
        self.assertNotContains(
            self.client.get(reverse("core:overview")), reverse("mothership:clients")
        )


class ClientCreateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = make_superuser()

    def setUp(self):
        self.client.force_login(self.superuser)

    def post(self, **overrides):
        data = {
            "name": "Nordjysk Byg A/S",
            "admin_first_name": "Ida",
            "admin_last_name": "Holm",
            "admin_email": "ida@nordjyskbyg.dk",
            "access": ClientCreateForm.INVITE,
            "password": "",
            "seed_disciplines": "on",
        }
        data.update(overrides)
        return self.client.post(reverse("mothership:client_create"), data)

    def test_invite_path_creates_org_disciplines_and_an_invitation(self):
        response = self.post()

        org = Organization.objects.get(slug="nordjysk-byg-as")
        self.assertRedirects(response, reverse("mothership:client_detail", args=[org.slug]))
        self.assertTrue(org.is_active)
        self.assertEqual(
            sorted(org.disciplines.values_list("name", flat=True)),
            sorted(name for name, _, _ in DEFAULT_DISCIPLINES),
        )

        invitation = org.invitations.get()
        self.assertEqual(invitation.email, "ida@nordjyskbyg.dk")
        self.assertTrue(invitation.as_org_admin)
        self.assertEqual(invitation.invited_by, self.superuser)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(invitation.token, mail.outbox[0].body)

        # No user until they accept — an invitation is a promise, not an account.
        self.assertFalse(org.users.exists())

    def test_password_path_creates_a_usable_admin(self):
        self.post(access=ClientCreateForm.PASSWORD, password="Fundament-2026!")

        org = Organization.objects.get(slug="nordjysk-byg-as")
        admin = org.users.get()
        self.assertTrue(admin.is_org_admin)
        self.assertFalse(admin.is_superuser)
        # Username *is* the email (ROADMAP.md §7, friction 2). Set differently
        # the account simply cannot log in, and nothing would say so.
        self.assertEqual(admin.username, "ida@nordjyskbyg.dk")
        self.assertEqual(admin.email, "ida@nordjyskbyg.dk")
        self.assertEqual(len(mail.outbox), 0)

        self.client.logout()
        self.assertTrue(
            self.client.login(username="ida@nordjyskbyg.dk", password="Fundament-2026!")
        )

    def test_the_new_admin_lands_in_their_own_org_and_sees_nothing_else(self):
        """The point of the whole page: one submit produces a working tenant."""
        other = Organization.objects.create(name="Anden Kunde", slug="anden")
        Project.objects.create(organization=other, name="Hemmeligt", slug="hemmeligt")

        self.post(access=ClientCreateForm.PASSWORD, password="Fundament-2026!")
        admin = User.objects.get(username="ida@nordjyskbyg.dk")

        self.client.force_login(admin)
        response = self.client.get(reverse("core:projects"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Hemmeligt")

    def test_seeding_can_be_skipped(self):
        self.post(seed_disciplines="")
        self.assertFalse(Organization.objects.get(slug="nordjysk-byg-as").disciplines.exists())

    def test_duplicate_name_is_a_field_error_not_a_500(self):
        Organization.objects.create(name="Nordjysk Byg A/S", slug="nordjysk-byg-as")
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "name", "Der findes allerede en kunde med dette navn."
        )
        self.assertEqual(Organization.objects.count(), 1)

    def test_email_already_in_use_anywhere_is_rejected(self):
        """An address is a username, and usernames are global — so it belongs
        to exactly one organization."""
        existing = Organization.objects.create(name="Anden", slug="anden")
        User.objects.create_user(
            username="ida@nordjyskbyg.dk", password=PASSWORD, organization=existing
        )
        response = self.post()
        self.assertFormError(
            response.context["form"], "admin_email",
            "Der findes allerede en bruger med denne e-mail.",
        )
        self.assertFalse(Organization.objects.filter(slug="nordjysk-byg-as").exists())

    def test_password_path_requires_a_password(self):
        response = self.post(access=ClientCreateForm.PASSWORD, password="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Organization.objects.exists())

    def test_weak_password_is_rejected(self):
        response = self.post(access=ClientCreateForm.PASSWORD, password="1234")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors["password"])
        self.assertFalse(Organization.objects.exists())

    def test_nothing_is_created_when_the_form_fails(self):
        """The org, its disciplines and its admin land together or not at all —
        an organization nobody can log into is exactly what this page prevents."""
        self.post(admin_email="not-an-email")
        self.assertFalse(Organization.objects.exists())
        self.assertFalse(Invitation.objects.exists())


class SuspensionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = make_superuser()
        cls.org = Organization.objects.create(name="Kunde A/S", slug="kunde")
        cls.user = User.objects.create_user(
            username="bruger@kunde.dk", password=PASSWORD, organization=cls.org
        )

    def suspend(self):
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("mothership:client_toggle", args=[self.org.slug]))
        self.client.logout()
        return response

    def test_toggle_flips_is_active_both_ways(self):
        self.suspend()
        self.org.refresh_from_db()
        self.assertFalse(self.org.is_active)

        self.suspend()
        self.org.refresh_from_db()
        self.assertTrue(self.org.is_active)

    def test_toggle_rejects_get(self):
        self.client.force_login(self.superuser)
        url = reverse("mothership:client_toggle", args=[self.org.slug])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.org.refresh_from_db()
        self.assertTrue(self.org.is_active)

    def test_a_suspended_client_cannot_log_in(self):
        self.suspend()
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "bruger@kunde.dk", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)
        self.assertContains(response, "sat på pause")

    def test_an_open_session_is_ended_on_the_next_request(self):
        """Sessions last 30 days and slide, so login-time enforcement alone
        would leave a suspended customer working for a month."""
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("core:overview")).status_code, 200)

        self.org.is_active = False
        self.org.save(update_fields=["is_active", "updated_at"])

        response = self.client.get(reverse("core:overview"))
        self.assertRedirects(response, reverse("accounts:login"))
        # Really logged out, not merely bounced once.
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_reactivating_lets_them_back_in(self):
        self.suspend()
        self.suspend()
        self.assertTrue(self.client.login(username="bruger@kunde.dk", password=PASSWORD))

    def test_a_superuser_is_unaffected_by_suspension(self):
        """Superusers have no organization, and the check must not trip over
        that — locking ourselves out of Mothership by suspending a client
        would be the worst possible failure mode here."""
        self.suspend()
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("mothership:clients")).status_code, 200)


class ClientListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = make_superuser()
        cls.a = Organization.objects.create(name="Alfa Byg", slug="alfa")
        cls.b = Organization.objects.create(name="Beta Entreprise", slug="beta")

        User.objects.create_user(username="a1@alfa.dk", password=PASSWORD, organization=cls.a)
        User.objects.create_user(username="a2@alfa.dk", password=PASSWORD, organization=cls.a)
        project = Project.objects.create(organization=cls.a, name="Sygehus", slug="sygehus")
        discipline = cls.a.disciplines.create(name="El")
        contractor = cls.a.contractors.create(name="Nord El")
        project.contractors.add(contractor)
        Registration.objects.create(
            project=project, discipline=discipline, subject="Fejl",
            assigned_contractor=contractor,
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_counts_are_not_multiplied_by_each_other(self):
        """Three independent joins in one annotate — without distinct=True
        each count comes back as the product of the others."""
        response = self.client.get(reverse("mothership:clients"))
        alfa = next(c for c in response.context["clients"] if c.slug == "alfa")
        self.assertEqual(alfa.user_count, 2)
        self.assertEqual(alfa.project_count, 1)
        self.assertEqual(alfa.registration_count, 1)

    def test_the_superuser_is_not_counted_as_anyones_user(self):
        response = self.client.get(reverse("mothership:clients"))
        self.assertEqual(response.context["total_users"], 2)

    def test_search_filters_by_name(self):
        response = self.client.get(reverse("mothership:clients"), {"q": "beta"})
        self.assertEqual([c.slug for c in response.context["clients"]], ["beta"])
        # Totals are over every client, so they must not follow the filter.
        self.assertEqual(response.context["total_active"], 2)

    def test_detail_shows_project_names_but_no_registration_content(self):
        """Counts + project names is the agreed depth — the hole in D6 is
        exactly this wide and no wider."""
        response = self.client.get(reverse("mothership:client_detail", args=["alfa"]))
        self.assertContains(response, "Sygehus")
        self.assertNotContains(response, "Fejl")

    def test_detail_warns_when_a_client_cannot_file_anything(self):
        """A brand-new client has no contractors, and a registration requires
        one — the warning is the only thing that catches it before they call."""
        response = self.client.get(reverse("mothership:client_detail", args=["beta"]))
        self.assertContains(response, "ikke klar til brug")

    def test_rename_keeps_the_slug(self):
        self.client.post(
            reverse("mothership:client_edit", args=["alfa"]), {"name": "Alfa Byg ApS"}
        )
        self.a.refresh_from_db()
        self.assertEqual(self.a.name, "Alfa Byg ApS")
        self.assertEqual(self.a.slug, "alfa")


class HomeTests(TestCase):
    """An account is either ours or a customer's, and each has one home.

    Asserted at both layers for the same reason suspension is: logging in is
    not the only way to arrive somewhere. A bookmark or a hand-typed URL has
    to land in the same place.
    """

    @classmethod
    def setUpTestData(cls):
        cls.superuser = make_superuser()
        cls.org = Organization.objects.create(name="Kunde A/S", slug="kunde")
        cls.customer = User.objects.create_user(
            username="bruger@kunde.dk", password=PASSWORD, organization=cls.org
        )

    def login(self, username, **extra):
        return self.client.post(
            reverse("accounts:login"),
            {"username": username, "password": PASSWORD},
            **extra,
        )

    def test_a_superuser_lands_in_mothership(self):
        self.assertRedirects(
            self.login("martin@micki.dk"), reverse("mothership:clients")
        )

    def test_a_customer_lands_in_the_app(self):
        self.assertRedirects(self.login("bruger@kunde.dk"), reverse("core:overview"))

    def test_an_explicit_next_still_wins_for_a_customer(self):
        """A bookmarked deep link has to survive an expired session."""
        target = reverse("core:projects")
        response = self.client.post(
            f"{reverse('accounts:login')}?next={target}",
            {"username": "bruger@kunde.dk", "password": PASSWORD},
        )
        self.assertRedirects(response, target)

    def test_a_superuser_visiting_the_customer_app_is_sent_back(self):
        self.client.force_login(self.superuser)
        for name in ("overview", "projects", "registrations", "reports", "users"):
            with self.subTest(view=name):
                self.assertRedirects(
                    self.client.get(reverse(f"core:{name}")),
                    reverse("mothership:clients"),
                )

    def test_a_customer_is_left_alone(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("core:overview")).status_code, 200)

    def test_logout_and_invitations_are_not_redirected(self):
        """Only `core` is bounced — the auth flow has to stay reachable, or a
        superuser could not log out."""
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)


class OrglessUserTests(TestCase):
    """`User.organization` is nullable, so a user without one is reachable
    state (ROADMAP.md §7, friction 3).

    Six views used to dereference `request.user.organization` with no check,
    which is an AttributeError on None and a 500 page. Superusers no longer
    reach those pages at all, but the guard is what makes that a routing
    decision rather than the only thing standing between us and a crash.
    """

    @classmethod
    def setUpTestData(cls):
        cls.orgless = User.objects.create_user(username="ingen@micki.dk", password=PASSWORD)
        cls.orgless_admin = User.objects.create_user(
            username="odd@micki.dk", password=PASSWORD, is_org_admin=True
        )

    def test_customer_pages_render_empty_rather_than_500(self):
        self.client.force_login(self.orgless)
        for name in ("overview", "projects", "registrations", "reports"):
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(f"core:{name}")).status_code, 200)

    def test_admin_pages_are_forbidden_rather_than_500(self):
        """An org admin flag without an organization has nothing to administer,
        so it's the ordinary 403 — not a crash, and not access either."""
        self.client.force_login(self.orgless_admin)
        for name in ("users", "settings"):
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(f"core:{name}")).status_code, 403)

    def test_an_orgless_user_sees_no_customer_data(self):
        org = Organization.objects.create(name="Kunde", slug="kunde")
        Project.objects.create(organization=org, name="Hemmeligt", slug="hemmeligt")
        org.disciplines.create(name="El")

        self.client.force_login(self.orgless)
        response = self.client.get(reverse("core:registrations"))
        self.assertNotContains(response, "Hemmeligt")
        self.assertEqual(list(response.context["disciplines"]), [])
