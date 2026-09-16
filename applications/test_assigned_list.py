"""Tests for the Tayinlangan Arizalar list of TASK-UZK-028.

One thing on this page has a security shape and the rest is columns: a
specialist must see the work assigned to them and must not see anybody else's.
It is tested from both sides rather than only from the owner's, because a list
that shows too much passes every test written from the point of view of the
person it belongs to.

The other half is a decision the acceptance criteria do not make. Four user
types may open this page and only one of them is the specialist. The people
who hand work out see all of it, because where the work went is the question
this page answers for them - recorded in the plan, and pinned here so that
overturning it is deliberate.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
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
)
from applications.models import Application
from applications.test_support import a_pdf
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


class AssignedListTestCase(TestCase):
    """Two specialists, a manager, and work to go round."""

    def setUp(self) -> None:
        self.manager = make_user(ADMIN)
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.specialist = make_user(KATTA_MUTAXASIS, first_name="Alisher")
        self.other_specialist = make_user(KATTA_MUTAXASIS, first_name="Dilnoza")

    def raise_application(self, lines: int = 1, **overrides) -> Application:
        items = [
            {
                "mahsulot_turi": self.category,
                "buyurtma_nomi": f"Bolt M{index + 1}",
                "buyurtma_soni": 500,
                "olchov_birligi": "ta",
            }
            for index in range(lines)
        ]
        fields = {"department": self.department, "izoh": "Zanglamaydigan"}
        fields.update(overrides)
        return Application.raise_application(items=items, **fields)

    def assigned_application(self, to=None, lines: int = 1, **overrides):
        application = self.raise_application(lines=lines, **overrides)
        application.accept(by=self.manager)
        application.assign(by=self.manager, specialist=to or self.specialist)
        return application

    def page(self) -> str:
        return self.client.get(reverse("tayinlangan")).content.decode()

    def table(self) -> str:
        body = self.page().split('<tbody id="tayinlangan-tbody">', 1)[1]

        return body.split("</tbody>", 1)[0]


class WhoSeesWhatTests(AssignedListTestCase):
    """The one rule on this page with a security shape."""

    def test_a_specialist_sees_their_own_work(self) -> None:
        mine = self.assigned_application(to=self.specialist)
        self.client.force_login(self.specialist)

        self.assertIn(mine.ariza_raqami, self.table())

    def test_a_specialist_does_not_see_somebody_elses(self) -> None:
        theirs = self.assigned_application(to=self.other_specialist)
        self.client.force_login(self.specialist)

        self.assertNotIn(theirs.ariza_raqami, self.table())

    def test_a_manager_sees_both(self) -> None:
        mine = self.assigned_application(to=self.specialist)
        theirs = self.assigned_application(to=self.other_specialist)
        self.client.force_login(self.manager)

        table = self.table()
        self.assertIn(mine.ariza_raqami, table)
        self.assertIn(theirs.ariza_raqami, table)

    def test_an_unassigned_application_is_on_nobodys_list(self) -> None:
        waiting = self.raise_application()
        waiting.accept(by=self.manager)

        for viewer in (self.specialist, self.manager):
            with self.subTest(viewer=viewer.first_name):
                self.client.force_login(viewer)
                self.assertNotIn(waiting.ariza_raqami, self.table())

    def test_an_incoming_application_is_on_nobodys_list(self) -> None:
        self.client.force_login(self.manager)

        self.assertNotIn(self.raise_application().ariza_raqami, self.table())


class HolderColumnTests(AssignedListTestCase):
    """The column a specialist does not need and a manager does."""

    def test_a_manager_sees_who_holds_each_application(self) -> None:
        self.assigned_application(to=self.other_specialist)
        self.client.force_login(self.manager)

        page = self.page()
        self.assertIn("Tayinlangan xodim", page)
        self.assertIn("Dilnoza", page)

    def test_a_specialist_does_not_get_a_column_of_their_own_name(
        self,
    ) -> None:
        self.assigned_application(to=self.specialist)
        self.client.force_login(self.specialist)

        self.assertNotIn("Tayinlangan xodim", self.page())


class ColumnTests(AssignedListTestCase):
    """Every column REQ-ARIZA-012 names."""

    def test_the_headings_are_the_specified_ones(self) -> None:
        self.client.force_login(self.manager)
        page = self.page()

        for heading in (
            "Ariza",
            "Bo'lim",
            "Mahsulot Turi",
            "Buyurtma nomi",
            "Soni",
            "O'lchov",
            "Izoh",
            "PDF",
            "Qabul qilingan sana",
            "Qabul",
            "Holat",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, page)

    def test_a_row_shows_the_application(self) -> None:
        application = self.assigned_application(izoh="Zanglamaydigan")
        self.client.force_login(self.specialist)

        row = self.table()
        self.assertIn(application.ariza_raqami, row)
        self.assertIn("Texnik bolim", row)
        self.assertIn("Metallurgiya", row)
        self.assertIn("Bolt M1", row)
        self.assertIn("500", row)
        self.assertIn("ta", row)
        self.assertIn("Zanglamaydigan", row)

    def test_the_comment_shown_is_the_applications_own(self) -> None:
        # REQ-ARIZA-012 says Izoh is the application's comment, and the
        # record has more than one thing that could be called that.
        self.assigned_application(izoh="Shoshilinch")
        self.client.force_login(self.specialist)

        self.assertIn("Shoshilinch", self.table())

    def test_a_multi_line_application_renders_a_row_per_line(self) -> None:
        self.assigned_application(lines=3)
        self.client.force_login(self.specialist)

        row = self.table()
        for nomi in ("Bolt M1", "Bolt M2", "Bolt M3"):
            with self.subTest(line=nomi):
                self.assertIn(nomi, row)
        self.assertEqual(row.count('rowspan="3"'), 8)

    def test_an_empty_list_says_so_rather_than_showing_nothing(self) -> None:
        self.client.force_login(self.specialist)

        self.assertIn("Hozircha tayinlangan ariza", self.table())


class WaitingControlTests(AssignedListTestCase):
    """Accept and Holat belong to TASK-UZK-029."""

    def test_they_are_disabled_and_name_the_task_that_wires_them(self) -> None:
        # Counted per row rather than as a fixed number. The #29 review made
        # this point about the same assertion on the Qabul qilingan page: an
        # exact count over the whole table body passes only while the case has
        # one application in it, and then fails for the wrong reason. The #38
        # review found it repeated here.
        rows = 3
        for index in range(rows):
            self.assigned_application(izoh=f"Ariza {index}")
        self.client.force_login(self.specialist)

        row = self.table()
        self.assertEqual(row.count("TASK-UZK-029"), 2 * rows)
        self.assertEqual(row.count("disabled"), 2 * rows)


class QueryTests(AssignedListTestCase):
    """What the page costs, which the #38 review found unmeasured."""

    def cost_of_the_page(self, viewer) -> int:
        """How many queries rendering the page takes, as it stands."""
        self.client.force_login(viewer)
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse("tayinlangan"))

        return len(captured.captured_queries)

    def test_the_page_does_not_cost_a_query_per_row(self) -> None:
        # Counted rather than named. Asserting that no query mentions
        # reference_arizastatus does not work once the column is joined -
        # the join puts the table in the list query too - and asserting an
        # exact total pins the number of unrelated queries the session and
        # the permission check happen to make today. What the fix actually
        # claims is that the cost does not grow with the rows, so that is
        # what is measured.
        for viewer, label in (
            (self.specialist, "specialist"),
            (self.manager, "manager"),
        ):
            with self.subTest(viewer=label):
                self.assigned_application(to=viewer if label == "specialist" else None)
                with_one_row = self.cost_of_the_page(viewer)

                for index in range(4):
                    self.assigned_application(
                        to=viewer if label == "specialist" else None,
                        izoh=f"Ariza {index}",
                    )

                self.assertEqual(self.cost_of_the_page(viewer), with_one_row)


