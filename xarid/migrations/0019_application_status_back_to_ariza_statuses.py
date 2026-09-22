"""An assigned application reports an Ariza Status again, not a contract one.

0014 pointed Application.status at the contract statuses so that Tayinlangan
Arizalar could say how far the work had got. The column that resulted offers
names that are not on the Ariza Status page - "Shartnoma tuzilgan",
"Yetkazib berilgan" - which is not what the page is read as saying, so the
column goes back to the Ariza Statuses and offers exactly the four rows that
page holds.

What an application cannot say any more it does not say: a row at a contract
status with no Ariza Status of that name is left with none, which the column
has always allowed, rather than being moved to a neighbouring state nobody
chose. Reporting the later stages of the work is a thing this page no longer
does; the contract's own status column on Kelishinlingan still does it.

0014's two additions to the contract statuses go with it - the pre-contract
rows "Tayinlangan" and "Qabul qilingan", which no contract is ever in, and
the code column DEC-010 says these rows must not carry.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models

# The one name that differs between the two tables. The others - "Qabul
# qilingan", "Tayinlangan", "Bekor qilingan" - are spelled the same on both.
BY_NAME = {"Boshlang`ich xolatda": "Yangi"}

# The rows 0014 put on the contract status list for the part of the work that
# happens before there is a contract.
WORK_STATUS_CODES = ("assigned", "accepted")


def carry_statuses_back(apps, schema_editor) -> None:
    """Move each application onto the Ariza Status of the same name.

    A contract status with no counterpart - "Birjaga qo`yilgan" and the two
    after it - leaves the application with no status. A status that cannot be
    expressed is better left blank than guessed at.
    """
    Application = apps.get_model("xarid", "Application")
    ArizaStatus = apps.get_model("xarid", "ArizaStatus")

    application_statuses = {status.name: status.pk for status in ArizaStatus.objects.all()}

    for application in Application.objects.exclude(status__isnull=True).select_related("status"):
        was = application.status.name
        Application.objects.filter(pk=application.pk).update(
            ariza_status_id=application_statuses.get(BY_NAME.get(was, was))
        )


def carry_statuses_across(apps, schema_editor) -> None:
    """The mirror, for a downgrade: back onto the contract status of that name."""
    Application = apps.get_model("xarid", "Application")
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")

    contract_statuses = {status.name: status.pk for status in ShartnomaStatus.objects.all()}
    forwards = {ariza: contract for contract, ariza in BY_NAME.items()}

    for application in Application.objects.exclude(ariza_status__isnull=True).select_related(
        "ariza_status"
    ):
        was = application.ariza_status.name
        Application.objects.filter(pk=application.pk).update(
            status_id=contract_statuses.get(forwards.get(was, was))
        )


def drop_work_statuses(apps, schema_editor) -> None:
    """Take 0014's two pre-contract rows off the contract status list.

    Deactivated rather than deleted when a contract was somehow moved to one:
    the column is PROTECTed, and a migration that can fail on a row somebody
    created is worse than a status nobody is offered any more.
    """
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")

    for status in ShartnomaStatus.objects.filter(code__in=WORK_STATUS_CODES):
        if status.contracts.exists() or status.moves_here.exists() or status.moves_away.exists():
            ShartnomaStatus.objects.filter(pk=status.pk).update(is_active=False, code="")
        else:
            ShartnomaStatus.objects.filter(pk=status.pk).delete()

    # 0014 gave the cancelled row a code so the workflow could cancel an
    # application by it; nothing reads a contract status by code now.
    ShartnomaStatus.objects.filter(name="Bekor qilingan").update(code="")


def add_work_statuses(apps, schema_editor) -> None:
    """The mirror, for a downgrade: 0014's rows, as 0014 wrote them."""
    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")

    for row in (
        {"name": "Tayinlangan", "code": "assigned", "position": 5, "badge_colour": "gray"},
        {"name": "Qabul qilingan", "code": "accepted", "position": 8, "badge_colour": "blue"},
    ):
        ShartnomaStatus.objects.update_or_create(
            name=row["name"],
            defaults={
                "code": row["code"],
                "position": row["position"],
                "badge_colour": row["badge_colour"],
                "is_active": True,
            },
        )

    ShartnomaStatus.objects.filter(name="Bekor qilingan", code="").update(code="cancelled")


class Migration(migrations.Migration):

    dependencies = [
        ("xarid", "0018_alter_notification_kind"),
    ]

    operations = [
        # Through a column of its own, for the reason 0014 gave: altering the
        # one in place would leave every row holding a contract status id in a
        # column pointing at the Ariza Statuses, with nothing to say so.
        migrations.AddField(
            model_name="application",
            name="ariza_status",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="xarid.arizastatus",
            ),
        ),
        migrations.RunPython(carry_statuses_back, carry_statuses_across),
        migrations.RemoveField(model_name="application", name="status"),
        migrations.RenameField(
            model_name="application", old_name="ariza_status", new_name="status"
        ),
        migrations.AlterField(
            model_name="application",
            name="status",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "The Ariza Status the work is in, which Tayinlangan Arizalar "
                    "shows and its holder moves along. Nullable because DEC-017 lets "
                    "an administrator delete every status, and a master data page "
                    "must not stop the workflow."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="xarid.arizastatus",
                verbose_name="Status",
            ),
        ),
        migrations.RunPython(drop_work_statuses, add_work_statuses),
        migrations.RemoveConstraint(
            model_name="shartnomastatus",
            name="unique_shartnoma_status_code",
        ),
        migrations.RemoveField(model_name="shartnomastatus", name="code"),
    ]
