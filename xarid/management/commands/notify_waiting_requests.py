"""Tell whoever a purchase request is waiting for, where nobody was told.

Notifications along DEC-016's chain were added after this application had
already been used, so a request approved before then moved on without anybody
hearing about it and will never hear about it by itself: nothing replays a
transition that has already happened.

This walks the requests that are still in flight and delivers the notification
their current step would have produced. It is safe to run more than once - a
step that has already been told is skipped - so it can be run after a
deployment without anybody having to work out what it would do.

    python manage.py notify_waiting_requests
    python manage.py notify_waiting_requests --check
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from xarid.models import Application, Notification, PurchaseApplication
from xarid.notifications import tell_whoever_it_now_waits_for

# The steps something can still be waiting at. A refused request waits for
# nobody, and an approved one whose application has been taken up is done.
IN_FLIGHT = (
    PurchaseApplication.Stage.AWAITING_HEAD,
    PurchaseApplication.Stage.AWAITING_DIREKTOR,
    PurchaseApplication.Stage.APPROVED,
)

# What the current step would have written, so a request that already carries
# it is left alone rather than told twice.
KIND_OF_STEP = {
    PurchaseApplication.Stage.AWAITING_HEAD: Notification.Kind.PURCHASE_AWAITING_YOU,
    PurchaseApplication.Stage.AWAITING_DIREKTOR: Notification.Kind.PURCHASE_AWAITING_YOU,
    PurchaseApplication.Stage.APPROVED: Notification.Kind.PURCHASE_ARRIVED,
}


class Command(BaseCommand):
    help = "Deliver the missing 'this is waiting for you' notification of each request."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Say what would be delivered without writing anything.",
        )

    def handle(self, *args, **options) -> None:
        waiting = (
            PurchaseApplication.objects.filter(stage__in=IN_FLIGHT)
            .select_related("department", "created_by", "raised_application")
            .order_by("id")
        )

        delivered = 0
        for application in waiting:
            if self.already_told(application) or self.taken_up(application):
                continue

            if options["check"]:
                self.stdout.write(f"would tell: {application.xarid_raqami} ({application.stage})")
                delivered += 1
                continue

            told = tell_whoever_it_now_waits_for(application)
            if told:
                names = ", ".join(sorted(one.recipient.get_username() for one in told))
                self.stdout.write(f"{application.xarid_raqami}: told {names}")
                delivered += 1

        outcome = "to tell" if options["check"] else "told"
        self.stdout.write(self.style.SUCCESS(f"{delivered} request(s) {outcome}."))

    @staticmethod
    def already_told(application: PurchaseApplication) -> bool:
        """Whether somebody has already been told about this request's step."""
        return Notification.objects.filter(
            purchase_application=application, kind=KIND_OF_STEP[application.stage]
        ).exists()

    @staticmethod
    def taken_up(application: PurchaseApplication) -> bool:
        """Whether the purchasing department has already got on with it.

        An approved request whose application has been accepted is off Kelib
        Tushgan Arizalar and out of everybody's queue. Announcing its arrival
        now would be telling people about work they have already done.
        """
        raised = application.raised_application

        return raised is not None and raised.stage != Application.Stage.INCOMING
