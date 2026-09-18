"""Tests for the Hisobotlar reports (TASK-UZK-044).

Xodimlar yuklamasi counts what each specialist is carrying, one column per
active contract status (REQ-YUKLAMA-002, DEC-010).
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    an_assigned_application,
    assigned_on,
    make_user,
    page,
)
from xarid.filters import DateColumn, DatePeriod
from xarid.models import ADMIN, KATTA_MUTAXASIS, MENEJER, Application, ShartnomaStatus
from xarid.reports import staff_workload, status_columns

ASSIGNMENT_PERIOD = DateColumn("Tayinlangan sana", "tayinlangan_sana")

REFUSED_INVERTED_PERIOD = "Davr boshlanishi tugashidan keyin"


def period(**chosen: str) -> DatePeriod:
    """The period a request with these bounds would produce."""
    return DatePeriod(ASSIGNMENT_PERIOD, chosen)


class StaffWorkloadTests(TestCase):
    """The counting itself, without a page around it."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("head", user_type=ADMIN)
        cls.busy = make_user("busy.specialist", user_type=KATTA_MUTAXASIS, first_name="Alisher")
        cls.idle = make_user("idle.specialist", user_type=KATTA_MUTAXASIS, first_name="Bobur")
        cls.statuses = tuple(ShartnomaStatus.objects.active())

    def row_for(self, specialist_name: str, report) -> object:
        for row in report.rows:
            if row.subject_label == specialist_name:
                return row
        self.fail(f"{specialist_name} is not in the report")

    def test_every_assignable_specialist_appears_once(self) -> None:
        an_assigned_application(self.head, self.busy)

        report = staff_workload(None)

        labels = [row.subject_label for row in report.rows]
        self.assertEqual(sorted(labels), sorted(set(labels)))
        self.assertIn("Alisher", labels)
        self.assertIn("Bobur", labels)

    def test_a_specialist_with_no_work_shows_zeros(self) -> None:
        an_assigned_application(self.head, self.busy)

        report = staff_workload(None)

        idle = self.row_for("Bobur", report)
        self.assertEqual(idle.total, 0)
        self.assertEqual(set(idle.counters), {0})

    def test_a_counter_is_the_applications_with_a_contract_in_that_status(self) -> None:
        first, second = self.statuses[0], self.statuses[1]
        a_contract(an_assigned_application(self.head, self.busy), self.head, status=first)
        a_contract(an_assigned_application(self.head, self.busy), self.head, status=first)
        a_contract(an_assigned_application(self.head, self.busy), self.head, status=second)

        report = staff_workload(None)

        busy = self.row_for("Alisher", report)
        self.assertEqual(busy.total, 3)
        self.assertEqual(busy.counters[0], 2)
        self.assertEqual(busy.counters[1], 1)

    def test_an_application_with_two_contracts_counts_under_both_statuses(self) -> None:
        first, second = self.statuses[0], self.statuses[1]
        application = an_assigned_application(self.head, self.busy)
        a_contract(application, self.head, status=first)
        a_contract(application, self.head, status=second)

        report = staff_workload(None)

        busy = self.row_for("Alisher", report)
        self.assertEqual(busy.total, 1)
        self.assertEqual(busy.counters[0], 1)
        self.assertEqual(busy.counters[1], 1)

    def test_an_application_without_a_contract_counts_only_in_the_total(self) -> None:
        an_assigned_application(self.head, self.busy)

        report = staff_workload(None)

        busy = self.row_for("Alisher", report)
        self.assertEqual(busy.total, 1)
        self.assertEqual(set(busy.counters), {0})

    def test_the_totals_row_is_the_sum_of_each_column(self) -> None:
        first = self.statuses[0]
        a_contract(an_assigned_application(self.head, self.busy), self.head, status=first)
        a_contract(an_assigned_application(self.head, self.idle), self.head, status=first)

        report = staff_workload(None)

        self.assertEqual(report.totals.total, sum(row.total for row in report.rows))
        for index in range(len(report.columns)):
            with self.subTest(column=report.columns[index].label):
                self.assertEqual(
                    report.totals.counters[index],
                    sum(row.counters[index] for row in report.rows),
                )
        self.assertEqual(report.totals.counters[0], 2)

    def test_a_new_status_adds_a_column_with_no_code_change(self) -> None:
        before = len(status_columns())

        ShartnomaStatus.objects.create(name="Tekshiruvda", badge_colour="blue")

        after = status_columns()
        self.assertEqual(len(after), before + 1)
        self.assertIn("Tekshiruvda", [column.label for column in after])

    def test_a_deactivated_status_stops_being_a_column(self) -> None:
        retired = self.statuses[0]
        retired.is_active = False
        retired.save(update_fields=["is_active"])

        labels = [column.label for column in status_columns()]

        self.assertNotIn(retired.name, labels)

    def test_the_columns_follow_the_configured_order(self) -> None:
        expected = [status.name for status in ShartnomaStatus.objects.active()]

        self.assertEqual([column.label for column in status_columns()], expected)

    def test_a_period_counts_only_the_assignments_inside_it(self) -> None:
        first = self.statuses[0]
        a_contract(
            assigned_on(date(2026, 2, 10), self.head, self.busy), self.head, status=first
        )
        a_contract(
            assigned_on(date(2026, 4, 10), self.head, self.busy), self.head, status=first
        )

        report = staff_workload(period(dan="2026-02-01", gacha="2026-02-28"))

        busy = self.row_for("Alisher", report)
        self.assertEqual(busy.total, 1)
        self.assertEqual(busy.counters[0], 1)

    def test_a_refused_period_counts_everything(self) -> None:
        assigned_on(date(2026, 2, 10), self.head, self.busy)
        assigned_on(date(2026, 4, 10), self.head, self.busy)

        report = staff_workload(period(dan="2026-04-01", gacha="2026-01-01"))

        self.assertEqual(self.row_for("Alisher", report).total, 2)

    def test_work_that_has_left_the_assigned_stage_is_still_counted(self) -> None:
        application = an_assigned_application(self.head, self.busy)
        Application.objects.filter(pk=application.pk).update(stage=Application.Stage.REJECTED)

        report = staff_workload(None)

        self.assertEqual(self.row_for("Alisher", report).total, 1)

    def test_the_query_count_does_not_grow_with_the_statuses(self) -> None:
        an_assigned_application(self.head, self.busy)

        with self.assertNumQueries(2):
            staff_workload(None)

        ShartnomaStatus.objects.create(name="Tekshiruvda", badge_colour="blue")
        ShartnomaStatus.objects.create(name="Kutilmoqda", badge_colour="grey")

        with self.assertNumQueries(2):
            staff_workload(None)


