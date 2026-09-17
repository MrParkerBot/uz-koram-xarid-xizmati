"""Tests for the specialist's acceptance and the status control (TASK-UZK-029).

Three things carry this task.

The acceptance is a different fact from the department's acceptance, and the
record already had fields for the second. A test asserts the Qabul qilingan
date is untouched, because reusing it would be the easy mistake and would make
that column mean two things.

DEC-024 lets Admin move an application after the specialist accepted it. The
acceptance belonged to whoever held it, so moving the work clears it - the
alternative is a record saying the new holder agreed to take something they
have not seen.

And the status: DEC-017 makes the rows editable master data and DEC-009 keeps
a deleted one for the records already pointing at it. So what may be chosen
and what may be displayed are different questions, and there is a test for an
application holding a status nobody may choose any more.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import (
    ADMIN,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    assign_user_type,
)
from applications.models import Application
from applications.notifications import Notification
from reference.models import ArizaStatus, Department, MahsulotTuri


def make_user(type_name: str = ADMIN, first_name: str = "Test"):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name=first_name,
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class SpecialistTestCase(TestCase):
    """An application in a specialist's hands."""

    def setUp(self) -> None:
        self.manager = make_user(ADMIN)
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.specialist = make_user(KATTA_MUTAXASIS, first_name="Alisher")
        self.other_specialist = make_user(KATTA_MUTAXASIS, first_name="Dilnoza")
        self.application = self.assigned_application()
        self.accept_url = reverse(
            "tayinlangan-qabul", args=[self.application.pk]
        )
        self.status_url = reverse(
            "tayinlangan-holat", args=[self.application.pk]
        )

    def unassigned_application(self) -> Application:
        """One that has arrived and been given to nobody."""
        return Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Gayka M10",
                    "buyurtma_soni": 20,
                    "olchov_birligi": "kg",
                }
            ],
            department=self.department,
        )

    def rejected_application(self) -> Application:
        """One that is off the workflow altogether."""
        application = self.unassigned_application()
        application.reject(by=self.manager, comment="Byudjet yo`q.")
        return application

    def assigned_application(self, to=None) -> Application:
        application = Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": 500,
                    "olchov_birligi": "ta",
                }
            ],
            department=self.department,
        )
        application.accept(by=self.manager)
        application.assign(by=self.manager, specialist=to or self.specialist)
        return application

    def told(self) -> str:
        page = self.client.get(reverse("tayinlangan"))

        return " ".join(str(message) for message in page.context["messages"])


class AcceptanceTests(SpecialistTestCase):
    """The holder takes the work."""

    def test_accepting_records_when(self) -> None:
        self.client.force_login(self.specialist)

        self.client.post(self.accept_url)

        self.application.refresh_from_db()
        self.assertIsNotNone(self.application.xodim_qabul_qilgan_sana)
        self.assertTrue(self.application.is_taken)

    def test_it_does_not_touch_the_departments_acceptance(self) -> None:
        # The record already had a Qabul qilingan date, and it means when the
        # department accepted the application - not when the specialist took
        # it. One column for both would make that column unreadable.
        before = Application.objects.get(pk=self.application.pk)
        self.client.force_login(self.specialist)

        self.client.post(self.accept_url)

        self.application.refresh_from_db()
        self.assertEqual(
            self.application.qabul_qilingan_sana, before.qabul_qilingan_sana
        )
        self.assertEqual(self.application.accepted_by, before.accepted_by)

    def test_the_stage_does_not_move(self) -> None:
        # Nothing names a stage after assigned, and DEC-024 needs assign() to
        # keep working afterwards - a new stage would quietly close that door.
        self.client.force_login(self.specialist)

        self.client.post(self.accept_url)

        self.application.refresh_from_db()
        self.assertEqual(self.application.stage, Application.Stage.ASSIGNED)

    def test_the_second_click_does_not_re_stamp(self) -> None:
        self.client.force_login(self.specialist)
        self.client.post(self.accept_url)
        self.application.refresh_from_db()
        first = self.application.xodim_qabul_qilgan_sana

        self.client.post(self.accept_url)

        self.application.refresh_from_db()
        self.assertEqual(self.application.xodim_qabul_qilgan_sana, first)

    def test_a_specialist_cannot_accept_somebody_elses(self) -> None:
        theirs = self.assigned_application(to=self.other_specialist)
        self.client.force_login(self.specialist)

        response = self.client.post(
            reverse("tayinlangan-qabul", args=[theirs.pk])
        )

        theirs.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(theirs.is_taken)

    def test_a_manager_accepts_on_the_holders_behalf(self) -> None:
        # The record says the specialist took it, because that is what it is
        # for - not that the manager did.
        self.client.force_login(self.manager)

        self.client.post(self.accept_url)

        self.application.refresh_from_db()
        self.assertTrue(self.application.is_taken)
        self.assertEqual(self.application.assigned_to, self.specialist)

    def test_get_is_refused(self) -> None:
        self.client.force_login(self.specialist)

        self.assertEqual(self.client.get(self.accept_url).status_code, 405)

    def test_somebody_who_may_not_open_the_page_may_not_accept(self) -> None:
        self.client.force_login(make_user(DIREKTOR))

        response = self.client.post(self.accept_url)

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.application.is_taken)


