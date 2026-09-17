"""Tests for assignment and re-assignment (TASK-UZK-027).

Three things carry this task.

REQ-ARIZA-007 says the drop-down shows specialists. DEC-024 says which
specialists: Katta Mutaxasis and nobody else. A chooser that offers anybody
else lets a manager give work to somebody with no page to see it on, so there
is a test per user type.

DEC-024 also says Admin may re-assign at any time, including after the
specialist accepted. That makes assignment unlike accept(): the assigned stage
is both a destination and a starting point, and there is a test that moves an
application twice.

The third is quieter and matters most. DEC-015 gives Katta Mutaxasis the
Tayinlangan page and not the Qabul qilingan one, so PAGE_SHOWING_STAGE has to
point an assigned application at Tayinlangan - otherwise a specialist cannot
open the attachment on work they were given. There is a test that fetches it
as them.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    assign_user_type,
    assignable_specialists,
)
from applications.models import Application
from applications.tests.test_support import a_pdf
from reference.models import Department, MahsulotTuri


def make_user(type_name: str = ADMIN, first_name: str = "Test"):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name=first_name,
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class AssignmentTestCase(TestCase):
    """An accepted application, a manager, and somebody to give it to."""

    def setUp(self) -> None:
        self.manager = make_user(ADMIN)
        self.client.force_login(self.manager)
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.specialist = make_user(KATTA_MUTAXASIS, first_name="Alisher")
        self.other_specialist = make_user(KATTA_MUTAXASIS, first_name="Dilnoza")
        self.application = self.accepted_application()
        self.url = reverse("ariza-tayinlash", args=[self.application.pk])

    def raise_application(self, **overrides) -> Application:
        line = {
            "mahsulot_turi": self.category,
            "buyurtma_nomi": "Bolt M12",
            "buyurtma_soni": 500,
            "olchov_birligi": "ta",
        }
        fields = {"department": self.department}
        fields.update(overrides)
        return Application.raise_application(items=[line], **fields)

    def accepted_application(self, **overrides) -> Application:
        application = self.raise_application(**overrides)
        application.accept(by=self.manager)
        return application

    def table(self) -> str:
        """The rows, without the page around them.

        The re-assign handler is a script on the page and names its own
        class, so a test about what a row offers has to read the rows.
        """
        page = self.client.get(reverse("qabul-arizalar")).content.decode()
        body = page.split('<tbody id="qabul-tbody">', 1)[1]

        return body.split("</tbody>", 1)[0]

    def assign(self, specialist=None, application=None):
        url = (
            self.url
            if application is None
            else reverse("ariza-tayinlash", args=[application.pk])
        )
        return self.client.post(
            url, {"xodim": (specialist or self.specialist).pk}
        )


class ChooserTests(AssignmentTestCase):
    """Who may be assigned work (DEC-024)."""

    def test_a_katta_mutaxasis_is_offered(self) -> None:
        self.assertIn(self.specialist, assignable_specialists())

    def test_nobody_of_another_type_is_offered(self) -> None:
        for type_name in (ADMIN, BOLIM_BOSHLIGI, MENEJER, DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.assertNotIn(
                    make_user(type_name), assignable_specialists()
                )

    def test_an_inactive_specialist_is_not_offered(self) -> None:
        # Somebody who has left should not be given new work. What they
        # already hold is a separate question, answered below.
        self.specialist.is_active = False
        self.specialist.save(update_fields=["is_active"])

        self.assertNotIn(self.specialist, assignable_specialists())

    def test_the_chooser_offers_the_specialists(self) -> None:
        row = self.table()

        self.assertIn("Alisher", row)
        self.assertIn("Dilnoza", row)


class AssignTests(AssignmentTestCase):
    """Giving an application to somebody."""

    def test_assigning_attaches_it_to_the_specialist(self) -> None:
        self.assign()

        self.application.refresh_from_db()
        self.assertEqual(self.application.assigned_to, self.specialist)

    def test_assigning_records_who_and_when(self) -> None:
        self.assign()

        self.application.refresh_from_db()
        self.assertEqual(self.application.assigned_by, self.manager)
        self.assertIsNotNone(self.application.tayinlangan_sana)

    def test_assigning_moves_it_to_the_assigned_stage(self) -> None:
        self.assign()

        self.application.refresh_from_db()
        self.assertEqual(self.application.stage, Application.Stage.ASSIGNED)

    def test_it_is_still_listed_on_qabul_qilingan(self) -> None:
        # REQ-ARIZA-007 puts re-assignment on this row, so the row has to
        # still be there. A list that dropped it would take the control with
        # it.
        self.assign()

        self.assertIn(self.application.ariza_raqami, self.table())

    def test_an_assigned_row_shows_the_name_and_offers_re_assignment(
        self,
    ) -> None:
        self.assign()
        row = self.table()

        self.assertIn("Alisher", row)
        self.assertIn("js-reassign", row)
        self.assertNotIn('name="xodim"', row)

    def test_an_unassigned_row_offers_the_chooser(self) -> None:
        row = self.table()

        self.assertIn('name="xodim"', row)
        self.assertNotIn("js-reassign", row)

    def test_the_second_click_of_a_double_click_is_not_an_error(self) -> None:
        self.assign()
        self.application.refresh_from_db()
        first_stamp = self.application.tayinlangan_sana

        response = self.assign()

        self.application.refresh_from_db()
        self.assertRedirects(response, reverse("qabul-arizalar"))
        self.assertEqual(self.application.tayinlangan_sana, first_stamp)


class ReAssignTests(AssignmentTestCase):
    """Moving an application to somebody else (DEC-024)."""

    def test_re_assigning_moves_it(self) -> None:
        self.assign()

        self.assign(specialist=self.other_specialist)

        self.application.refresh_from_db()
        self.assertEqual(self.application.assigned_to, self.other_specialist)

    def test_re_assigning_replaces_the_stamp(self) -> None:
        # The first stamp is written explicitly rather than taken from the
        # first assignment. Two timezone.now() calls microseconds apart store
        # as equal at SQLite's resolution, and the #29 review found that shape
        # passing on an idle machine and failing on a busy one. The #35 review
        # found it again here.
        self.assign()
        earlier = timezone.now() - timedelta(hours=2)
        Application.objects.filter(pk=self.application.pk).update(
            tayinlangan_sana=earlier
        )

        self.assign(specialist=self.other_specialist)

        self.application.refresh_from_db()
        self.assertGreater(self.application.tayinlangan_sana, earlier)

    def test_re_assignment_is_allowed_from_the_assigned_stage(self) -> None:
        """DEC-024: a move is allowed at any time, not only before acceptance.

        The specialist's own acceptance is TASK-UZK-029 and does not exist
        yet. What can be pinned now is the half that matters here: assigned
        is a stage assignment moves out of as well as into, so whatever
        TASK-UZK-029 records on top of it cannot close the door.
        """
        self.assign()
        self.application.refresh_from_db()
        self.assertEqual(self.application.stage, Application.Stage.ASSIGNED)

        moved = self.application.assign(
            by=self.manager, specialist=self.other_specialist
        )

        self.assertTrue(moved)

    def test_it_leaves_the_first_specialists_list(self) -> None:
        from applications.views import assigned_applications

        self.assign()
        self.assign(specialist=self.other_specialist)

        self.assertNotIn(
            self.application, assigned_applications(self.specialist)
        )
        self.assertIn(
            self.application, assigned_applications(self.other_specialist)
        )


class RefusalTests(AssignmentTestCase):
    """What assignment will not do."""

    def test_somebody_who_is_not_a_specialist_is_refused(self) -> None:
        manager = make_user(MENEJER)

        self.assign(specialist=manager)

        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)

    def test_choosing_nobody_is_refused(self) -> None:
        response = self.client.post(self.url, {"xodim": ""})

        self.application.refresh_from_db()
        self.assertRedirects(response, reverse("qabul-arizalar"))
        self.assertIsNone(self.application.assigned_to)

    def test_an_incoming_application_cannot_be_assigned(self) -> None:
        waiting = self.raise_application()

        self.assign(application=waiting)

        waiting.refresh_from_db()
        self.assertIsNone(waiting.assigned_to)
        self.assertEqual(waiting.stage, Application.Stage.INCOMING)

    def test_a_rejected_application_cannot_be_assigned(self) -> None:
        refused = self.raise_application()
        refused.reject(by=self.manager, comment="Byudjet yo`q.")

        self.assign(application=refused)

        refused.refresh_from_db()
        self.assertIsNone(refused.assigned_to)

    def test_a_refusal_says_which_refusal_it_is(self) -> None:
        # Two things stop an assignment - the application, and who was chosen
        # - and being told the wrong one sends whoever investigates to the
        # permission matrix for something that has nothing to do with it. The
        # #28 review made this point about rejection.
        waiting = self.raise_application()

        self.assign(application=waiting)
        stale = self.told()

        self.assign(specialist=make_user(MENEJER))
        wrong_person = self.told()

        self.assertIn("qabul qilinmagan", stale)
        self.assertIn("Katta Mutaxasis", wrong_person)

    def told(self) -> str:
        """What the page said after the last redirect, as one string."""
        page = self.client.get(reverse("qabul-arizalar"))

        return " ".join(str(message) for message in page.context["messages"])

    def test_a_choice_that_is_not_a_number_is_refused_rather_than_crashing(
        self,
    ) -> None:
        """The #35 review found this answering 500 from inside the ORM."""
        response = self.client.post(self.url, {"xodim": "abc"})

        # told() before any other fetch: assertRedirects follows the redirect,
        # and following it is what consumes the message.
        self.assertEqual(response.status_code, 302)
        self.assertIn("Katta Mutaxasis", self.told())
        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)

    def test_a_number_naming_nobody_is_refused(self) -> None:
        response = self.client.post(self.url, {"xodim": "999999"})

        self.application.refresh_from_db()
        self.assertRedirects(response, reverse("qabul-arizalar"))
        self.assertIsNone(self.application.assigned_to)

    def test_an_inactive_specialist_cannot_be_chosen(self) -> None:
        # Not offered by the chooser, and not accepted from a request that
        # did not come from it.
        self.specialist.is_active = False
        self.specialist.save(update_fields=["is_active"])

        self.assign()

        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)

    def test_get_is_refused(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 405)