class AttachmentTests(AssignedListTestCase):
    """The page is where a specialist reaches their own application's PDF."""

    def test_the_pdf_is_linked_and_reachable(self) -> None:
        application = self.assigned_application(pdf=a_pdf())
        self.client.force_login(self.specialist)

        self.assertIn(
            reverse("ariza-pdf", args=[application.pk]), self.table()
        )
        self.assertEqual(
            self.client.get(
                reverse("ariza-pdf", args=[application.pk])
            ).status_code,
            200,
        )

    def test_a_row_without_one_says_so(self) -> None:
        self.assigned_application()
        self.client.force_login(self.specialist)

        self.assertNotIn("pdf-badge", self.table())


class PermissionTests(AssignedListTestCase):
    """DEC-015 decides who may open this page at all."""

    def test_the_permitted_types_may_open_it(self) -> None:
        for type_name in (ADMIN, BOLIM_BOSHLIGI, MENEJER, KATTA_MUTAXASIS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))
                self.assertEqual(
                    self.client.get(reverse("tayinlangan")).status_code, 200
                )

    def test_the_others_may_not(self) -> None:
        for type_name in (DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))
                self.assertEqual(
                    self.client.get(reverse("tayinlangan")).status_code, 403
                )

    def test_signing_in_is_required(self) -> None:
        response = self.client.get(reverse("tayinlangan"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
