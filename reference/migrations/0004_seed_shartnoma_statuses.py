"""Seed the five contract statuses DEC-010 names.

They are examples, not a fixed set. Sections 4.3 to 4.6 print exactly these
five as counter columns, and DEC-010 settles that against section 3.5 in
favour of section 3.5: the statuses are editable and extensible, and the
workload and purchasing reports generate one column per active status rather
than assuming these.

So nothing in the application may count on there being five of them, or on any
of these names still existing. TASK-UZK-044 and TASK-UZK-045 read the table.

The colours follow the progression the supplied pages used: neutral at the
start, the department's orange while work is in flight, green when delivered,
grey when cancelled.
"""

from django.db import migrations

# Kept as literals rather than imported from the model: a migration has to keep
# working when the code around it changes.
SEEDED_STATUSES = (
    ("Boshlang`ich xolatda", "blue"),
    ("Birjaga qo`yilgan", "yellow"),
    ("Shartnoma tuzilgan", "orange"),
    ("Yetkazib berilgan", "green"),
    ("Bekor qilingan", "gray"),
)


def seed_shartnoma_statuses(apps, schema_editor):
    """Add the five statuses, leaving any that are already there alone."""
    ShartnomaStatus = apps.get_model("reference", "ShartnomaStatus")
    for name, badge_colour in SEEDED_STATUSES:
        ShartnomaStatus.objects.get_or_create(
            name=name, defaults={"badge_colour": badge_colour}
        )


def remove_shartnoma_statuses(apps, schema_editor):
    """Remove them again.

    Nothing refers to a contract status yet. When TASK-UZK-037 gives contracts
    one, this reverse will start failing on a populated database, which is the
    correct answer: unapplying the seed would strand those contracts.
    """
    ShartnomaStatus = apps.get_model("reference", "ShartnomaStatus")
    ShartnomaStatus.objects.filter(
        name__in=[name for name, _ in SEEDED_STATUSES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [("reference", "0003_shartnomastatus")]

    operations = [
        migrations.RunPython(seed_shartnoma_statuses, remove_shartnoma_statuses),
    ]