class NotificationTests(SpecialistTestCase):
    """The second half of REQ-ARIZA-013: Admin is told."""

    def test_accepting_notifies_admin(self) -> None:
        self.client.force_login(self.specialist)

        self.client.post(self.accept_url)

        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.manager)
        self.assertEqual(notification.application, self.application)
        self.assertEqual(
            notification.kind, Notification.Kind.SPECIALIST_ACCEPTED
        )

    def test_every_admin_is_told_rather_than_one_of_them(self) -> None:
        second_admin = make_user(ADMIN)
        self.client.force_login(self.specialist)

        self.client.post(self.accept_url)

        self.assertEqual(
            set(
                Notification.objects.values_list("recipient", flat=True)
            ),
            {self.manager.pk, second_admin.pk},
        )

    def test_nobody_else_is_told(self) -> None:
        make_user(MENEJER)
        self.client.force_login(self.specialist)

        self.client.post(self.accept_url)

        self.assertEqual(Notification.objects.count(), 1)

    def test_a_second_click_does_not_notify_twice(self) -> None:
        self.client.force_login(self.specialist)

        self.client.post(self.accept_url)
        self.client.post(self.accept_url)

        self.assertEqual(Notification.objects.count(), 1)

    def test_nothing_has_been_delivered(self) -> None:
        # read_at stays null: this task produces notifications and
        # TASK-UZK-054 is what makes one arrive.
        self.client.force_login(self.specialist)

        self.client.post(self.accept_url)

        self.assertIsNone(Notification.objects.get().read_at)


class ReAssignmentClearsAcceptanceTests(SpecialistTestCase):
    """DEC-024 allows the move; the acceptance does not travel with it."""

    def test_moving_the_work_clears_the_acceptance(self) -> None:
        self.client.force_login(self.specialist)
        self.client.post(self.accept_url)

        self.application.assign(
            by=self.manager, specialist=self.other_specialist
        )

        self.application.refresh_from_db()
        self.assertFalse(self.application.is_taken)

    def test_the_new_holder_can_accept_it_themselves(self) -> None:
        self.client.force_login(self.specialist)
        self.client.post(self.accept_url)
        self.application.assign(
            by=self.manager, specialist=self.other_specialist
        )

        self.client.force_login(self.other_specialist)
        self.client.post(self.accept_url)

        self.application.refresh_from_db()
        self.assertTrue(self.application.is_taken)


