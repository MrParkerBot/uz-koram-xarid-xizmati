"""Create the six user types the department works with (DEC-013).

They are data rather than code because the specification gives User Types a
master data page, but they are seeded here because the application cannot
decide who may open what until the rows exist. An installation that renames or
retires one does so through that page; this migration only ensures nobody
starts with an empty table.
"""

from django.db import migrations

# Kept as a literal rather than imported from accounts.roles: a migration has
# to keep working when the code around it changes.
DEPARTMENT_USER_TYPES = (
    "Admin",
    "Bo`lim Boshlig`i",
    "Menejer",
    "Katta Mutaxasis",
    "Direktor",
    "Users",
)


def create_department_user_types(apps, schema_editor):
    UserType = apps.get_model("accounts", "UserType")
    for name in DEPARTMENT_USER_TYPES:
        UserType.objects.get_or_create(name=name)


def remove_department_user_types(apps, schema_editor):
    """Remove only the types nobody has been assigned.

    A type still in use cannot be deleted - the foreign key protects it - and
    an unapplied migration is a poor reason to detach somebody's role.
    """
    UserType = apps.get_model("accounts", "UserType")
    UserType.objects.filter(name__in=DEPARTMENT_USER_TYPES, users__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.RunPython(
            create_department_user_types, remove_department_user_types
        )
    ]
