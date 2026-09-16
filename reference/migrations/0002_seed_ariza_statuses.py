"""Seed the four application statuses DEC-017 names.

They are examples, not system rows: DEC-017 makes application status editable
master data that the department is expected to extend, so nothing here marks
them as protected and an administrator may rename or delete any of them.

The colours are the ones the supplied prototype used for the same four ideas -
a new application is neutral, an accepted one is green, an assigned one carries
the department's own orange, and a cancelled one is grey.
"""

from django.db import migrations

# Kept as literals rather than imported from the model: a migration has to keep
# working when the code around it changes.
SEEDED_STATUSES = (
    ("Yangi", "blue"),
    ("Qabul qilingan", "green"),
    ("Tayinlangan", "orange"),
    ("Bekor qilingan", "gray"),
)


def seed_ariza_statuses(apps, schema_editor):
    """Add the four statuses, leaving any that are already there alone."""
    ArizaStatus = apps.get_model("reference", "ArizaStatus")
    for name, badge_colour in SEEDED_STATUSES:
        ArizaStatus.objects.get_or_create(
            name=name, defaults={"badge_colour": badge_colour}
        )


def remove_ariza_statuses(apps, schema_editor):
    """Remove them again, but only the ones nothing refers to.

    Nothing refers to a status yet. When TASK-UZK-023 gives applications one,
    this reverse will start failing on a populated database, which is the
    correct answer: unapplying the seed would strand those applications.
    """
    ArizaStatus = apps.get_model("reference", "ArizaStatus")
    ArizaStatus.objects.filter(
        name__in=[name for name, _ in SEEDED_STATUSES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [("reference", "0001_initial")]

    operations = [
        migrations.RunPython(seed_ariza_statuses, remove_ariza_statuses),
    ]