class StaffWorkloadPageTests(SignedInAdminTestCase):
    """The report as the page renders it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user(
            "page.specialist",
            user_type=KATTA_MUTAXASIS,
            first_name="Dilnoza",
            last_name="Yusupova",
        )

    def test_the_page_answers_with_no_data_at_all(self) -> None:
        response = self.client.get(page("xodimlar-yuklamasi"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Xodimlar Yuklamasi")

    def test_the_page_prints_a_row_per_specialist_and_the_totals(self) -> None:
        status = ShartnomaStatus.objects.active().first()
        a_contract(an_assigned_application(self.admin, self.specialist), self.admin, status=status)

        response = self.client.get(page("xodimlar-yuklamasi"))

        self.assertContains(response, "Dilnoza Yusupova")
        self.assertContains(response, status.name)
        self.assertContains(response, "Jami:")

    def test_the_page_prints_a_column_per_active_status(self) -> None:
        response = self.client.get(page("xodimlar-yuklamasi"))

        for status in ShartnomaStatus.objects.active():
            with self.subTest(status=status.name):
                self.assertContains(response, status.name)

    def test_the_page_narrows_to_the_chosen_period(self) -> None:
        assigned_on(date(2026, 2, 10), self.admin, self.specialist)
        assigned_on(date(2026, 5, 10), self.admin, self.specialist)

        response = self.client.get(
            page("xodimlar-yuklamasi"), {"dan": "2026-02-01", "gacha": "2026-02-28"}
        )

        self.assertContains(response, 'data-jami="1"')

    def test_the_page_refuses_an_inverted_period_with_a_message(self) -> None:
        assigned_on(date(2026, 2, 10), self.admin, self.specialist)

        response = self.client.get(
            page("xodimlar-yuklamasi"), {"dan": "2026-04-01", "gacha": "2026-01-01"}
        )

        self.assertContains(response, REFUSED_INVERTED_PERIOD)
        self.assertContains(response, 'data-jami="1"')

    def test_the_page_renders_the_period_controls(self) -> None:
        response = self.client.get(page("xodimlar-yuklamasi"))

        self.assertContains(response, 'name="dan"')
        self.assertContains(response, 'name="gacha"')

    def test_the_bar_offers_no_column_filter_and_says_so(self) -> None:
        response = self.client.get(page("xodimlar-yuklamasi"))

        self.assertNotContains(response, "Filter:")
        self.assertContains(response, "Sana:")

    def test_a_type_the_matrix_refuses_cannot_open_it(self) -> None:
        manager = make_user("report.manager", user_type=MENEJER)
        self.client.force_login(manager)

        response = self.client.get(page("xodimlar-yuklamasi"))

        self.assertEqual(response.status_code, 403)
