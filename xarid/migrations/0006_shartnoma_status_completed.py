"""Mark which contract status means completed.

DEC-010 makes the contract statuses editable master data, so the dashboard's
completed figure (REQ-DASH-004) cannot name one in code. The state is marked
on the status row instead. An existing database already holds the five seeded
examples, so the marker is put on the last workflow state of that set,
"Yetkazib berilgan"; a department that means something else moves it from the
Shartnoma Status page.
"""

from django.db import migrations, models

COMPLETED_EXAMPLE = "Yetkazib berilgan"


def mark_the_seeded_completed_status(apps, schema_editor):
    """Put the marker on the seeded delivered status when it is still there."""
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")
    ShartnomaStatus.objects.filter(name=COMPLETED_EXAMPLE).update(is_completed=True)


def clear_the_marker(apps, schema_editor):
    """Undo the marking, so the migration reverses without a trace."""
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")
    ShartnomaStatus.objects.filter(is_completed=True).update(is_completed=False)


class Migration(migrations.Migration):

    dependencies = [
        ("xarid", "0005_contract_approval"),
    ]

    operations = [
        migrations.AddField(
            model_name="shartnomastatus",
            name="is_completed",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "A contract in this status is finished, and the dashboard "
                    "counts it as completed. The statuses are editable "
                    "(DEC-010), so which one means completed is marked here "
                    "rather than named in the code. Only one status may hold "
                    "the marker."
                ),
                verbose_name="Tugallangan holat",
            ),
        ),
        migrations.RunPython(mark_the_seeded_completed_status, clear_the_marker),
    ]
