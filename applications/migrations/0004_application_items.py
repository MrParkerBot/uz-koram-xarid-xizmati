"""Move what an application orders onto its own table (TASK-UZK-026).

One change, in four steps: create the line table, loosen the columns the line
is about to leave, carry every existing application's line into the new table,
then drop those columns.

The whole migration is reversible, not only the RunPython inside it, and that
matters more than it usually does: the last operations drop four columns, so a
one-way migration would put the data beyond reach of anything but a backup.
The loosening step is what earns the word - see the comment on it, because the
order operations are reversed in is the entire reason it exists.

An application with several lines cannot be reversed faithfully - the columns
hold one line and there is nowhere for the rest - so the reverse refuses rather
than dropping the others quietly. That is only reachable once the form has
created a multi-line application, which is exactly when reversing this
migration would lose real orders.
"""

from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError
import django.db.models.deletion


def carry_lines_onto_items(apps, schema_editor):
    """Give every existing application one line, from its own columns."""
    Application = apps.get_model("applications", "Application")
    ApplicationItem = apps.get_model("applications", "ApplicationItem")

    ApplicationItem.objects.bulk_create(
        [
            ApplicationItem(
                application=application,
                mahsulot_turi_id=application.mahsulot_turi_id,
                buyurtma_nomi=application.buyurtma_nomi,
                buyurtma_soni=application.buyurtma_soni,
                olchov_birligi=application.olchov_birligi,
            )
            for application in Application.objects.all()
        ]
    )


def carry_lines_back_onto_applications(apps, schema_editor):
    """Write each application's first line back into its own columns.

    A second and later line has nowhere to go: the columns being restored hold
    exactly one. Rather than lose them silently this refuses, because a
    reverse that quietly drops orders is worse than one that stops.
    """
    Application = apps.get_model("applications", "Application")
    ApplicationItem = apps.get_model("applications", "ApplicationItem")

    crowded = (
        Application.objects.annotate(line_count=models.Count("items"))
        .filter(line_count__gt=1)
        .values_list("ariza_raqami", flat=True)
    )
    if crowded:
        raise IrreversibleError(
            "These applications order more than one line, and the columns "
            "being restored hold one: " + ", ".join(crowded)
        )

    for line in ApplicationItem.objects.all().select_related("application"):
        Application.objects.filter(pk=line.application_id).update(
            mahsulot_turi_id=line.mahsulot_turi_id,
            buyurtma_nomi=line.buyurtma_nomi,
            buyurtma_soni=line.buyurtma_soni,
            olchov_birligi=line.olchov_birligi,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0001_initial"),
        ("applications", "0003_application_rejection"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="buyurtmachi_ismi",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Who asked for this, as REQ-ARIZA-008 collects it: a name "
                    "typed on the form rather than a user chosen from a list. "
                    "DEC-016's approval chain would identify a person, and it "
                    "is not built - which is the same reason sender is "
                    "nullable. Blank because every application that existed "
                    "before the form predates the question."
                ),
                max_length=255,
                verbose_name="Buyurtmachi ismi",
            ),
        ),
        migrations.CreateModel(
            name="ApplicationItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "buyurtma_nomi",
                    models.CharField(
                        max_length=255, verbose_name="Buyurtma nomi"
                    ),
                ),
                (
                    "buyurtma_soni",
                    models.DecimalField(
                        decimal_places=3,
                        max_digits=12,
                        verbose_name="Buyurtma soni",
                    ),
                ),
                (
                    "olchov_birligi",
                    models.CharField(
                        help_text=(
                            "ta, kg, m and so on. Free text: REQ-ARIZA-003 "
                            "gives examples and no page maintains a list of "
                            "units."
                        ),
                        max_length=16,
                        verbose_name="O`lchov birligi",
                    ),
                ),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="applications.application",
                        verbose_name="Ariza",
                    ),
                ),
                (
                    "mahsulot_turi",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="application_items",
                        to="reference.mahsulotturi",
                        verbose_name="Mahsulot Turi",
                    ),
                ),
            ],
            options={
                "verbose_name": "Ariza qatori",
                "verbose_name_plural": "Ariza qatorlari",
                "ordering": ("id",),
            },
        ),
        # The four columns become nullable before they are dropped, and that
        # is what makes the whole migration reversible rather than only the
        # RunPython inside it. Reversing runs the operations backwards: the
        # removals come back first and would re-create NOT NULL columns on
        # rows that have no value for them yet, which fails before the copy
        # gets a chance to fill them. Nullable on the way back, filled by the
        # copy, then NOT NULL again - in that order, because this operation is
        # the last one reversed.
        migrations.AlterField(
            model_name="application",
            name="mahsulot_turi",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="reference.mahsulotturi",
                verbose_name="Mahsulot Turi",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="buyurtma_nomi",
            field=models.CharField(
                max_length=255, null=True, verbose_name="Buyurtma nomi"
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="buyurtma_soni",
            field=models.DecimalField(
                decimal_places=3,
                max_digits=12,
                null=True,
                verbose_name="Buyurtma soni",
            ),
        ),
        migrations.AlterField(
            model_name="application",
            name="olchov_birligi",
            field=models.CharField(
                max_length=16, null=True, verbose_name="O`lchov birligi"
            ),
        ),
        migrations.RunPython(
            carry_lines_onto_items,
            carry_lines_back_onto_applications,
        ),
        migrations.RemoveField(
            model_name="application",
            name="mahsulot_turi",
        ),
        migrations.RemoveField(
            model_name="application",
            name="buyurtma_nomi",
        ),
        migrations.RemoveField(
            model_name="application",
            name="buyurtma_soni",
        ),
        migrations.RemoveField(
            model_name="application",
            name="olchov_birligi",
        ),
    ]
