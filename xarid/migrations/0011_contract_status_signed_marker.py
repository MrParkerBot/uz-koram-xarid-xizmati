"""Mark which contract status means signed.

DEC-039 makes the Tuzilgan Shartnomalar indicator count the contracts that
reached the signed status rather than every contract raised. DEC-010 makes the
statuses editable master data, so the dashboard cannot name one in code; the
state is marked on the status row, exactly as 0006 marked the completed one.

An existing database already holds the five seeded examples, so the marker is
put on "Shartnoma tuzilgan", which is that set's signature step. A department
that means something else moves it from the Shartnoma Status page.
"""

from django.db import migrations, models

SIGNED_EXAMPLE = "Shartnoma tuzilgan"

HELP_TEXT = 'A contract in this status has been signed, and the dashboard counts it under Tuzilgan Shartnomalar. Marked here rather than named in the code, for the same reason the completed marker is (DEC-010). Only one status may hold the marker.'


def mark_the_seeded_signed_status(apps, schema_editor):
    """Put the marker on the seeded signature status when it is still there."""
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")
    ShartnomaStatus.objects.filter(name=SIGNED_EXAMPLE).update(is_signed=True)


def clear_the_marker(apps, schema_editor):
    """Undo the marking, so the migration reverses without a trace."""
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")
    ShartnomaStatus.objects.filter(is_signed=True).update(is_signed=False)


class Migration(migrations.Migration):

    dependencies = [
        ("xarid", "0010_contract_pdf"),
    ]

    operations = [
        migrations.AddField(
            model_name="shartnomastatus",
            name="is_signed",
            field=models.BooleanField(
                default=False,
                help_text=HELP_TEXT,
                verbose_name="Tuzilgan holat",
            ),
        ),
        migrations.RunPython(mark_the_seeded_signed_status, clear_the_marker),
    ]
