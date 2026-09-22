"""Tests for the sender notifications and their panel (TASK-UZK-054).

Accepting an application tells its sender; refusing tells them why. Delivery
is in-app and nothing else - a panel entry and a number on the bell (DEC-012)
- and a delivery that fails leaves the decision it followed standing.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import DatabaseError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.support import (
    a_category,
    a_department,
    a_pdf,
    a_purchase_application,
    an_application,
    make_user,
    page,
)
from xarid.models import (
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    Application,
    Notification,
    PurchaseApplication,
)
from xarid.notifications import (
    tell_sender_of_acceptance,
    tell_whoever_it_now_waits_for,
    unread_for,
)

# What the panel says when there is nothing in it.
EMPTY_PANEL = "Bildirishnomalar yo'q."


class DecidingTellsTheSenderTests(TestCase):
    """What a decision writes for the person who sent the application."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department()
        cls.manager = make_user("tell.manager", user_type=MENEJER, department=cls.department)
        cls.requester = make_user("tell.requester", user_type=USERS, department=cls.department)

    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.manager)

    def a_sent_application(self) -> Application:
        application = an_application(department=self.department)
        Application.objects.filter(pk=application.pk).update(sender=self.requester)
        application.refresh_from_db()
        return application

    def test_accepting_tells_the_sender(self) -> None:
        application = self.a_sent_application()

        self.client.post(page("ariza-qabul", application.pk))

        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.requester)
        self.assertEqual(notification.kind, Notification.Kind.APPLICATION_ACCEPTED)
        self.assertEqual(notification.application, application)
        self.assertIsNone(notification.read_at)

    def test_refusing_tells_the_sender_why(self) -> None:
        application = self.a_sent_application()

        self.client.post(
            page("ariza-inkor", application.pk), {"inkor_izohi": "Narx noto'g'ri"}
        )

        notification = Notification.objects.get()
        self.assertEqual(notification.kind, Notification.Kind.APPLICATION_REJECTED)
        self.assertEqual(notification.izoh, "Narx noto'g'ri")

    def test_an_application_with_no_sender_tells_nobody(self) -> None:
        """One entered on the Qabul qilingan page has no requester (DEC-031)."""
        application = an_application(department=self.department)

        response = self.client.post(page("ariza-qabul", application.pk), follow=True)

        self.assertContains(response, "qabul qilindi")
        self.assertFalse(Notification.objects.exists())

    def test_accepting_twice_tells_the_sender_once(self) -> None:
        application = self.a_sent_application()

        self.client.post(page("ariza-qabul", application.pk))
        self.client.post(page("ariza-qabul", application.pk))

        self.assertEqual(Notification.objects.count(), 1)

    def test_a_refused_decision_tells_nobody(self) -> None:
        application = self.a_sent_application()

        self.client.post(page("ariza-inkor", application.pk), {"inkor_izohi": "   "})

        self.assertFalse(Notification.objects.exists())

    def test_a_delivery_that_fails_leaves_the_decision_standing(self) -> None:
        application = self.a_sent_application()

        with patch(
            "xarid.notifications.Notification.objects.create",
            side_effect=DatabaseError("no room"),
        ), self.assertLogs("xarid.notifications", level="ERROR"):
            response = self.client.post(page("ariza-qabul", application.pk), follow=True)

        application.refresh_from_db()
        self.assertEqual(application.stage, Application.Stage.ACCEPTED)
        self.assertContains(response, "qabul qilindi")
        self.assertFalse(Notification.objects.exists())


