"""Tests for the sender notifications and their panel (TASK-UZK-054).

Accepting an application tells its sender; refusing tells them why. Delivery
is in-app and nothing else - a panel entry and a number on the bell (DEC-012)
- and a delivery that fails leaves the decision it followed standing.
"""

from __future__ import annotations

from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase

from tests.support import a_department, an_application, make_user, page
from xarid.models import (
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    Application,
    Notification,
)
from xarid.notifications import tell_sender_of_acceptance, unread_for

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
        Notification.objects.filter(pk=notification.pk).update(read_at="2026-03-02 12:00+00:00")

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
