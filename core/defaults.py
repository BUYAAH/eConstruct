"""What a brand-new organization starts with.

A registration requires a discipline and a contractor (both non-nullable on
`Registration`), so an organization created with nothing in it cannot file
anything until someone works out why. Contractors are genuinely per-customer
and can't be guessed; disciplines are the same five trades on every Danish
site, so those get seeded.

One list, used by both `mothership` when a client is created and
`manage.py seed_demo`. Changing what a new client starts with is an edit
here and nowhere else.
"""

from .models import Discipline

# (name, colour, sort order). Colours match the status/discipline palette
# already in micki.css — see the accent note there for why these five.
DEFAULT_DISCIPLINES = [
    ("Konstruktion", "#dc3545", 1),
    ("Brand", "#fd7e14", 2),
    ("El", "#0d6efd", 3),
    ("VVS", "#0dcaf0", 4),
    ("Kvalitet", "#198754", 5),
]


def seed_disciplines(organization):
    """Give an organization the standard faggrupper. Idempotent.

    Uses get_or_create rather than bulk_create so re-running against an
    organization that already has some of them is safe, and so the per-org
    unique-name constraint is never hit as an IntegrityError.
    """
    created = []
    for name, color, sort_order in DEFAULT_DISCIPLINES:
        discipline, made = Discipline.objects.get_or_create(
            organization=organization,
            name=name,
            defaults={"color": color, "sort_order": sort_order},
        )
        if made:
            created.append(discipline)
    return created
