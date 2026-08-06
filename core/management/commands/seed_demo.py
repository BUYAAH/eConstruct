"""Create a usable organization to develop against.

Replaces what the Microsoft tenant used to provide — before the pivot the
only way to get a logged-in user was a real Entra login. Idempotent: safe to
re-run, and it never touches an organization it didn't create.
"""

from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand

from core.models import Discipline, Drawing, Organization

User = get_user_model()

SLUG = "demo"

DISCIPLINES = [
    ("Konstruktion", "#dc3545", 1),
    ("Brand", "#fd7e14", 2),
    ("El", "#0d6efd", 3),
    ("VVS", "#0dcaf0", 4),
    ("Kvalitet", "#198754", 5),
]

# Left over from the project-detail mock-up; handy as a real first drawing.
SAMPLE_PDF = Path(django_settings.BASE_DIR) / "static" / "img" / "3 - 1. ETAGE.pdf"


class Command(BaseCommand):
    help = "Create a demo organization, an admin user, and disciplines."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="admin@demo.dk")
        parser.add_argument("--password", default="demo1234")
        parser.add_argument("--name", default="Demo Byg A/S")

    def handle(self, *args, **options):
        org, created = Organization.objects.get_or_create(
            slug=SLUG, defaults={"name": options["name"]}
        )
        self.stdout.write(f"{'Created' if created else 'Found'} organization: {org.name}")

        for name, color, order in DISCIPLINES:
            Discipline.objects.get_or_create(
                organization=org, name=name, defaults={"color": color, "sort_order": order}
            )
        self.stdout.write(f"Disciplines: {org.disciplines.count()}")

        email = options["email"]
        user = User.objects.filter(username=email).first()
        if user is None:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=options["password"],
                first_name="Demo",
                last_name="Admin",
                organization=org,
                is_org_admin=True,
            )
            self.stdout.write(self.style.SUCCESS(f"Created admin: {email} / {options['password']}"))
        else:
            self.stdout.write(f"User already exists: {email}")

        if SAMPLE_PDF.exists() and not org.drawings.exists():
            drawing = Drawing(organization=org, name=SAMPLE_PDF.stem, uploaded_by=user)
            with SAMPLE_PDF.open("rb") as fh:
                drawing.file.save(SAMPLE_PDF.name, File(fh), save=True)
            # Imported here so a missing pypdf doesn't break the whole seed.
            from pypdf import PdfReader

            with drawing.file.open("rb") as fh:
                drawing.page_count = len(PdfReader(fh).pages)
            drawing.save(update_fields=["page_count"])
            self.stdout.write(f"Added drawing: {drawing.name} ({drawing.page_count} pages)")

        self.stdout.write(self.style.SUCCESS("Done. Log in at /auth/login/"))
