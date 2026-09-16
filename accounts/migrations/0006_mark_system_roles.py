"""Mark the six user types the department runs on.

accounts/permissions.py decides what each type may open by that type's name,
so the six DEC-013 fixes cannot be renamed or deleted from the User Types page.
Recognising them by name would have meant the protection stopped applying the
moment a name changed - which is the very thing it exists to prevent. A flag
set here breaks that circle: after this migration the flag is the handle, and
the name is just a name.
"""

from django.db import migrations, models

# A literal, like the 0002 migration that seeded these rows, so this migration
# keeps working when the code around it changes. It runs before anybody can
# have renamed one, which is what makes matching by name safe here and nowhere
# else.
DEPARTMENT_USER_TYPES = (
    "Admin",
    "Bo`lim Boshlig`i",
    "Menejer",
    "Katta Mutaxasis",
    "Direktor",
    "Users",
)


def mark_seeded_types(apps, schema_editor):
    UserType = apps.get_model("accounts", "UserType")
    UserType.objects.filter(name__in=DEPARTMENT_USER_TYPES).update(
        is_system_role=True
    )


def unmark_seeded_types(apps, schema_editor):
    UserType = apps.get_model("accounts", "UserType")
    UserType.objects.update(is_system_role=False)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_usertype_badge_colour")]

    operations = [
        migrations.AddField(
            model_name="usertype",
            name="is_system_role",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "One of the six DEC-013 fixes. accounts/permissions.py "
                    "decides what each may open by name, so a system role "
                    "cannot be renamed or deleted from the User Types page."
                ),
            ),
        ),
        migrations.RunPython(mark_seeded_types, unmark_seeded_types),
    ]
