"""Tests for the Kelib tushgan Arizalar list of TASK-UZK-022.

REQ-ARIZA-003 names eleven columns, and the list showing all of them is most
of what this page is. The rest is the stage: the page must show applications
that are still incoming and nothing else, and it must decide that from a code
rather than from an Ariza Status name, because DEC-017 lets an administrator
rename or delete any status row. A list that quietly empties when somebody
renames a status is the failure this design exists to prevent, so there is a
test that renames one.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import ADMIN, MENEJER, USERS, assign_user_type
from applications.models import Application, next_ariza_raqami
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


class ApplicationTestCase(TestCase):
    """Somebody permitted to see incoming applications."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.client.force_login(make_user(ADMIN))

    def raise_application(self, **overrides) -> Application:
        """One application with one order line, both taking overrides.

        The order-line fields moved onto ApplicationItem in TASK-UZK-026 and
        the callers of this helper did not: it still takes buyurtma_nomi and
        the rest as keywords and sends each to whichever record now holds it.
        """
        line = {
            "mahsulot_turi": self.category,
            "buyurtma_nomi": "Bolt M12",
            "buyurtma_soni": 500,
            "olchov_birligi": "ta",
        }
        fields = {
            "department": self.department,
            "izoh": "Zanglamaydigan",
        }
        for name, value in overrides.items():
            if name in line:
                line[name] = value
            else:
                fields[name] = value

        return Application.raise_application(items=[line], **fields)

    def page(self) -> str:
        return self.client.get(reverse("kelib-arizalar")).content.decode()


class ColumnTests(ApplicationTestCase):
    """REQ-ARIZA-003 names eleven columns and the table shows them."""

    def test_the_headings_are_the_specified_ones(self) -> None:
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
            "Kelib tushgan",
            "Amallar",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, page)

    def test_a_row_shows_the_application(self) -> None:
        application = self.raise_application()
        page = self.page()

        self.assertIn(application.ariza_raqami, page)
        self.assertIn("Texnik bolim", page)
        self.assertIn("Metallurgiya", page)
        self.assertIn("Bolt M12", page)
        self.assertIn("ta", page)
        self.assertIn("Zanglamaydigan", page)

    def test_the_category_shows_its_number_and_name(self) -> None:
        # REQ-ARIZA-003 asks for "category number - category name", which is
        # how the department refers to a category.
        self.raise_application()

        self.assertIn("100042", self.page())

    def test_a_fractional_quantity_keeps_its_value(self) -> None:
        # REQ-ARIZA-003 allows int or float, and 2.5 kg is not 3 kg.
        # Rendered "2,5" because LANGUAGE_CODE is uz and the decimal
        # separator is a comma - not "2,500", which is what three stored
        # decimal places print as and reads as two and a half thousand.
        self.raise_application(buyurtma_soni="2.5", olchov_birligi="kg")

        page = self.page()

        self.assertIn("2,5", page)
        self.assertNotIn("2,500", page)

    def test_a_whole_quantity_has_no_decimal_part(self) -> None:
        self.raise_application(buyurtma_soni=500)

        page = self.page()

        self.assertIn("500", page)
        self.assertNotIn("500,000", page)

    def test_an_empty_comment_renders_as_a_dash(self) -> None:
        self.raise_application(izoh="")

        self.assertIn("&mdash;", self.page())


class EmptyListTests(ApplicationTestCase):
    """An empty list renders without error - the criterion says so."""

    def test_the_empty_page_renders_and_says_so(self) -> None:
        self.assertIn("Hozircha kelib tushgan ariza yo", self.page())

    def test_the_empty_page_is_not_an_error(self) -> None:
        self.assertEqual(
            self.client.get(reverse("kelib-arizalar")).status_code, 200
        )