class StatusTests(SpecialistTestCase):
    """Marking where the work has got to."""

    def setUp(self) -> None:
        super().setUp()
        self.status = ArizaStatus.objects.filter(is_active=True).first()

    def test_setting_a_status_stores_it(self) -> None:
        self.client.force_login(self.specialist)

        self.client.post(self.status_url, {"status": self.status.pk})

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, self.status)

    def test_the_list_shows_it(self) -> None:
        self.client.force_login(self.specialist)

        self.client.post(self.status_url, {"status": self.status.pk})

        self.assertIn(
            self.status.name,
            self.client.get(reverse("tayinlangan")).content.decode(),
        )

    def test_only_active_statuses_are_offered(self) -> None:
        retired = ArizaStatus.objects.create(
            name="Eskirgan holat", position=99, is_active=False
        )
        self.client.force_login(self.specialist)

        page = self.client.get(reverse("tayinlangan")).content.decode()

        self.assertNotIn(retired.name, page)

    def test_an_inactive_status_cannot_be_set(self) -> None:
        retired = ArizaStatus.objects.create(
            name="Eskirgan holat", position=99, is_active=False
        )
        self.client.force_login(self.specialist)

        self.client.post(self.status_url, {"status": retired.pk})

        self.application.refresh_from_db()
        self.assertNotEqual(self.application.status, retired)

    def test_a_status_retired_after_it_was_set_still_renders(self) -> None:
        # DEC-009 keeps the row for the records already pointing at it, so
        # what may be chosen and what may be shown are different questions.
        self.client.force_login(self.specialist)
        self.client.post(self.status_url, {"status": self.status.pk})
        self.status.is_active = False
        self.status.save(update_fields=["is_active"])

        self.assertIn(
            self.status.name,
            self.client.get(reverse("tayinlangan")).content.decode(),
        )

    def test_choosing_nothing_is_refused(self) -> None:
        self.client.force_login(self.specialist)

        self.client.post(self.status_url, {"status": ""})

        self.application.refresh_from_db()
        self.assertIsNotNone(self.told())

    def test_a_choice_that_is_not_a_number_is_refused_rather_than_crashing(
        self,
    ) -> None:
        # The #35 review found this shape on the assignment route. Applied
        # here before review rather than after it.
        self.client.force_login(self.specialist)

        response = self.client.post(self.status_url, {"status": "abc"})

        self.assertEqual(response.status_code, 302)

    def test_a_specialist_cannot_set_a_status_on_somebody_elses(self) -> None:
        theirs = self.assigned_application(to=self.other_specialist)
        self.client.force_login(self.specialist)

        response = self.client.post(
            reverse("tayinlangan-holat", args=[theirs.pk]),
            {"status": self.status.pk},
        )

        theirs.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(theirs.status, self.status)

    def test_a_manager_may_set_one(self) -> None:
        self.client.force_login(self.manager)

        self.client.post(self.status_url, {"status": self.status.pk})

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, self.status)

    def test_get_is_refused(self) -> None:
        self.client.force_login(self.specialist)

        self.assertEqual(self.client.get(self.status_url).status_code, 405)

    def test_an_application_nobody_holds_has_no_status_to_report(self) -> None:
        """The #40 review found this route writing rows off its own page.

        A manager could reach any application by its pk and move it to a
        status - including a rejected one, which is off the workflow
        entirely.
        """
        for label, application in (
            ("incoming", self.unassigned_application()),
            ("rejected", self.rejected_application()),
        ):
            with self.subTest(application=label):
                before = application.status
                self.client.force_login(self.manager)

                self.client.post(
                    reverse("tayinlangan-holat", args=[application.pk]),
                    {"status": self.status.pk},
                )

                application.refresh_from_db()
                self.assertEqual(application.status, before)

    def test_the_refusal_says_the_application_is_not_assigned(self) -> None:
        waiting = self.unassigned_application()
        self.client.force_login(self.manager)

        self.client.post(
            reverse("tayinlangan-holat", args=[waiting.pk]),
            {"status": self.status.pk},
        )

        self.assertIn("tayinlanmagan", self.told())

    def test_the_status_column_has_a_save_button(self) -> None:
        # Submitting when the value changes is what the first version did,
        # and it makes the control unusable with arrow keys: every option on
        # the way to the wanted one submits.
        self.client.force_login(self.specialist)

        self.assertIn(
            "Saqlash",
            self.client.get(reverse("tayinlangan")).content.decode(),
        )
