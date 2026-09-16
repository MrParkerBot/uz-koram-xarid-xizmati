"""Give the seeded application statuses the codes the workflow looks them up by.

0002 seeded four statuses by name, because at the time nothing needed to find
one. TASK-UZK-023 does: accepting an application has to attach the accepted
status, and DEC-017 lets an administrator rename any row, so a lookup by name
is a lookup that stops working the day somebody exercises the page.

The rows are matched here by the names 0002 wrote, which is safe exactly once -
now, before anybody has had the chance to rename them. After this the code is
the handle and the name is free to change, which is the whole point.

A row an administrator added has no code and gets none. The code means "the
application itself relies on this row", and only the application can say that.
"""

from django.db import migrations

# The names 0002_seed_ariza_statuses.py created, paired with the code each row
# is known by from now on. Literals rather than imports: a migration has to
# keep working when the code around it changes.
CODE_BY_SEEDED_NAME = (
    ("Yangi", "new"),
    ("Qabul qilingan", "accepted"),
    ("Tayinlangan", "assigned"),
    ("Bekor qilingan", "cancelled"),
)


def code_the_seeded_statuses(apps, schema_editor):
    """Set each seeded row's code, leaving anything else alone."""
    ArizaStatus = apps.get_model("reference", "ArizaStatus")
    for name, code in CODE_BY_SEEDED_NAME:
        # Only a row that still has its seeded name and no code yet. An
        # installation that already renamed one is left alone rather than
        # matched by guesswork, and the pull request says what that costs.
        ArizaStatus.objects.filter(name=name, code="").update(code=code)


def uncode_the_seeded_statuses(apps, schema_editor):
    """Clear the codes again."""
    ArizaStatus = apps.get_model("reference", "ArizaStatus")
    ArizaStatus.objects.filter(
        code__in=[code for _, code in CODE_BY_SEEDED_NAME]
    ).update(code="")


class Migration(migrations.Migration):

    dependencies = [("reference", "0012_arizastatus_code")]

    operations = [
        migrations.RunPython(code_the_seeded_statuses, uncode_the_seeded_statuses),
    ]