class PurchaseRequestNotificationTests(TestCase):
    """Both ends of DEC-016's chain hear about a purchase request."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.purchasing = a_department("Xarid bo`limi")
        cls.purchasing.is_purchasing = True
        cls.purchasing.save(update_fields=["is_purchasing"])
        cls.department = a_department("Ishlab chiqarish")
        cls.requester = make_user("note.requester", user_type=USERS, department=cls.department)
        cls.head = make_user("note.head", user_type=BOLIM_BOSHLIGI, department=cls.department)
        cls.other_head = make_user(
            "note.other.head", user_type=BOLIM_BOSHLIGI, department=a_department("Buxgalteriya")
        )
        cls.direktor = make_user("note.direktor", user_type=DIREKTOR)
        cls.xarid_head = make_user(
            "note.xarid.head", user_type=BOLIM_BOSHLIGI, department=cls.purchasing
        )
        cls.xarid_menejer = make_user(
            "note.xarid.menejer", user_type=MENEJER, department=cls.purchasing
        )

    def raise_one(self) -> PurchaseApplication:
        self.client.force_login(self.requester)
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        return request

    def kinds_for(self, user) -> list[str]:
        return list(
            Notification.objects.filter(recipient=user)
            .order_by("id")
            .values_list("kind", flat=True)
        )

    def test_raising_one_tells_the_head_it_waits_for_and_nobody_else(self) -> None:
        self.client.force_login(self.requester)
        fields = {
            "shartnoma_nomi": "Kabel xaridi",
            "muddat_talabi": "",
            "izoh": "",
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-mahsulot_turi": a_category().pk,
            "form-0-buyurtma_nomi": "Kabel 4mm",
            "form-0-buyurtma_soni": "200",
            "form-0-olchov_birligi": "m",
            "pdf": a_pdf(),
        }

        self.client.post(page("xarid-ariza-yaratish"), fields)

        self.assertEqual(
            self.kinds_for(self.head), [Notification.Kind.PURCHASE_AWAITING_YOU]
        )
        self.assertEqual(self.kinds_for(self.other_head), [])
        self.assertEqual(self.kinds_for(self.direktor), [])
        self.assertEqual(self.kinds_for(self.requester), [])

    def test_the_message_says_what_the_request_is_without_opening_it(self) -> None:
        request = self.raise_one()
        self.client.force_login(self.head)
        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))

        told = Notification.objects.get(recipient=self.direktor)

        self.assertEqual(told.kind, Notification.Kind.PURCHASE_AWAITING_YOU)
        self.assertIn("Kabel xaridi", told.izoh)
        self.assertIn(self.department.name, told.izoh)
        self.assertIn("note.requester", told.izoh)

    def test_the_head_s_approval_tells_the_requester_and_the_direktor(self) -> None:
        request = self.raise_one()
        self.client.force_login(self.head)

        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))

        self.assertEqual(
            self.kinds_for(self.requester), [Notification.Kind.PURCHASE_APPROVED_BY_HEAD]
        )
        self.assertEqual(
            self.kinds_for(self.direktor), [Notification.Kind.PURCHASE_AWAITING_YOU]
        )

    def test_the_direktor_s_approval_tells_the_requester_and_xarid_bolimi(self) -> None:
        request = self.raise_one()
        request.approve(by=self.head)
        self.client.force_login(self.direktor)

        self.client.post(page("xarid-ariza-tasdiqlash", request.pk))

        self.assertEqual(
            self.kinds_for(self.requester), [Notification.Kind.PURCHASE_APPROVED]
        )
        for worker in (self.xarid_head, self.xarid_menejer):
            with self.subTest(worker=worker.get_username()):
                self.assertEqual(
                    self.kinds_for(worker), [Notification.Kind.PURCHASE_ARRIVED]
                )

    def test_a_refusal_tells_the_requester_and_carries_the_reason(self) -> None:
        request = self.raise_one()
        self.client.force_login(self.head)

        self.client.post(
            page("xarid-ariza-inkor", request.pk), {"inkor_izohi": "Byudjet yetarli emas"}
        )

        told = Notification.objects.get(recipient=self.requester)
        self.assertEqual(told.kind, Notification.Kind.PURCHASE_REJECTED)
        self.assertEqual(told.izoh, "Byudjet yetarli emas")
        # A refused request waits for nobody, so nobody is told it is theirs.
        self.assertEqual(self.kinds_for(self.direktor), [])

    def test_a_head_raising_their_own_is_not_told_it_waits_for_them(self) -> None:
        request = a_purchase_application(self.head, self.department, with_pdf=False)

        tell_whoever_it_now_waits_for(request)

        self.assertEqual(self.kinds_for(self.head), [])

    def test_nothing_is_told_when_no_purchasing_department_is_named(self) -> None:
        """An ordinary state, not a fault: the notification simply has nobody."""
        self.purchasing.is_purchasing = False
        self.purchasing.save(update_fields=["is_purchasing"])
        request = self.raise_one()
        request.approve(by=self.head)
        request.approve(by=self.direktor)

        self.assertEqual(tell_whoever_it_now_waits_for(request), [])

    def test_a_delivery_that_fails_leaves_the_approval_standing(self) -> None:
        request = self.raise_one()
        self.client.force_login(self.head)

        with patch.object(
            Notification.objects, "bulk_create", side_effect=DatabaseError("no")
        ):
            self.client.post(page("xarid-ariza-tasdiqlash", request.pk))

        request.refresh_from_db()
        self.assertEqual(request.stage, PurchaseApplication.Stage.AWAITING_DIREKTOR)


class CatchingUpOnWaitingRequestsTests(TestCase):
    """notify_waiting_requests: the requests that moved before anybody was told."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department("Ishlab chiqarish")
        cls.requester = make_user(
            "catch.requester", user_type=USERS, department=cls.department
        )
        cls.head = make_user("catch.head", user_type=BOLIM_BOSHLIGI, department=cls.department)
        cls.direktor = make_user("catch.direktor", user_type=DIREKTOR)

    def run_command(self, **options) -> str:
        output = StringIO()
        call_command("notify_waiting_requests", stdout=output, **options)
        return output.getvalue()

    def waiting_for_the_direktor(self) -> PurchaseApplication:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        request.approve(by=self.head)
        Notification.objects.all().delete()
        return request

    def test_it_tells_whoever_a_request_is_standing_on(self) -> None:
        request = self.waiting_for_the_direktor()

        self.run_command()

        told = Notification.objects.get(recipient=self.direktor)
        self.assertEqual(told.purchase_application, request)
        self.assertEqual(told.kind, Notification.Kind.PURCHASE_AWAITING_YOU)

    def test_running_it_twice_does_not_tell_anybody_twice(self) -> None:
        self.waiting_for_the_direktor()

        self.run_command()
        self.run_command()

        self.assertEqual(Notification.objects.filter(recipient=self.direktor).count(), 1)

    def test_check_writes_nothing(self) -> None:
        request = self.waiting_for_the_direktor()

        printed = self.run_command(check=True)

        self.assertIn(request.xarid_raqami, printed)
        self.assertFalse(Notification.objects.exists())

    def test_a_refused_request_waits_for_nobody(self) -> None:
        request = a_purchase_application(self.requester, self.department, with_pdf=False)
        request.reject(by=self.head, comment="Byudjet yetarli emas")
        Notification.objects.all().delete()

        self.run_command()

        self.assertFalse(Notification.objects.exists())


