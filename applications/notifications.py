"""What the system has to tell somebody, and nothing about how it is told.

REQ-ARIZA-013 says information about a specialist's acceptance goes to the
department head. This is that information. It is a record with a recipient,
not a message with a transport: nothing delivers it yet, and TASK-UZK-054 is
the task that makes notifications arrive.

Writing it now rather than waiting is deliberate. The acceptance is the moment
the notification is true, and a system that produces the fact when it happens
can deliver it later; one that waits for a transport has to reconstruct who
should have been told, from a log that also does not exist yet.

The separation is the honest part. A Notification row means "this should reach
that person", and read_at stays null until something has actually shown it to
them. Nothing here sets it, because nothing here shows anything.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import models

from accounts.roles import ADMIN


class Notification(models.Model):
    """Something one person should be told about one application.

    CASCADE on both sides. A notification about a deleted application is
    about nothing, and one addressed to a deleted account has nobody to
    reach - neither is a record worth keeping, which is the opposite of how
    this module treats master data and correct for the same reason: these
    point at the thing rather than describe it.
    """

    class Kind(models.TextChoices):
        """What happened. The wording belongs to whatever renders it."""

        SPECIALIST_ACCEPTED = "specialist_accepted", "Xodim arizani qabul qildi"

    recipient = models.ForeignKey(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Kimga",
    )
    application = models.ForeignKey(
        "applications.Application",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Ariza",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When somebody was actually shown this. Null until then, and "
            "nothing sets it yet: TASK-UZK-054 is what delivers a "
            "notification, and this task only produces one."
        ),
    )

    class Meta:
        ordering = ("-created_at", "-id")
        verbose_name = "Bildirishnoma"
        verbose_name_plural = "Bildirishnomalar"

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.application.ariza_raqami}"


def notify_admins_of_acceptance(application) -> list[Notification]:
    """Tell the department head that a specialist took an application.

    REQ-ARIZA-013 names one department head and DEC-013 makes that Admin, of
    which there may be several. Each gets their own notification rather than
    one being picked: choosing arbitrarily would mean the message reaching
    whoever happened to be created first, and reaching nobody on the day that
    account is deactivated.

    Args:
        application: the one that was accepted.

    Returns:
        The notifications produced, which is empty when there is no active
        Admin at all. That is a real state - an installation mid-handover -
        and it is not this function's business to refuse the acceptance over
        it.
    """
    admins = get_user_model().objects.filter(
        is_active=True, profile__user_type__name=ADMIN
    )

    return Notification.objects.bulk_create(
        [
            Notification(
                recipient=admin,
                application=application,
                kind=Notification.Kind.SPECIALIST_ACCEPTED,
            )
            for admin in admins
        ]
    )
