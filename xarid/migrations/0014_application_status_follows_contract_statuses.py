"""An assigned application reports a Shartnoma Status, not an Ariza Status.

Tayinlangan Arizalar is where a specialist says how far the work has got, and
how far it has got is a contract state. The column used to offer the Ariza
Statuses, which stop at "Qabul qilingan" and never reach "Birjaga qo`yilgan"
or "Yetkazib berilgan", so the page could not say the thing it exists to say.

Two rows are added to the contract statuses for the part of the work that
happens before there is a contract - handed out, and taken up - so that one
column moves through one list of names, and the filter beside it offers that
same list.

Application.status is repointed rather than joined by a second column: the
Ariza Statuses were shown on no other page, and two status columns that can
disagree is the bug this avoids. The values are carried across by name, which
is what the two tables share.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models

# The two states an application is in before a contract exists. Placed ahead
# of the seeded contract statuses, in the order the work passes through them.
WORK_STATUSES = (
    {"name": "Tayinlangan", "code": "assigned", "position": 5, "badge_colour": "gray"},
    {"name": "Qabul qilingan", "code": "accepted", "position": 8, "badge_colour": "blue"},
)

# An Ariza Status carried across to the contract status of the same name. Only
# "Yangi" needs saying: the other three names now exist on both tables.
BY_NAME = {"Yangi": "Boshlang`ich xolatda"}


def add_work_statuses(apps, schema_editor) -> None:
    """Put the two pre-contract states on the contract status list."""
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")

    for row in WORK_STATUSES:
        ShartnomaStatus.objects.update_or_create(
            name=row["name"],
            defaults={
                "code": row["code"],
                "position": row["position"],
                "badge_colour": row["badge_colour"],
            },
        )

    # The workflow cancels an application by code, so the row it cancels to
    # needs one. Matched by name because that is all the seeded row has.
    ShartnomaStatus.objects.filter(name="Bekor qilingan", code="").update(code="cancelled")


def drop_work_statuses(apps, schema_editor) -> None:
    """Take the two rows back off, leaving anything pointing at them alone."""
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")

    ShartnomaStatus.objects.filter(code__in=[row["code"] for row in WORK_STATUSES]).delete()
    ShartnomaStatus.objects.filter(name="Bekor qilingan").update(code="")


def carry_statuses_across(apps, schema_editor) -> None:
    """Move each application onto the contract status of the same name.

    A name with no counterpart leaves the application with no status, which
    the column has always allowed: a status that cannot be expressed is
    better left blank than guessed at.
    """
    Application = apps.get_model("xarid", "Application")
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")

    contract_statuses = {status.name: status.pk for status in ShartnomaStatus.objects.all()}

    for application in Application.objects.exclude(status__isnull=True).select_related("status"):
        was = application.status.name
        Application.objects.filter(pk=application.pk).update(
            shartnoma_status_id=contract_statuses.get(BY_NAME.get(was, was))
        )


def carry_statuses_back(apps, schema_editor) -> None:
    """The mirror, for a downgrade: back onto the Ariza Status of that name."""
    Application = apps.get_model("xarid", "Application")
    ArizaStatus = apps.get_model("xarid", "ArizaStatus")

    application_statuses = {status.name: status.pk for status in ArizaStatus.objects.all()}
    backwards = {contract: ariza for ariza, contract in BY_NAME.items()}

    for application in Application.objects.exclude(shartnoma_status__isnull=True):
        was = application.shartnoma_status.name
        Application.objects.filter(pk=application.pk).update(
            status_id=application_statuses.get(backwards.get(was, was))
        )


class Migration(migrations.Migration):

    dependencies = [
        ("xarid", "0013_alter_notification_izoh_alter_notification_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="shartnomastatus",
            name="code",
            field=models.CharField(
                blank=True,
                choices=[
                    ("assigned", "Tayinlangan"),
                    ("accepted", "Qabul qilingan"),
                    ("cancelled", "Bekor qilingan"),
                ],
                help_text=(
                    "How the workflow finds this row. Set on the rows it moves an "
                    "application to by itself and empty on any an administrator adds, "
                    "so that renaming one keeps the workflow working."
                ),
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="shartnomastatus",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("code",),
                name="unique_shartnoma_status_code",
            ),
        ),
        migrations.RunPython(add_work_statuses, drop_work_statuses),
        # The values are moved through a column of their own rather than by
        # altering the one in place: for the moment between the two, a row
        # would otherwise hold an Ariza Status id in a column pointing at the
        # contract statuses, and nothing would say so.
        migrations.AddField(
            model_name="application",
            name="shartnoma_status",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="xarid.shartnomastatus",
            ),
        ),
        migrations.RunPython(carry_statuses_across, carry_statuses_back),
        migrations.RemoveField(model_name="application", name="status"),
        migrations.RenameField(
            model_name="application", old_name="shartnoma_status", new_name="status"
        ),
        migrations.AlterField(
            model_name="application",
            name="status",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "The Shartnoma Status the work is in, which Tayinlangan Arizalar "
                    "shows and its holder moves along. Nullable because DEC-010 lets "
                    "an administrator delete every status, and a master data page "
                    "must not stop the workflow."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="xarid.shartnomastatus",
                verbose_name="Status",
            ),
        ),
    ]