class UnreadCountTests(TestCase):
    """The number on the bell."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department()
        cls.requester = make_user("bell.requester", user_type=USERS, department=cls.department)
        cls.other = make_user("bell.other", user_type=USERS, department=cls.department)

    def a_notification_for(self, person) -> Notification:
        application = an_application(department=self.department)
        Application.objects.filter(pk=application.pk).update(sender=person)
        application.refresh_from_db()
        return tell_sender_of_acceptance(application)

    def test_it_counts_only_this_person_s_unread(self) -> None:
        self.a_notification_for(self.requester)
        self.a_notification_for(self.other)

        self.assertEqual(unread_for(self.requester), 1)

    def test_a_read_notification_is_not_counted(self) -> None:
        notification = self.a_notification_for(self.requester)
        Notification.objects.filter(pk=notification.pk).update(read_at=timezone.now())

        self.assertEqual(unread_for(self.requester), 0)

    def test_an_anonymous_visitor_counts_nothing(self) -> None:
        self.assertEqual(unread_for(None), 0)

    def test_the_header_shows_the_badge_only_when_there_is_something(self) -> None:
        self.client.force_login(self.requester)

        without = self.client.get(page("xarid-ariza")).content.decode()
        self.a_notification_for(self.requester)
        with_one = self.client.get(page("xarid-ariza")).content.decode()

        self.assertNotIn("data-unread-count", without)
        self.assertIn("data-unread-count", with_one)


class NotificationsPanelTests(TestCase):
    """The page itself."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.department = a_department()
        cls.requester = make_user("panel.requester", user_type=USERS, department=cls.department)
        cls.other = make_user("panel.other", user_type=USERS, department=cls.department)

    def a_notification_for(self, person, comment: str = "") -> Notification:
        application = an_application(department=self.department)
        Application.objects.filter(pk=application.pk).update(sender=person)
        application.refresh_from_db()
        return Notification.objects.create(
            recipient=person,
            application=application,
            kind=Notification.Kind.APPLICATION_REJECTED,
            izoh=comment,
        )

    def test_it_shows_your_own_notifications_and_their_comment(self) -> None:
        self.a_notification_for(self.requester, comment="Narx noto'g'ri")
        self.client.force_login(self.requester)

        response = self.client.get(page("notifications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Arizangiz inkor etildi")
        self.assertContains(response, "Narx noto&#39;g&#39;ri")

    def test_it_does_not_show_somebody_else_s(self) -> None:
        self.a_notification_for(self.other, comment="Boshqaning xabari")
        self.client.force_login(self.requester)

        response = self.client.get(page("notifications"))

        self.assertNotContains(response, "Boshqaning xabari")
        self.assertContains(response, EMPTY_PANEL)

    def marking_predicate(self, queries: CaptureQueriesContext) -> str:
        """Which rows the panel's one marking statement chose, as SQL.

        The statement is picked out by the table it writes to rather than by
        position: the session has its own writes, and which of them run
        depends on how the test client signed this person in.

        Only the predicate is returned. The value half sets read_at to the
        moment it ran, which is different on every request and is not what
        this is asking about - the question is whether choosing the rows
        costs a bound parameter each.
        """
        written = [
            query["sql"]
            for query in queries
            if query["sql"].lstrip().upper().startswith("UPDATE")
            and Notification._meta.db_table in query["sql"]
        ]

        self.assertEqual(len(written), 1, "the panel should mark read in one statement")

        return written[0].split(" WHERE ", 1)[-1]

    def test_it_marks_read_without_listing_every_notification(self) -> None:
        """One statement over this person's unread rows, not one id each.

        SQLite refuses an IN list past its own parameter limit, and nothing
        deletes a notification, so an account that collects enough of them
        would otherwise lose its own panel.

        The assertion is on the statement's own text, not on how many
        statements ran. An IN list naming eight thousand ids is still a
        single query, so counting queries cannot see this fault - which is
        how it survived one review and came back in the next.
        """
        self.client.force_login(self.requester)

        for _ in range(2):
            self.a_notification_for(self.requester)
        with CaptureQueriesContext(connection) as few:
            self.client.get(page("notifications"))

        for _ in range(6):
            self.a_notification_for(self.requester)
        with CaptureQueriesContext(connection) as many:
            self.client.get(page("notifications"))

        # Eight notifications cost what two did, and the statement that marks
        # them is the same text either way: it names the reader, not the rows.
        self.assertEqual(len(many), len(few))
        self.assertEqual(self.marking_predicate(many), self.marking_predicate(few))
        self.assertEqual(unread_for(self.requester), 0)

    def test_the_entries_it_shows_still_say_they_were_new(self) -> None:
        """Read first, marked after: you see what changed before it stops being new."""
        self.a_notification_for(self.requester)
        self.client.force_login(self.requester)

        first = self.client.get(page("notifications"))
        second = self.client.get(page("notifications"))

        self.assertContains(first, "Yangi")
        self.assertNotContains(second, "Yangi")

    def test_opening_it_marks_what_it_showed_as_read(self) -> None:
        notification = self.a_notification_for(self.requester)
        self.client.force_login(self.requester)

        self.client.get(page("notifications"))

        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)
        self.assertEqual(unread_for(self.requester), 0)

    def test_an_anonymous_visitor_is_sent_to_the_login_page(self) -> None:
        response = self.client.get(page("notifications"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.headers["Location"])

    def test_every_signed_in_type_may_open_it(self) -> None:
        """It is nobody's page and everybody's: no DEC-015 entry gates it."""
        for user_type in (USERS, KATTA_MUTAXASIS, MENEJER):
            with self.subTest(user_type=user_type):
                self.client.force_login(make_user(f"panel.{user_type}", user_type=user_type))

                self.assertEqual(self.client.get(page("notifications")).status_code, 200)
