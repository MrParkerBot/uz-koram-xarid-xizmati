"""Seed the two contract types DEC-023 names.

CONFLICT-004 is that section 3.7 gives Shartnoma turi a master data page while
the section 4.8 contract form fixes it to Import and Local. DEC-023 decides for
section 3.7: the list is maintainable and these two are where it starts.

So they are examples, not a pair. TASK-UZK-034 and TASK-UZK-035 read the table,
and an installation that works with framework agreements or tolling contracts
adds them here rather than waiting for a release.
"""

from django.db import migrations

# Kept as literals rather than imported from the model: a migration has to keep
# working when the code around it changes.
SEEDED_CONTRACT_TYPES = ("Import", "Mahalliy (Local)")


def seed_shartnoma_turlari(apps, schema_editor):
    """Add the two types, leaving any that are already there alone."""
    ShartnomaTuri = apps.get_model("reference", "ShartnomaTuri")
    for name in SEEDED_CONTRACT_TYPES:
        ShartnomaTuri.objects.get_or_create(name=name)


def remove_shartnoma_turlari(apps, schema_editor):
    """Remove them again.

    Nothing refers to a contract type yet. When TASK-UZK-035 gives contracts
    one, this reverse will start failing on a populated database, which is the
    correct answer: unapplying the seed would strand those contracts.
    """
    ShartnomaTuri = apps.get_model("reference", "ShartnomaTuri")
    ShartnomaTuri.objects.filter(name__in=SEEDED_CONTRACT_TYPES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0008_shartnomaturi_alter_arizastatus_name_and_more")
    ]

    operations = [
        migrations.RunPython(seed_shartnoma_turlari, remove_shartnoma_turlari),
    ]
