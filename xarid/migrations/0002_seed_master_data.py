"""Seed the master data the application cannot start without.

- The six User Types DEC-013 fixes, marked as system roles because the
  permission matrix names them.
- The four application statuses DEC-017 names, with the codes the workflow
  finds them by and the order the work moves through them.
- The five contract statuses DEC-010 names, in workflow order.
- The two contract types DEC-023 names.

Everything is written as literals rather than imported from the models: a
migration has to keep working when the code around it changes. Rows that
already exist are left alone.
"""

from django.db import migrations

POSITION_STEP = 10

DEPARTMENT_USER_TYPES = (
    "Admin",
    "Bo`lim Boshlig`i",
    "Menejer",
    "Katta Mutaxasis",
    "Direktor",
    "Users",
)

# (name, code, badge colour), in workflow order.
ARIZA_STATUSES = (
    ("Yangi", "new", "blue"),
    ("Qabul qilingan", "accepted", "green"),
    ("Tayinlangan", "assigned", "orange"),
    ("Bekor qilingan", "cancelled", "gray"),
)

# (name, badge colour), in workflow order.
SHARTNOMA_STATUSES = (
    ("Boshlang`ich xolatda", "blue"),
    ("Birjaga qo`yilgan", "yellow"),
    ("Shartnoma tuzilgan", "orange"),
    ("Yetkazib berilgan", "green"),
    ("Bekor qilingan", "gray"),
)

SHARTNOMA_TURLARI = ("Import", "Mahalliy (Local)")


def seed(apps, schema_editor):
    UserType = apps.get_model("xarid", "UserType")
    for name in DEPARTMENT_USER_TYPES:
        UserType.objects.get_or_create(name=name, defaults={"is_system_role": True})

    ArizaStatus = apps.get_model("xarid", "ArizaStatus")
    for position, (name, code, badge_colour) in enumerate(ARIZA_STATUSES, start=1):
        ArizaStatus.objects.get_or_create(
            name=name,
            defaults={
                "code": code,
                "badge_colour": badge_colour,
                "position": position * POSITION_STEP,
            },
        )

    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")
    for position, (name, badge_colour) in enumerate(SHARTNOMA_STATUSES, start=1):
        ShartnomaStatus.objects.get_or_create(
            name=name,
            defaults={"badge_colour": badge_colour, "position": position * POSITION_STEP},
        )

    ShartnomaTuri = apps.get_model("xarid", "ShartnomaTuri")
    for name in SHARTNOMA_TURLARI:
        ShartnomaTuri.objects.get_or_create(name=name)


def unseed(apps, schema_editor):
    """Remove the seeded rows nothing refers to; protected rows stay."""
    UserType = apps.get_model("xarid", "UserType")
    UserType.objects.filter(name__in=DEPARTMENT_USER_TYPES, users__isnull=True).delete()

    ArizaStatus = apps.get_model("xarid", "ArizaStatus")
    ArizaStatus.objects.filter(
        name__in=[name for name, _, _ in ARIZA_STATUSES],
        applications__isnull=True,
        purchase_applications__isnull=True,
    ).delete()

    ShartnomaStatus = apps.get_model("xarid", "ShartnomaStatus")
    ShartnomaStatus.objects.filter(
        name__in=[name for name, _ in SHARTNOMA_STATUSES], contracts__isnull=True
    ).delete()

    ShartnomaTuri = apps.get_model("xarid", "ShartnomaTuri")
    ShartnomaTuri.objects.filter(name__in=SHARTNOMA_TURLARI, contracts__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("xarid", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
