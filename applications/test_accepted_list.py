"""Tests for the Qabul qilingan Arizalar list of TASK-UZK-025.

Two things carry the weight.

The first is that the page shows accepted applications and nothing else. It
decides that from the stage code, for the reason TASK-UZK-022 gave about the
incoming list: DEC-017 lets an administrator rename or delete any Ariza Status
row, and a list that reads a status name quietly empties the day somebody
does. There is a test that renames the accepted status and then loads the
page.

The second is the date. Qabul qilingan sana is when acceptance happened, not
when the application arrived, and the two are easy to confuse because both are
on the record. There is a test whose application has two different dates.
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
    MENEJER,
    USERS,
    assign_user_type,
)
from applications.models import Application
from reference.models import ArizaStatus, Department, MahsulotTuri


def make_user(type_name: str = ADMIN):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class AcceptedListTestCase(TestCase):
    """Somebody permitted to see accepted applications."""

    def setUp(self) -> None:
        self.decider = make_user(ADMIN)
        self.client.force_login(self.decider)
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )

    def raise_application(self, **overrides) -> Application:
        fields = {
            "department": self.department,
            "mahsulot_turi": self.category,
            "buyurtma_nomi": "Bolt M12",
            "buyurtma_soni": 500,
            "olchov_birligi": "ta",
        }
        fields.update(overrides)
        return Application.raise_application(**fields)

    def accepted_application(self, **overrides) -> Application:
        application = self.raise_application(**overrides)
        application.accept(by=self.decider)
        return application

    def page(self) -> str:
        return self.client.get(reverse("qabul-arizalar")).content.decode()

    def table(self) -> str:
        """The rows, without the page around them.

        The page can name an application outside the table - in a message, for
        instance - so a test about what is listed has to read the list.
        """
        body = self.page().split('<tbody id="qabul-tbody">', 1)[1]

        return body.split("</tbody>", 1)[0]


class ContentTests(AcceptedListTestCase):
    """Only accepted applications, and every column REQ-ARIZA-006 names."""

    def test_an_accepted_application_is_listed(self) -> None:
        application = self.accepted_application()

        self.assertIn(application.ariza_raqami, self.table())

    def test_an_incoming_application_is_not_listed(self) -> None:
        waiting = self.raise_application(buyurtma_nomi="Gayka M10")

        self.assertNotIn(waiting.ariza_raqami, self.table())

    def test_a_rejected_application_is_not_listed(self) -> None:
        refused = self.raise_application(buyurtma_nomi="Kabel 4mm")
        refused.reject(by=self.decider, comment="Byudjet yo`q.")

        self.assertNotIn(refused.ariza_raqami, self.table())

    def test_the_headings_are_the_specified_ones(self) -> None:
        page = self.page()

        for heading in (
            "Ariza",
            "Bo'lim",
            "Mahsulot Turi",
            "Buyurtma nomi",
            "Soni",
            "O'lchov",
            "PDF",
            "Qabul qilingan sana",
            "Tayinlangan xodim",
            "Amallar",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, page)

    def test_a_row_shows_the_application(self) -> None:
        application = self.accepted_application(buyurtma_nomi="Prokat polat")
        row = self.table()

        self.assertIn(application.ariza_raqami, row)
        self.assertIn("Texnik bolim", row)
        self.assertIn("Metallurgiya", row)
        self.assertIn("Prokat polat", row)
        self.assertIn("500", row)
        self.assertIn("ta", row)

    def test_an_empty_list_says_so_rather_than_showing_nothing(self) -> None:
        self.assertIn("Hozircha qabul qilingan ariza", self.table())

    def test_the_list_is_newest_decision_first(self) -> None:
        # The order acceptances were taken in, which is what this page is
        # worked through in - not the order the applications arrived.
        first = self.accepted_application(buyurtma_nomi="Birinchi")
        second = self.accepted_application(buyurtma_nomi="Ikkinchi")
        Application.objects.filter(pk=first.pk).update(
            qabul_qilingan_sana=timezone.now()
        )

        row = self.table()

        self.assertLess(
            row.index(first.ariza_raqami), row.index(second.ariza_raqami)
        )


class AcceptanceDateTests(AcceptedListTestCase):
    """Qabul qilingan sana is when it was accepted, not when it arrived."""

    def test_the_date_shown_is_the_acceptance_date(self) -> None:
        application = self.accepted_application()
        arrived = timezone.now() - timedelta(days=9)
        decided = timezone.now() - timedelta(days=2)
        Application.objects.filter(pk=application.pk).update(
            kelib_tushgan_sana=arrived, qabul_qilingan_sana=decided
        )

        row = self.table()

        self.assertIn(decided.strftime("%Y-%m-%d"), row)
        self.assertNotIn(arrived.strftime("%Y-%m-%d"), row)


class StageNotStatusTests(AcceptedListTestCase):
    """The list reads the stage, which an administrator cannot rename."""

    def test_renaming_the_accepted_status_does_not_empty_the_list(self) -> None:
        application = self.accepted_application()
        accepted = ArizaStatus.objects.get(code=ArizaStatus.Code.ACCEPTED)
        accepted.name = "Bo`lim qabul qildi"
        accepted.save(update_fields=["name"])

        self.assertIn(application.ariza_raqami, self.table())

    def test_deleting_every_status_does_not_empty_the_list(self) -> None:
        application = self.accepted_application()
        ArizaStatus.objects.update(is_active=False)

        self.assertIn(application.ariza_raqami, self.table())


class AssignmentControlsTests(AcceptedListTestCase):
    """The controls REQ-ARIZA-006 names are there, visibly waiting."""

    def test_every_row_offers_the_controls(self) -> None:
        self.accepted_application()
        row = self.table()

        self.assertIn("Tayinlash", row)
        self.assertIn("<select", row)

    def test_they_are_disabled_rather_than_pretending_to_work(self) -> None:
        self.accepted_application()
        row = self.table()

        # Two controls, both disabled, both saying which task wires them.
        self.assertEqual(row.count("disabled"), 2)
        self.assertEqual(row.count("TASK-UZK-027"), 2)

    def test_the_prototypes_creation_form_is_gone(self) -> None:
        # It is the section 4.2 form, which is TASK-UZK-026, and it posted
        # nowhere. An inert creation form on a page that is otherwise real
        # reads as a broken feature rather than as a placeholder.
        page = self.page()

        self.assertNotIn("create-modal", page)
        self.assertNotIn("Ariza Yaratish", page)


class AttachmentTests(AcceptedListTestCase):
    """The pairing PAGE_SHOWING_STAGE promised and nothing could test.

    TASK-UZK-022 made an application's PDF answer to the permission of the
    page the application is currently on, and mapped the accepted stage to
    this page - which did not exist. Now it does, so the promise can be
    checked: somebody who may open this page may fetch the attachment of a row
    on it, and somebody who may not, may not.
    """

    def test_somebody_who_may_open_this_page_may_fetch_the_attachment(self):
        application = self.accepted_application()
        self.client.force_login(make_user(MENEJER))

        response = self.client.get(
            reverse("ariza-pdf", args=[application.pk])
        )

        # 404 because this application has no file, not 403: the permission
        # question was answered yes and the file is what is missing.
        self.assertEqual(response.status_code, 404)

    def test_somebody_who_may_not_open_this_page_may_not(self) -> None:
        # DEC-015 gives Direktor the incoming page and not this one, so an
        # application's attachment stops being reachable by them at the moment
        # it is accepted. That is the whole point of following the record.
        application = self.accepted_application()
        self.client.force_login(make_user(DIREKTOR))

        response = self.client.get(
            reverse("ariza-pdf", args=[application.pk])
        )

        self.assertEqual(response.status_code, 403)


class AccessTests(AcceptedListTestCase):
    """DEC-015 decides who opens this page, as it does for every page."""

    def test_a_permitted_type_opens_it(self) -> None:
        for type_name in (ADMIN, MENEJER, BOLIM_BOSHLIGI):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                response = self.client.get(reverse("qabul-arizalar"))

                self.assertEqual(response.status_code, 200)

    def test_an_excluded_type_is_refused(self) -> None:
        for type_name in (DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                response = self.client.get(reverse("qabul-arizalar"))

                self.assertEqual(response.status_code, 403)

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.client.logout()

        response = self.client.get(reverse("qabul-arizalar"))

        self.assertEqual(response.status_code, 302)