class AssignedListTests(AssignmentTestCase):
    """What the specialist's Tayinlangan Arizalar page will read."""

    def test_an_assigned_application_is_in_the_specialists_list(self) -> None:
        from applications.views import assigned_applications

        self.assign()

        self.assertIn(self.application, assigned_applications(self.specialist))

    def test_it_is_not_in_somebody_elses_list(self) -> None:
        from applications.views import assigned_applications

        self.assign()

        self.assertNotIn(
            self.application, assigned_applications(self.other_specialist)
        )

    def test_an_unassigned_application_is_in_nobodys_list(self) -> None:
        from applications.views import assigned_applications

        self.assertNotIn(self.application, assigned_applications(self.specialist))


class AttachmentReachabilityTests(AssignmentTestCase):
    """The PAGE_SHOWING_STAGE entry, which is the quiet half of this task."""

    def test_the_specialist_can_open_the_attachment(self) -> None:
        # DEC-015 keeps Katta Mutaxasis off Qabul qilingan, so an assigned
        # application whose stage still pointed there would hand somebody work
        # whose PDF they cannot read.
        application = self.accepted_application(pdf=a_pdf())
        application.assign(by=self.manager, specialist=self.specialist)
        self.client.force_login(self.specialist)

        response = self.client.get(
            reverse("ariza-pdf", args=[application.pk])
        )

        self.assertEqual(response.status_code, 200)

    def test_a_specialist_cannot_open_an_unassigned_application(self) -> None:
        # Still accepted, so it belongs to the Qabul qilingan page, which the
        # specialist may not open.
        application = self.accepted_application(pdf=a_pdf())
        self.client.force_login(self.specialist)

        response = self.client.get(
            reverse("ariza-pdf", args=[application.pk])
        )

        self.assertEqual(response.status_code, 403)


class PermissionTests(AssignmentTestCase):
    """The route answers to the permission of the page offering it."""

    def test_somebody_who_may_not_open_the_page_may_not_assign(self) -> None:
        self.client.force_login(make_user(DIREKTOR))

        response = self.assign()

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.application.assigned_to)

    def test_signing_in_is_required(self) -> None:
        self.client.logout()

        response = self.assign()

        self.application.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.application.assigned_to)
