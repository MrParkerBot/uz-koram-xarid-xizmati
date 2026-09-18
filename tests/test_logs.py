"""Tests for the Logs page (TASK-UZK-053, REQ-LOG-001, DEC-029).

The page reads the audit table TASK-UZK-052 writes. It shows the nine columns
section 10 names, filters by each of them, and leaves the four approval cells
empty for an entry nobody has decided.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from tests.support import SignedInAdminTestCase, a_department, a_supplier, make_user, page
from xarid.audit import record_created, record_decision, record_deleted
from xarid.models import (
    ADMIN,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    AuditEntry,
    Supplier,
)

# What the page says when the filter matches nothing.
EMPTY_LOG = "Log yozuvlari topilmadi."


class LogsPageTests(SignedInAdminTestCase):
    """What the page shows and how its bar narrows it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.sales = a_department("Savdo bo`limi")
        cls.technical = a_department("Texnik bo`lim")
        cls.clerk = make_user(
            "log.clerk",
            user_type=MENEJER,
            department=cls.sales,
            first_name="Bobur",
            last_name="Toshmatov",
        )
        cls.engineer = make_user(
            "log.engineer", user_type=KATTA_MUTAXASIS, department=cls.technical
        )

    def an_entry(self, actor=None, name="Texnoprom LLC", inn="123456789") -> AuditEntry:
        supplier, _ = Supplier.objects.get_or_create(name=name, defaults={"inn": inn})
        return record_created(actor or self.clerk, supplier)

    def rows_of(self, response) -> str:
        """The table body, so an assertion cannot match the filter bar."""
        rendered = response.content.decode()
        return rendered.split('id="logs-tbody"', 1)[1].split("</tbody>", 1)[0]

    def test_the_page_shows_every_column_the_assignment_names(self) -> None:
        self.an_entry()

        response = self.client.get(page("logs"))

        self.assertEqual(response.status_code, 200)
        for heading in (
            "Foydalanuvchi",
            "Foydalanuvchi Bo'limi",
            "Forma Nomi",
            "Sana/Soat",
            "Amal",
            "Tasdiqlovchi",
            "Tasdiqlovchi Bo'lim",
            "Tasdiq comment",
            "Tasdiq Sanasi/Vaqti",
        ):
            with self.subTest(column=heading):
                self.assertContains(response, heading)

    def test_an_entry_prints_who_did_what_and_when(self) -> None:
        self.an_entry()

        rows = self.rows_of(self.client.get(page("logs")))

        self.assertIn("Bobur Toshmatov", rows)
        self.assertIn("Savdo bo`limi", rows)
        self.assertIn("Firma", rows)
        self.assertIn("Texnoprom LLC", rows)
        self.assertIn("Created", rows)

    def approval_cells_of(self, rows: str) -> list[str]:
        """The four approval cells of the first row, with their tags stripped.

        Read by position rather than by counting empty cells: the last of the
        four carries a class, and an actor with no department leaves an empty
        cell of its own, so counting would check neither the right cells nor
        all of them.
        """
        import re

        cells = re.findall(r"<td[^>]*>(.*?)</td>", rows, flags=re.S)

        return [re.sub(r"<[^>]+>", "", cell).strip() for cell in cells[-4:]]

    def test_an_undecided_entry_leaves_all_four_approval_cells_empty(self) -> None:
        self.an_entry()

        rows = self.rows_of(self.client.get(page("logs")))

        self.assertEqual(self.approval_cells_of(rows), ["", "", "", ""])

    def test_a_decided_entry_prints_all_four_approval_cells(self) -> None:
        supplier = a_supplier()
        record_created(self.clerk, supplier)
        approver = make_user(
            "log.approver",
            user_type=DIREKTOR,
            department=self.technical,
            first_name="Dilnoza",
            last_name="Yusupova",
        )
        record_decision(approver, supplier, approved=True, comment="Hujjatlar to'liq")

        rows = self.rows_of(self.client.get(page("logs")))
        approver, department, comment, decided_at = self.approval_cells_of(rows)

        self.assertEqual(approver, "Dilnoza Yusupova")
        self.assertEqual(department, "Texnik bo`lim")
        self.assertEqual(comment, "Hujjatlar to&#39;liq")
        self.assertTrue(decided_at)

    def test_filtering_by_user_narrows_the_rows_to_that_user(self) -> None:
        self.an_entry(actor=self.clerk, name="Texnoprom LLC", inn="123456789")
        self.an_entry(actor=self.engineer, name="MetalGrup JV", inn="223456789")

        rows = self.rows_of(
            self.client.get(page("logs"), {"foydalanuvchi": self.clerk.pk})
        )

        self.assertIn("Texnoprom LLC", rows)
        self.assertNotIn("MetalGrup JV", rows)

    def test_filtering_by_department_narrows_the_rows(self) -> None:
        self.an_entry(actor=self.clerk, name="Texnoprom LLC", inn="123456789")
        self.an_entry(actor=self.engineer, name="MetalGrup JV", inn="223456789")

        rows = self.rows_of(self.client.get(page("logs"), {"bolim": self.sales.pk}))

        self.assertIn("Texnoprom LLC", rows)
        self.assertNotIn("MetalGrup JV", rows)

    def test_filtering_by_action_narrows_the_rows(self) -> None:
        kept = a_supplier(name="Texnoprom LLC", inn="123456789")
        record_created(self.clerk, kept)
        gone = a_supplier(name="MetalGrup JV", inn="223456789")
        record_deleted(self.clerk, gone)

        response = self.client.get(page("logs"), {"amal": AuditEntry.Action.DELETED})
        rows = self.rows_of(response)

        self.assertIn("MetalGrup JV", rows)
        self.assertNotIn("Texnoprom LLC", rows)

    def test_the_action_drop_down_and_the_column_agree_on_a_name(self) -> None:
        """A bar that says "created" over a column that says "Created" is two names."""
        self.an_entry()

        rendered = self.client.get(page("logs")).content.decode()
        options = rendered.split('name="amal"', 1)[1].split("</select>", 1)[0]

        self.assertIn(">Created<", options)
        self.assertNotIn(">created<", options)

    def test_filtering_by_form_narrows_the_rows(self) -> None:
        self.an_entry()
        record_created(self.clerk, self.engineer)

        rows = self.rows_of(self.client.get(page("logs"), {"forma": "Firma"}))

        self.assertIn("Texnoprom LLC", rows)
        self.assertNotIn("Foydalanuvchi", rows)

    def test_the_period_narrows_by_when_it_happened(self) -> None:
        entry = self.an_entry()
        AuditEntry.objects.filter(pk=entry.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )
        today = timezone.localdate()

        rows = self.rows_of(self.client.get(page("logs"), {"dan": today.isoformat()}))

        self.assertIn(EMPTY_LOG, rows)

    def test_a_refused_period_is_reported_and_not_applied(self) -> None:
        self.an_entry()
        today = timezone.localdate()

        response = self.client.get(
            page("logs"),
            {"dan": today.isoformat(), "gacha": (today - timedelta(days=1)).isoformat()},
            follow=True,
        )

        self.assertContains(response, "Davr boshlanishi tugashidan keyin")
        self.assertIn("Texnoprom LLC", self.rows_of(response))

    def test_an_empty_log_renders_its_own_message(self) -> None:
        response = self.client.get(page("logs"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, EMPTY_LOG)

    def test_the_page_offers_no_export(self) -> None:
        """DEC-029: section 10 is the one page that does not ask for one.

        The page's own body, not the shell around it: a word appearing in
        base.html later must not fail a Logs test.
        """
        self.an_entry()

        rendered = self.client.get(page("logs")).content.decode()
        body = rendered.split('<div class="page-wrap">', 1)[1]

        self.assertNotIn("Export", body)
        self.assertNotIn("eksport", body)
        self.assertNotIn("Excel", body)


class LogsPermissionTests(TestCase):
    """Who may open it."""

    def test_the_types_dec_015_permits_may_open_it(self) -> None:
        for user_type in (ADMIN, MENEJER, DIREKTOR):
            with self.subTest(user_type=user_type):
                self.client.force_login(make_user(f"logs.{user_type}", user_type=user_type))

                self.assertEqual(self.client.get(page("logs")).status_code, 200)

    def test_a_type_it_does_not_permit_is_refused(self) -> None:
        self.client.force_login(make_user("logs.outsider", user_type=KATTA_MUTAXASIS))

        self.assertEqual(self.client.get(page("logs")).status_code, 403)
