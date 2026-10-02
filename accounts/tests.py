"""The email address is the account.

These pin the invariant that used to live in two form validators and was
therefore not an invariant at all: `createsuperuser` and Django admin both
bypassed it, which is how two accounts ended up sharing one address while the
login page — labelled E-mail — could log in neither of them.

What matters here is *where* the rule is enforced. Every test below goes
around the forms deliberately, because the forms were never the problem.
"""

from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Organization

User = get_user_model()

PASSWORD = "pw-for-tests-123"


class EmailIsTheIdentifierTests(TestCase):
    def test_there_is_no_username_field(self):
        """If this ever fails, a second identity field is back and the whole
        class of bug with it."""
        self.assertEqual(User.USERNAME_FIELD, "email")
        field_names = {f.name for f in User._meta.get_fields()}
        self.assertNotIn("username", field_names)

    def test_a_duplicate_address_is_refused_by_the_database(self):
        """Not by a form. This is the path `createsuperuser` and Django
        admin's add-user page take, and the one that actually failed."""
        User.objects.create_user(email="anna@byg.dk", password=PASSWORD)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(email="anna@byg.dk", password=PASSWORD)

    def test_a_superuser_cannot_reuse_a_customers_address(self):
        User.objects.create_user(email="anna@byg.dk", password=PASSWORD)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_superuser(email="anna@byg.dk", password=PASSWORD)

    def test_an_account_cannot_be_created_without_an_address(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password=PASSWORD)


class EmailCaseTests(TestCase):
    """`Anna@Byg.dk` and `anna@byg.dk` are one person, not two.

    SQLite and Postgres both compare text case-sensitively, so `unique=True`
    alone would happily store both. Normalisation is what makes the constraint
    mean what it looks like it means.
    """

    def test_the_address_is_stored_lower_cased(self):
        user = User.objects.create_user(email="Anna@Byg.DK", password=PASSWORD)
        self.assertEqual(user.email, "anna@byg.dk")
        self.assertEqual(User.objects.get(email="anna@byg.dk"), user)

    def test_a_case_variant_is_a_duplicate(self):
        User.objects.create_user(email="anna@byg.dk", password=PASSWORD)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(email="ANNA@BYG.DK", password=PASSWORD)

    def test_save_normalises_too_not_just_the_manager(self):
        """A shell session or a fixture assigns the attribute directly and
        never goes near `create_user`."""
        user = User.objects.create_user(email="anna@byg.dk", password=PASSWORD)
        user.email = "Anna@BYG.dk"
        user.save()
        user.refresh_from_db()
        self.assertEqual(user.email, "anna@byg.dk")


class LoginWithEmailTests(TestCase):
    """The symptom that started this: the login page says E-mail, so an email
    address has to be what logs you in."""

    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Byg A/S", slug="byg")
        cls.user = User.objects.create_user(
            email="anna@byg.dk", password=PASSWORD, organization=cls.org
        )

    def test_logging_in_with_the_email_address_works(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "anna@byg.dk", "password": PASSWORD},
        )
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_the_casing_typed_does_not_matter(self):
        """A phone keyboard capitalises the first letter. That must not read
        as a wrong password."""
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "Anna@Byg.dk", "password": PASSWORD},
        )
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.pk))
        self.assertEqual(response.status_code, 302)

    def test_surrounding_whitespace_is_tolerated(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "  anna@byg.dk  ", "password": PASSWORD},
        )
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.pk))
        self.assertEqual(response.status_code, 302)

    def test_a_wrong_password_still_fails(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "anna@byg.dk", "password": "not-the-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "Forkert e-mail eller adgangskode.")


class UserAdminTests(TestCase):
    """`UserAdmin`'s stock fieldsets name `username`. Inheriting them after the
    field is gone breaks both pages at render time, and ROADMAP.md §7 had
    written `add_fieldsets` off as not worth doing — so it is worth a test that
    actually opens them."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            email="martin@micki.dk", password=PASSWORD
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_the_user_list_renders(self):
        response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_the_add_user_page_renders(self):
        response = self.client.get(reverse("admin:accounts_user_add"))
        self.assertEqual(response.status_code, 200)

    def test_the_change_user_page_renders(self):
        response = self.client.get(
            reverse("admin:accounts_user_change", args=[self.staff.pk])
        )
        self.assertEqual(response.status_code, 200)
