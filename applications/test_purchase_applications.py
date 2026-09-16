"""Tests for the Xarid Arizasi page of TASK-UZK-030.

Two things carry this task.

DEC-018 fills the department from the requester's own account. The test that
matters is not that it appears - it is that posting a different one does
nothing, because a field that is merely hidden is a field somebody can still
send.

And the audience. USERS may open this page and nothing else, so a requester
who cannot create here cannot do anything at all. The one state that stops
them is having no department, which is real rather than impossible: an account
exists before anybody decides what it is for. They are told what to do about
it rather than shown a crash.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserProfile, UserType
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    assign_user_type,
)
from applications.models import (
    Application,
    PurchaseApplication,
    PurchaseApplicationItem,
    next_ariza_raqami,
)
from applications.test_support import a_pdf
from reference.models import ArizaStatus, Department, MahsulotTuri


def make_user(type_name: str = USERS, department: Department | None = None):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    if department is not None:
        UserProfile.objects.filter(user=user).update(department=department)
    return user


class PurchaseTestCase(TestCase):
    """A requester with a department, and a page that is all they have."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.other_department = Department.objects.create(name="Logistika")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.requester = make_user(USERS, self.department)
        self.client.force_login(self.requester)
        self.url = reverse("xarid-ariza-yaratish")

    def payload(self, lines: int = 1, **overrides) -> dict:
        form = {
            "shartnoma_nomi": "Bolt yetkazib berish shartnomasi",
            "muddat_talabi": "2026-12-31",
            "izoh": "Shoshilinch",
            "form-TOTAL_FORMS": str(lines),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
        }
        for index in range(lines):
            form |= {
                f"form-{index}-mahsulot_turi": self.category.pk,
                f"form-{index}-buyurtma_nomi": f"Bolt M{index + 1}",
                f"form-{index}-buyurtma_soni": "500",
                f"form-{index}-olchov_birligi": "ta",
            }
        form.update(overrides)
        return form

    def create(self, lines: int = 1, pdf=None, **overrides):
        payload = self.payload(lines, **overrides)
        payload["pdf"] = pdf if pdf is not None else a_pdf()

        return self.client.post(self.url, payload)

    def create_without_pdf(self, lines: int = 1, **overrides):
        return self.client.post(self.url, self.payload(lines, **overrides))

    def page(self) -> str:
        return self.client.get(reverse("xarid-ariza")).content.decode()

    def table(self) -> str:
        body = self.page().split('<tbody id="xa-tbody">', 1)[1]

        return body.split("</tbody>", 1)[0]


class CreationTests(PurchaseTestCase):
    """Raising a request."""

    def test_creating_produces_one_application(self) -> None:
        response = self.create()

        self.assertRedirects(response, reverse("xarid-ariza"))
        application = PurchaseApplication.objects.get()
        self.assertEqual(
            application.shartnoma_nomi, "Bolt yetkazib berish shartnomasi"
        )
        self.assertEqual(application.created_by, self.requester)

    def test_the_number_is_year_prefixed(self) -> None:
        self.create()

        self.assertEqual(
            PurchaseApplication.objects.get().xarid_raqami,
            f"XA-{date.today().year}-00001",
        )

    def test_a_second_one_takes_the_next_number(self) -> None:
        self.create()
        self.create()

        self.assertEqual(
            sorted(
                PurchaseApplication.objects.values_list(
                    "xarid_raqami", flat=True
                )
            ),
            [
                f"XA-{date.today().year}-00001",
                f"XA-{date.today().year}-00002",
            ],
        )

    def test_the_sequence_is_independent_of_the_ariza_one(self) -> None:
        # Two sequences sharing a counter would make either one's numbering
        # depend on how busy the other had been.
        self.create()

        self.assertEqual(
            next_ariza_raqami(), f"ARZ-{date.today().year}-00001"
        )
        self.assertFalse(Application.objects.exists())

    def test_the_deadline_is_stored(self) -> None:
        self.create()

        self.assertEqual(
            PurchaseApplication.objects.get().muddat_talabi,
            date(2026, 12, 31),
        )

    def test_several_rows_are_stored_in_order(self) -> None:
        self.create(lines=3)

        self.assertEqual(
            [
                line.buyurtma_nomi
                for line in PurchaseApplication.objects.get().items.all()
            ],
            ["Bolt M1", "Bolt M2", "Bolt M3"],
        )

    def test_the_status_starts_as_the_new_row(self) -> None:
        self.create()

        self.assertEqual(
            PurchaseApplication.objects.get().status.code,
            ArizaStatus.Code.NEW,
        )


class DepartmentTests(PurchaseTestCase):
    """DEC-018 fills it from the account, which is not the same as hiding it."""

    def test_the_department_is_the_requesters_own(self) -> None:
        self.create()

        self.assertEqual(
            PurchaseApplication.objects.get().department, self.department
        )

    def test_posting_a_different_department_changes_nothing(self) -> None:
        # A field that is merely absent from the form is a field somebody can
        # still send. This is the test that says it is filled from rather than
        # filled in.
        self.create(department=self.other_department.pk)

        self.assertEqual(
            PurchaseApplication.objects.get().department, self.department
        )

    def test_a_requester_with_no_department_is_told_what_is_wrong(
        self,
    ) -> None:
        self.client.force_login(make_user(USERS))

        response = self.create()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PurchaseApplication.objects.exists())
        self.assertContains(response, "bo`lim biriktirilmagan")

    def test_the_form_shows_the_department_it_will_use(self) -> None:
        self.assertIn(self.department.name, self.page())


