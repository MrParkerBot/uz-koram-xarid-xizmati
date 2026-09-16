"""Give the seeded statuses the order the work moves through them.

0005 added the position column with a default of zero, which means unplaced.
The rows the earlier migrations seeded were written in workflow order but have
no position, so every one of them is unplaced and the list falls back to the
name tie-break - cancelled first, the starting state third.

The order is restated here rather than read from the seed migrations. A
migration has to keep working when the code around it changes, and that
includes the other migrations.

Rows an administrator added before this ran keep position zero and sort to the
front by name. There are none in any deployment yet, and giving them a guessed
position would be worse than leaving them somewhere visible.
"""

from django.db import migrations

# Steps of ten, matching accounts.master_data.POSITION_STEP, so a status can
# later be dropped between two without renumbering the table.
STEP = 10

ARIZA_STATUS_ORDER = (
    "Yangi",
    "Qabul qilingan",
    "Tayinlangan",
    "Bekor qilingan",
)

SHARTNOMA_STATUS_ORDER = (
    "Boshlang`ich xolatda",
    "Birjaga qo`yilgan",
    "Shartnoma tuzilgan",
    "Yetkazib berilgan",
    "Bekor qilingan",
)


def place(model, names) -> None:
    """Number the named rows from one step upward, in the order given."""
    for index, name in enumerate(names, start=1):
        model.objects.filter(name=name).update(position=index * STEP)


def place_seeded_statuses(apps, schema_editor):
    place(apps.get_model("reference", "ArizaStatus"), ARIZA_STATUS_ORDER)
    place(apps.get_model("reference", "ShartnomaStatus"), SHARTNOMA_STATUS_ORDER)


def unplace_seeded_statuses(apps, schema_editor):
    """Put them back to unplaced, which is what 0005's default gives."""
    for model_name, names in (
        ("ArizaStatus", ARIZA_STATUS_ORDER),
        ("ShartnomaStatus", SHARTNOMA_STATUS_ORDER),
    ):
        apps.get_model("reference", model_name).objects.filter(
            name__in=names
        ).update(position=0)


class Migration(migrations.Migration):

    dependencies = [("reference", "0005_status_position")]

    operations = [
        migrations.RunPython(place_seeded_statuses, unplace_seeded_statuses),
    ]
