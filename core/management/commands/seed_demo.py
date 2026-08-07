"""Create a realistic organization to develop against.

Replaces what the Microsoft tenant used to provide: before the pivot the
only way to get a logged-in user was a real Entra login. Idempotent — safe
to re-run, and it never touches an organization it didn't create.
"""

import random
from datetime import timedelta
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from core.defaults import seed_disciplines
from core.models import Contractor, Drawing, Organization, Project, Registration

User = get_user_model()

SLUG = "demo"
PASSWORD = "demo1234"

CONTRACTORS = [
    ("Nord El A/S", "Søren Dahl", "sd@nordel.dk"),
    ("Aalborg VVS ApS", "Anders Precht", "ap@aalborgvvs.dk"),
    ("Betonteknik Nord", "Mette Kjær", "mk@betonteknik.dk"),
    ("Brandsikring Danmark", "Lars Storm", "ls@brandsikring.dk"),
]

# (email, first, last, is_admin)
PEOPLE = [
    ("admin@demo.dk", "Demo", "Admin", True),
    ("lene@demo.dk", "Lene", "Bak", False),
    ("jonas@demo.dk", "Jonas", "Overgaard", False),
]

PROJECTS = [
    ("Sygehus Nord", "2024-0417", "Hobrovej 18, 9000 Aalborg", Project.ACTIVE),
    ("Hasserisvej 31", "2024-0392", "Hasserisvej 31, 9000 Aalborg", Project.ACTIVE),
    ("Vester Hassing Skole", "2023-1184", "Halvvejen 5, 9310 Vodskov", Project.DONE),
]

# (subject, discipline, status, deadline offset in days or None)
REGISTRATIONS = [
    ("Revne i betonvæg ved akse D/4", "Konstruktion", Registration.OPEN, 5),
    ("Manglende brandtætning omkring rørgennemføring", "Brand", Registration.OPEN, -1),
    ("El-dåse placeret forkert ift. tegning", "El", Registration.OPEN, None),
    ("Vandskade i loft ved teknikrum", "VVS", Registration.OPEN, 1),
    ("Loftshøjde målt til 2,80 m mod 3,00 m projekteret", "Konstruktion", Registration.RESOLVED, -3),
    ("Manglende isolering i ydervæg mod nord", "Kvalitet", Registration.APPROVED, None),
    ("Fejlmonteret brandspjæld i skakt 2", "Brand", Registration.RESOLVED, 8),
    ("Utæt samling ved faldstamme", "VVS", Registration.APPROVED, -10),
]

SAMPLE_PDF = Path(django_settings.BASE_DIR) / "static" / "img" / "3 - 1. ETAGE.pdf"


class Command(BaseCommand):
    help = "Create a demo organization with projects, contractors and registrations."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Demo Byg A/S")

    def handle(self, *args, **options):
        # Seeded so re-running gives the same layout — a demo that reshuffles
        # every run is hard to talk about.
        rng = random.Random(20260806)

        org, created = Organization.objects.get_or_create(
            slug=SLUG, defaults={"name": options["name"]}
        )
        self.stdout.write(f"{'Created' if created else 'Found'} organization: {org.name}")

        # Same five a client created from Mothership gets — one list, in
        # core/defaults.py.
        seed_disciplines(org)
        disciplines = {d.name: d for d in org.disciplines.all()}

        contractors = []
        for name, contact, email in CONTRACTORS:
            contractor, _ = Contractor.objects.get_or_create(
                organization=org, name=name,
                defaults={"contact_name": contact, "contact_email": email},
            )
            contractors.append(contractor)

        users = []
        for email, first, last, is_admin in PEOPLE:
            user = User.objects.filter(username=email).first()
            if user is None:
                user = User.objects.create_user(
                    username=email, email=email, password=PASSWORD,
                    first_name=first, last_name=last,
                    organization=org, is_org_admin=is_admin,
                )
            users.append(user)

        for name, case_no, address, status in PROJECTS:
            project, made = Project.objects.get_or_create(
                organization=org, slug=slugify(name),
                defaults={
                    "name": name, "case_no": case_no, "address": address,
                    "status": status, "manager": users[1],
                },
            )
            if not made:
                continue
            project.members.set(users)
            project.contractors.set(contractors)

            drawing = None
            if SAMPLE_PDF.exists():
                drawing = Drawing(project=project, name="3 - 1. etage", uploaded_by=users[0])
                with SAMPLE_PDF.open("rb") as fh:
                    drawing.file.save(SAMPLE_PDF.name, File(fh), save=True)
                drawing.page_count = _page_count(drawing)
                drawing.save(update_fields=["page_count", "updated_at"])

            today = timezone.localdate()
            for subject, discipline_name, status_value, offset in REGISTRATIONS:
                registration = Registration(
                    project=project,
                    drawing=drawing,
                    discipline=disciplines[discipline_name],
                    subject=subject,
                    assigned_contractor=rng.choice(contractors),
                    responsible=rng.choice(users),
                    author=rng.choice(users),
                    deadline=today + timedelta(days=offset) if offset is not None else None,
                    status=status_value,
                )
                if drawing:
                    registration.page_number = 1
                    registration.x_pct = round(rng.uniform(12, 88), 3)
                    registration.y_pct = round(rng.uniform(12, 88), 3)
                if status_value in (Registration.RESOLVED, Registration.APPROVED):
                    registration.resolved_at = timezone.now() - timedelta(days=2)
                if status_value == Registration.APPROVED:
                    registration.approved_at = timezone.now() - timedelta(days=1)
                registration.save()

            self.stdout.write(f"  {project.name}: {project.registrations.count()} registreringer")

        self.stdout.write(self.style.SUCCESS(f"\nLog in at /auth/login/"))
        for email, *_ in PEOPLE:
            self.stdout.write(f"  {email} / {PASSWORD}")


def _page_count(drawing):
    from pypdf import PdfReader

    try:
        with drawing.file.open("rb") as fh:
            return len(PdfReader(fh).pages)
    except Exception:
        return 0