class StageTests(ApplicationTestCase):
    """Only incoming applications, decided by a code rather than a name."""

    def test_only_incoming_applications_are_listed(self) -> None:
        incoming = self.raise_application()
        accepted = self.raise_application(buyurtma_nomi="Gayka M10")
        accepted.stage = Application.Stage.ACCEPTED
        accepted.save(update_fields=["stage"])

        page = self.page()

        self.assertIn(incoming.ariza_raqami, page)
        self.assertNotIn(accepted.ariza_raqami, page)

    def test_a_rejected_application_leaves_the_list(self) -> None:
        rejected = self.raise_application()
        rejected.stage = Application.Stage.REJECTED
        rejected.save(update_fields=["stage"])

        self.assertNotIn(rejected.ariza_raqami, self.page())

    def test_renaming_every_status_does_not_empty_the_list(self) -> None:
        # The reason the stage is a code and not one of DEC-017's editable
        # rows. An administrator renaming statuses is doing something the
        # specification invites; this list must not notice.
        application = self.raise_application()
        for status in ArizaStatus.objects.all():
            status.name = f"Boshqa nom {status.pk}"
            status.save(update_fields=["name"])

        self.assertIn(application.ariza_raqami, self.page())

    def test_deleting_every_status_does_not_empty_the_list(self) -> None:
        application = self.raise_application()
        ArizaStatus.objects.update(is_active=False)

        self.assertIn(application.ariza_raqami, self.page())

    def test_a_new_application_starts_incoming(self) -> None:
        self.assertEqual(
            self.raise_application().stage, Application.Stage.INCOMING
        )


class NumberingTests(ApplicationTestCase):
    """DEC-022: ARZ-2026-00001, five digits, resetting each year."""

    def test_the_first_number_of_the_year_has_the_decided_format(self) -> None:
        self.assertEqual(
            next_ariza_raqami(date(2026, 3, 1)), "ARZ-2026-00001"
        )

    def test_the_sequence_increases(self) -> None:
        first = self.raise_application()
        second = self.raise_application(buyurtma_nomi="Gayka M10")

        self.assertLess(first.ariza_raqami, second.ariza_raqami)

    def test_the_sequence_restarts_in_a_new_year(self) -> None:
        Application.objects.create(
            ariza_raqami="ARZ-2025-00007",
            department=self.department,
        )

        self.assertEqual(
            next_ariza_raqami(date(2026, 1, 4)), "ARZ-2026-00001"
        )

    def test_the_sequence_continues_within_a_year(self) -> None:
        Application.objects.create(
            ariza_raqami="ARZ-2026-00007",
            department=self.department,
        )

        self.assertEqual(
            next_ariza_raqami(date(2026, 6, 1)), "ARZ-2026-00008"
        )

    def test_two_applications_cannot_share_a_number(self) -> None:
        from django.db import IntegrityError

        first = self.raise_application()

        with self.assertRaises(IntegrityError):
            Application.objects.create(
                ariza_raqami=first.ariza_raqami,
                department=self.department,
            )


class ReferenceProtectionTests(ApplicationTestCase):
    """A category or department an application points at cannot vanish."""

    def test_a_referenced_category_cannot_be_removed_from_the_database(self):
        from django.db.models import ProtectedError

        self.raise_application()

        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_a_referenced_department_survives_being_deleted_on_its_page(self):
        # DEC-009 deletion is deactivation, so the page never calls delete().
        # The application keeps resolving to the department it came from.
        application = self.raise_application()
        self.department.is_active = False
        self.department.save(update_fields=["is_active"])
        application.refresh_from_db()

        self.assertEqual(application.department, self.department)


class PermissionTests(ApplicationTestCase):
    """DEC-015 decides who may open this page, and the PDF answers to it."""

    def test_a_manager_may_open_the_page(self) -> None:
        self.client.force_login(make_user(MENEJER))

        self.assertEqual(
            self.client.get(reverse("kelib-arizalar")).status_code, 200
        )

    def test_a_users_role_may_not_open_the_page(self) -> None:
        # DEC-015 gives Users the Xarid Arizasi page and nothing else.
        self.client.force_login(make_user(USERS))

        self.assertEqual(
            self.client.get(reverse("kelib-arizalar")).status_code, 403
        )

    def test_an_anonymous_visitor_is_redirected(self) -> None:
        self.client.logout()

        self.assertEqual(
            self.client.get(reverse("kelib-arizalar")).status_code, 302
        )
