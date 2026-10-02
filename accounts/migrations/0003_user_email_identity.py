"""Make the email address the account.

`username` is dropped and `email` becomes unique. The RunPython step runs
first and does two things the schema change cannot do for itself: it
lower-cases every stored address, and it refuses to continue if that would
collide or if any account has no address at all.

Worth the guard even though the dev database is disposable: the
PythonAnywhere server has its own, and the alternative on deploy is a bare
IntegrityError with no indication of which rows caused it.

One-way. The reverse would have to invent a username for every account, and
the project has no data worth rolling back to.
"""

import accounts.models
from django.db import migrations, models


def normalise_and_check(apps, schema_editor):
    User = apps.get_model("accounts", "User")

    # Collect before writing: raising half way through would leave some rows
    # normalised and some not.
    seen = {}
    blanks = []
    collisions = []
    updates = []

    for user in User.objects.all().order_by("pk"):
        email = (user.email or "").strip().lower()
        if not email:
            blanks.append(user.pk)
            continue
        if email in seen:
            collisions.append(f"  {email}: user pk={seen[email]} and pk={user.pk}")
        else:
            seen[email] = user.pk
        if email != user.email:
            updates.append((user.pk, email))

    problems = []
    if blanks:
        problems.append(
            "These accounts have no email address, which is now the login:\n"
            + "\n".join(f"  user pk={pk}" for pk in blanks)
        )
    if collisions:
        problems.append(
            "These accounts would share an address once lower-cased:\n"
            + "\n".join(collisions)
        )
    if problems:
        raise RuntimeError(
            "Cannot make email the login identifier yet.\n\n"
            + "\n\n".join(problems)
            + "\n\nFix them first, e.g.:\n"
            "  manage.py shell -c \"from accounts.models import User; "
            "u=User.objects.get(pk=PK); u.email='ny@adresse.dk'; u.save()\"\n"
            "or delete the account if it is a leftover."
        )

    for pk, email in updates:
        User.objects.filter(pk=pk).update(email=email)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(normalise_and_check, migrations.RunPython.noop),
        migrations.AlterModelManagers(
            name='user',
            managers=[
                ('objects', accounts.models.UserManager()),
            ],
        ),
        migrations.RemoveField(
            model_name='user',
            name='username',
        ),
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(max_length=254, unique=True, verbose_name='email address'),
        ),
    ]