class RefusalTests(PurchaseTestCase):
    """What creation will not do."""

    def test_without_the_pdf_nothing_is_created(self) -> None:
        response = self.create_without_pdf()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PurchaseApplication.objects.exists())
        self.assertFalse(PurchaseApplicationItem.objects.exists())

    def test_without_a_row_nothing_is_created(self) -> None:
        response = self.create(lines=0, **{"form-TOTAL_FORMS": "0"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PurchaseApplication.objects.exists())

    def test_a_broken_row_leaves_nothing_behind(self) -> None:
        response = self.create(lines=2, **{"form-1-buyurtma_soni": ""})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(PurchaseApplication.objects.exists())
        self.assertFalse(PurchaseApplicationItem.objects.exists())

    def test_a_negative_quantity_is_refused(self) -> None:
        self.create(**{"form-0-buyurtma_soni": "-5"})

        self.assertFalse(PurchaseApplication.objects.exists())

    def test_without_a_title_nothing_is_created(self) -> None:
        self.create(shartnoma_nomi="")

        self.assertFalse(PurchaseApplication.objects.exists())

    def test_a_refused_submission_comes_back_with_what_was_typed(self) -> None:
        response = self.create_without_pdf(shartnoma_nomi="Kabel shartnomasi")

        self.assertContains(response, "Kabel shartnomasi")

    def test_get_is_refused(self) -> None:
        self.assertEqual(self.client.get(self.url).status_code, 405)


class ListTests(PurchaseTestCase):
    """Every column REQ-ARIZA-014 names."""

    def test_the_headings_are_the_specified_ones(self) -> None:
        page = self.page()

        for heading in (
            "Ariza",
            "Shartnoma nomi",
            "Bo'lim",
            "Buyurtma nomi",
            "Soni",
            "O'lchov",
            "Holati",
            "Mahsulot Turi",
            "Izoh",
            "PDF",
            "Yaratilgan",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, page)

    def test_a_row_shows_the_application(self) -> None:
        self.create()
        row = self.table()

        self.assertIn(PurchaseApplication.objects.get().xarid_raqami, row)
        self.assertIn("Bolt yetkazib berish shartnomasi", row)
        self.assertIn("Texnik bolim", row)
        self.assertIn("Bolt M1", row)
        self.assertIn("500", row)
        self.assertIn("Metallurgiya", row)
        self.assertIn("Shoshilinch", row)

    def test_the_list_shows_the_current_status(self) -> None:
        self.create()

        self.assertIn(
            PurchaseApplication.objects.get().status.name, self.table()
        )

    def test_a_multi_line_application_renders_a_row_per_line(self) -> None:
        self.create(lines=3)
        row = self.table()

        for nomi in ("Bolt M1", "Bolt M2", "Bolt M3"):
            with self.subTest(line=nomi):
                self.assertIn(nomi, row)

    def test_the_pdf_is_linked_and_reachable(self) -> None:
        self.create()
        application = PurchaseApplication.objects.get()

        self.assertIn(
            reverse("xarid-ariza-pdf", args=[application.pk]), self.table()
        )
        self.assertEqual(
            self.client.get(
                reverse("xarid-ariza-pdf", args=[application.pk])
            ).status_code,
            200,
        )

    def test_an_empty_list_says_so_rather_than_showing_nothing(self) -> None:
        self.assertIn("Hozircha xarid arizasi", self.table())

    def test_the_page_does_not_cost_a_query_per_row(self) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.create()
        with CaptureQueriesContext(connection) as first:
            self.client.get(reverse("xarid-ariza"))

        for index in range(4):
            self.create(shartnoma_nomi=f"Shartnoma {index}")
        with CaptureQueriesContext(connection) as later:
            self.client.get(reverse("xarid-ariza"))

        self.assertEqual(
            len(later.captured_queries), len(first.captured_queries)
        )


class PermissionTests(PurchaseTestCase):
    """Who may open the only page a requester has."""

    def test_every_type_may_open_it(self) -> None:
        # Unusually, DEC-015 excludes nobody from this page - it is the one
        # page every type has, and the only page USERS has at all. Asserted
        # rather than assumed, because "nobody is excluded" reads like a
        # missing test otherwise.
        for type_name in (
            ADMIN,
            BOLIM_BOSHLIGI,
            MENEJER,
            KATTA_MUTAXASIS,
            DIREKTOR,
            USERS,
        ):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name, self.department))
                self.assertEqual(
                    self.client.get(reverse("xarid-ariza")).status_code, 200
                )

    def test_signing_in_is_required(self) -> None:
        self.client.logout()

        response = self.client.get(reverse("xarid-ariza"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
