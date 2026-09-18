"""Tests for the Hisobotlar reports (TASK-UZK-044).

Xodimlar yuklamasi counts what each specialist is carrying, one column per
active contract status (REQ-YUKLAMA-002, DEC-010).
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from tests.support import (
    SignedInAdminTestCase,
    a_category,
    a_contract,
    a_department,
    an_application,
    an_assigned_application,
    arrived_on,
    assigned_on,
    make_user,
    page,
)
from xarid.filters import DateColumn, DatePeriod
from xarid.models import (
    ADMIN,
    KATTA_MUTAXASIS,
    MENEJER,
    Application,
    ApplicationItem,
    ShartnomaStatus,
)
from xarid.reports import (
    ReportRow,
    category_purchasing,
    department_purchasing,
    staff_workload,
    status_columns,
)
from xarid.views import CATEGORY_REPORT_PERIOD, category_report_filter

ASSIGNMENT_PERIOD = DateColumn("Tayinlangan sana", "tayinlangan_sana")
ARRIVAL_PERIOD = DateColumn("Kelib tushgan sana", "kelib_tushgan_sana")

REFUSED_INVERTED_PERIOD = "Davr boshlanishi tugashidan keyin"


def period(**chosen: str) -> DatePeriod:
    """The assignment period a request with these bounds would produce."""
    return DatePeriod(ASSIGNMENT_PERIOD, chosen)


def arrival_period(**chosen: str) -> DatePeriod:
    """The arrival period the departments report is narrowed by."""
    return DatePeriod(ARRIVAL_PERIOD, chosen)


def category_period(**chosen: str) -> DatePeriod:
    """The period the type report is narrowed by.

    Built from the column the page itself declares, so the test exercises the
    production path from a product type to the date rather than a copy of it.
    """
    return DatePeriod(CATEGORY_REPORT_PERIOD, chosen)


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

    def test_the_busiest_specialist_is_first(self) -> None:
        an_assigned_application(self.head, self.idle)
        an_assigned_application(self.head, self.busy)
        an_assigned_application(self.head, self.busy)

        report = staff_workload(None)

        self.assertEqual(report.rows[0].subject_label, "Alisher")
        self.assertEqual(report.rows[0].total, 2)

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


class DepartmentPurchasingTests(TestCase):
    """What each department is buying (REQ-XARID-001)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("dept.head", user_type=ADMIN)
        cls.texnik = a_department("Texnik bo`lim")
        cls.moliya = a_department("Moliya bo`limi")
        cls.quiet = a_department("Logistika")
        cls.statuses = tuple(ShartnomaStatus.objects.active())

    def row_for(self, department_name: str, report) -> ReportRow:
        for row in report.rows:
            if row.subject_label == department_name:
                return row
        self.fail(f"{department_name} is not in the report")

    def test_every_active_department_appears_once(self) -> None:
        an_application(department=self.texnik)

        report = department_purchasing(None)

        labels = [row.subject_label for row in report.rows]
        self.assertEqual(sorted(labels), sorted(set(labels)))
        for department in (self.texnik, self.moliya, self.quiet):
            with self.subTest(department=department.name):
                self.assertIn(department.name, labels)

    def test_a_department_with_no_activity_shows_zeros(self) -> None:
        an_application(department=self.texnik)

        report = department_purchasing(None)

        quiet = self.row_for("Logistika", report)
        self.assertEqual(quiet.total, 0)
        self.assertEqual(set(quiet.counters), {0})

    def test_a_counter_is_the_applications_with_a_contract_in_that_status(self) -> None:
        first, second = self.statuses[0], self.statuses[1]
        a_contract(an_application(department=self.texnik), self.head, status=first)
        a_contract(an_application(department=self.texnik), self.head, status=first)
        a_contract(an_application(department=self.moliya), self.head, status=second)
        an_application(department=self.texnik)

        report = department_purchasing(None)

        texnik = self.row_for("Texnik bo`lim", report)
        self.assertEqual(texnik.total, 3)
        self.assertEqual(texnik.counters[0], 2)
        self.assertEqual(texnik.counters[1], 0)
        self.assertEqual(self.row_for("Moliya bo`limi", report).counters[1], 1)

    def test_the_totals_row_is_the_sum_of_each_column(self) -> None:
        first = self.statuses[0]
        a_contract(an_application(department=self.texnik), self.head, status=first)
        a_contract(an_application(department=self.moliya), self.head, status=first)

        report = department_purchasing(None)

        self.assertEqual(report.totals.total, sum(row.total for row in report.rows))
        for index in range(len(report.columns)):
            with self.subTest(column=report.columns[index].label):
                self.assertEqual(
                    report.totals.counters[index],
                    sum(row.counters[index] for row in report.rows),
                )
        self.assertEqual(report.totals.counters[0], 2)

    def test_the_busiest_department_is_first(self) -> None:
        an_application(department=self.moliya)
        an_application(department=self.texnik)
        an_application(department=self.texnik)

        report = department_purchasing(None)

        self.assertEqual(report.rows[0].subject_label, "Texnik bo`lim")
        self.assertEqual(report.rows[0].total, 2)

    def test_the_columns_are_the_active_statuses_in_their_order(self) -> None:
        expected = [status.name for status in ShartnomaStatus.objects.active()]

        report = department_purchasing(None)

        self.assertEqual([column.label for column in report.columns], expected)

    def test_a_period_counts_only_the_applications_that_arrived_inside_it(self) -> None:
        inside = arrived_on(date(2026, 2, 10))
        outside = arrived_on(date(2026, 5, 10))
        Application.objects.filter(pk__in=[inside.pk, outside.pk]).update(department=self.texnik)

        report = department_purchasing(arrival_period(dan="2026-02-01", gacha="2026-02-28"))

        self.assertEqual(self.row_for("Texnik bo`lim", report).total, 1)

    def test_a_refused_period_counts_everything(self) -> None:
        first = arrived_on(date(2026, 2, 10))
        second = arrived_on(date(2026, 5, 10))
        Application.objects.filter(pk__in=[first.pk, second.pk]).update(department=self.texnik)

        report = department_purchasing(arrival_period(dan="2026-05-01", gacha="2026-01-01"))

        self.assertEqual(self.row_for("Texnik bo`lim", report).total, 2)

    def test_choosing_a_department_leaves_one_row(self) -> None:
        an_application(department=self.texnik)
        an_application(department=self.moliya)

        report = department_purchasing(None, str(self.moliya.pk))

        self.assertEqual([row.subject_label for row in report.rows], ["Moliya bo`limi"])
        self.assertEqual(report.totals.total, 1)

    def test_an_inactive_department_has_no_row(self) -> None:
        self.quiet.is_active = False
        self.quiet.save(update_fields=["is_active"])

        report = department_purchasing(None)

        self.assertNotIn("Logistika", [row.subject_label for row in report.rows])

    def test_the_query_count_does_not_grow_with_the_statuses(self) -> None:
        an_application(department=self.texnik)

        with self.assertNumQueries(2):
            department_purchasing(None)

        ShartnomaStatus.objects.create(name="Tekshiruvda", badge_colour="blue")
        ShartnomaStatus.objects.create(name="Kutilmoqda", badge_colour="grey")

        with self.assertNumQueries(2):
            department_purchasing(None)


class DepartmentPurchasingPageTests(SignedInAdminTestCase):
    """The departments report as the page renders it."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.texnik = a_department("Texnik bo`lim")
        cls.moliya = a_department("Moliya bo`limi")

    def test_the_page_answers_with_no_data_at_all(self) -> None:
        response = self.client.get(page("bolimlar"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Korhona Xaridi")

    def test_the_page_prints_a_row_per_department_and_the_totals(self) -> None:
        status = ShartnomaStatus.objects.active().first()
        a_contract(an_application(department=self.texnik), self.admin, status=status)

        response = self.client.get(page("bolimlar"))

        self.assertContains(response, status.name)
        self.assertContains(response, 'data-jami="1"')

    def test_a_department_name_links_to_the_products_page_with_the_department(self) -> None:
        an_application(department=self.texnik)

        response = self.client.get(page("bolimlar"))

        self.assertContains(response, f"?bolim={self.texnik.pk}")

    def test_the_page_narrows_to_the_chosen_department(self) -> None:
        an_application(department=self.texnik)
        an_application(department=self.moliya)

        response = self.client.get(page("bolimlar"), {"bolim": self.moliya.pk})

        self.assertContains(response, f"?bolim={self.moliya.pk}")
        self.assertNotContains(response, f"?bolim={self.texnik.pk}")

    def test_the_page_refuses_an_unknown_department_with_a_message(self) -> None:
        an_application(department=self.texnik)

        response = self.client.get(page("bolimlar"), {"bolim": "9999"})

        self.assertContains(response, "Noma&#39;lum filtr qiymati")
        self.assertContains(response, f"?bolim={self.texnik.pk}")

    def test_the_page_narrows_to_the_chosen_period(self) -> None:
        inside = arrived_on(date(2026, 2, 10))
        outside = arrived_on(date(2026, 5, 10))
        Application.objects.filter(pk__in=[inside.pk, outside.pk]).update(department=self.texnik)

        response = self.client.get(page("bolimlar"), {"dan": "2026-02-01", "gacha": "2026-02-28"})

        self.assertContains(response, 'data-jami="1"')

    def test_the_page_refuses_an_inverted_period_with_a_message(self) -> None:
        arrived_on(date(2026, 2, 10))

        response = self.client.get(page("bolimlar"), {"dan": "2026-05-01", "gacha": "2026-01-01"})

        self.assertContains(response, REFUSED_INVERTED_PERIOD)
        self.assertContains(response, 'data-jami="1"')

    def test_the_drop_down_does_not_offer_a_department_without_a_row(self) -> None:
        retired = a_department("Eski bo" + chr(96) + "lim")
        an_application(department=retired)
        retired.is_active = False
        retired.save(update_fields=["is_active"])

        response = self.client.get(page("bolimlar"))

        self.assertNotContains(response, f'value="{retired.pk}"')

    def test_a_type_the_matrix_refuses_cannot_open_it(self) -> None:
        manager = make_user("departments.manager", user_type=MENEJER)
        self.client.force_login(manager)

        response = self.client.get(page("bolimlar"))

        self.assertEqual(response.status_code, 403)


class CategoryPurchasingTests(TestCase):
    """What is bought of each product type (REQ-XARID-002)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("cat.head", user_type=ADMIN)
        cls.metal = a_category(100042, "Metallurgiya")
        cls.kimyo = a_category(200031, "Kimyoviy")
        cls.quiet = a_category(300015, "Elektr")
        cls.statuses = tuple(ShartnomaStatus.objects.active())

    def row_for(self, name: str, report) -> ReportRow:
        for row in report.rows:
            if row.subject_label == name:
                return row
        self.fail(f"{name} is not in the report")

    def test_every_active_type_appears_once(self) -> None:
        an_application(category=self.metal)

        report = category_purchasing(None)

        labels = [row.subject_label for row in report.rows]
        self.assertEqual(sorted(labels), sorted(set(labels)))
        for category in (self.metal, self.kimyo, self.quiet):
            with self.subTest(category=category.name):
                self.assertIn(category.name, labels)

    def test_a_type_nothing_has_ordered_shows_zeros(self) -> None:
        an_application(category=self.metal)

        report = category_purchasing(None)

        quiet = self.row_for("Elektr", report)
        self.assertEqual(quiet.total, 0)
        self.assertEqual(set(quiet.counters), {0})

    def test_two_lines_of_one_type_count_as_one_application(self) -> None:
        application = an_application(category=self.metal)
        ApplicationItem.objects.create(
            application=application,
            mahsulot_turi=self.metal,
            buyurtma_nomi="Ikkinchi qator",
            buyurtma_soni=2,
            olchov_birligi="ta",
        )

        report = category_purchasing(None)

        self.assertEqual(self.row_for("Metallurgiya", report).total, 1)

    def test_an_application_of_two_types_counts_under_each(self) -> None:
        application = an_application(category=self.metal)
        ApplicationItem.objects.create(
            application=application,
            mahsulot_turi=self.kimyo,
            buyurtma_nomi="Kislota",
            buyurtma_soni=5,
            olchov_birligi="l",
        )

        report = category_purchasing(None)

        self.assertEqual(self.row_for("Metallurgiya", report).total, 1)
        self.assertEqual(self.row_for("Kimyoviy", report).total, 1)

    def test_a_counter_is_the_applications_with_a_contract_in_that_status(self) -> None:
        first = self.statuses[0]
        a_contract(an_application(category=self.metal), self.head, status=first)
        an_application(category=self.metal)

        report = category_purchasing(None)

        metal = self.row_for("Metallurgiya", report)
        self.assertEqual(metal.total, 2)
        self.assertEqual(metal.counters[0], 1)

    def test_the_totals_row_is_the_sum_of_each_column(self) -> None:
        first = self.statuses[0]
        a_contract(an_application(category=self.metal), self.head, status=first)
        a_contract(an_application(category=self.kimyo), self.head, status=first)

        report = category_purchasing(None)

        self.assertEqual(report.totals.total, sum(row.total for row in report.rows))
        for index in range(len(report.columns)):
            with self.subTest(column=report.columns[index].label):
                self.assertEqual(
                    report.totals.counters[index],
                    sum(row.counters[index] for row in report.rows),
                )
        self.assertEqual(report.totals.counters[0], 2)

    def test_the_busiest_type_is_first(self) -> None:
        an_application(category=self.kimyo)
        an_application(category=self.metal)
        an_application(category=self.metal)

        report = category_purchasing(None)

        self.assertEqual(report.rows[0].subject_label, "Metallurgiya")
        self.assertEqual(report.rows[0].total, 2)

    def test_a_row_carries_the_code_and_the_id(self) -> None:
        an_application(category=self.metal)

        row = self.row_for("Metallurgiya", category_purchasing(None))

        self.assertEqual(row.detail, "100042")
        self.assertEqual(row.subject_id, self.metal.pk)

    def test_the_columns_are_the_active_statuses_in_their_order(self) -> None:
        expected = [status.name for status in ShartnomaStatus.objects.active()]

        report = category_purchasing(None)

        self.assertEqual([column.label for column in report.columns], expected)

    def test_a_period_counts_only_what_arrived_inside_it(self) -> None:
        inside = arrived_on(date(2026, 2, 10))
        outside = arrived_on(date(2026, 5, 10))
        ApplicationItem.objects.filter(
            application__in=[inside, outside]
        ).update(mahsulot_turi=self.metal)

        report = category_purchasing(category_period(dan="2026-02-01", gacha="2026-02-28"))

        self.assertEqual(self.row_for("Metallurgiya", report).total, 1)

    def test_choosing_a_type_leaves_one_row(self) -> None:
        an_application(category=self.metal)
        an_application(category=self.kimyo)

        report = category_purchasing(None, str(self.kimyo.pk))

        self.assertEqual([row.subject_label for row in report.rows], ["Kimyoviy"])

    def test_an_inactive_type_has_no_row(self) -> None:
        self.quiet.is_active = False
        self.quiet.save(update_fields=["is_active"])

        report = category_purchasing(None)

        self.assertNotIn("Elektr", [row.subject_label for row in report.rows])

    def test_the_query_count_does_not_grow_with_the_statuses(self) -> None:
        an_application(category=self.metal)

        with self.assertNumQueries(2):
            category_purchasing(None)

        ShartnomaStatus.objects.create(name="Tekshiruvda", badge_colour="blue")
        ShartnomaStatus.objects.create(name="Kutilmoqda", badge_colour="grey")

        with self.assertNumQueries(2):
            category_purchasing(None)


class CategoryPurchasingPageTests(SignedInAdminTestCase):
    """The report as the page renders it, and where Ko`rish goes."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.metal = a_category(100042, "Metallurgiya")
        cls.kimyo = a_category(200031, "Kimyoviy")

    def test_the_page_answers_with_no_data_at_all(self) -> None:
        response = self.client.get(page("mahsulot-tur"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mahsulot Turi")

    def test_the_page_prints_a_row_per_type_with_its_code_and_the_totals(self) -> None:
        status = ShartnomaStatus.objects.active().first()
        a_contract(an_application(category=self.metal), self.admin, status=status)

        response = self.client.get(page("mahsulot-tur"))

        self.assertContains(response, "Metallurgiya")
        self.assertContains(response, "100042")
        self.assertContains(response, status.name)
        self.assertContains(response, 'data-jami="1"')

    def test_the_page_narrows_to_the_chosen_type(self) -> None:
        an_application(category=self.metal)
        an_application(category=self.kimyo)

        response = self.client.get(page("mahsulot-tur"), {"mahsulot": self.kimyo.pk})

        # The drop-down still offers every type; it is the table that narrows,
        # so assert on the rows rather than on the page as a whole.
        self.assertContains(response, f"/mahsulotlar/?mahsulot={self.kimyo.pk}")
        self.assertNotContains(response, f"/mahsulotlar/?mahsulot={self.metal.pk}")

    def test_the_page_narrows_to_the_chosen_period(self) -> None:
        inside = arrived_on(date(2026, 2, 10))
        outside = arrived_on(date(2026, 5, 10))
        ApplicationItem.objects.filter(
            application__in=[inside, outside]
        ).update(mahsulot_turi=self.metal)

        response = self.client.get(
            page("mahsulot-tur"), {"dan": "2026-02-01", "gacha": "2026-02-28"}
        )

        self.assertContains(response, 'data-jami="1"')

    def test_the_page_refuses_an_inverted_period_with_a_message(self) -> None:
        an_application(category=self.metal)

        response = self.client.get(
            page("mahsulot-tur"), {"dan": "2026-05-01", "gacha": "2026-01-01"}
        )

        self.assertContains(response, REFUSED_INVERTED_PERIOD)

    def test_korish_links_to_the_products_page_with_the_type(self) -> None:
        an_application(category=self.metal)

        response = self.client.get(page("mahsulot-tur"))

        self.assertContains(response, f"?mahsulot={self.metal.pk}")

    def test_korish_lists_exactly_the_products_of_that_type(self) -> None:
        metal = an_application(category=self.metal)
        kimyo = an_application(category=self.kimyo)

        followed = self.client.get(page("mahsulotlar"), {"mahsulot": self.metal.pk})

        self.assertContains(followed, metal.ariza_raqami)
        self.assertNotContains(followed, kimyo.ariza_raqami)

    def test_korish_on_a_type_with_no_products_renders_an_empty_list(self) -> None:
        empty = a_category(400001, "Bo`sh tur")

        followed = self.client.get(page("mahsulotlar"), {"mahsulot": empty.pk})

        self.assertEqual(followed.status_code, 200)
        self.assertContains(followed, "Mahsulot topilmadi.")

    def test_the_bar_can_narrow_its_own_rows_by_the_period(self) -> None:
        """Every other bar in the application can; this one must not be the odd one.

        Its rows are product types while its period is a date on the
        application, so the column has to carry the path between them - or
        apply() raises FieldError on the one bar nobody happened to call.
        """
        inside = arrived_on(date(2026, 2, 10))
        outside = arrived_on(date(2026, 5, 10))
        ApplicationItem.objects.filter(application=inside).update(mahsulot_turi=self.metal)
        ApplicationItem.objects.filter(application=outside).update(mahsulot_turi=self.kimyo)

        narrowed = category_report_filter({"dan": "2026-02-01", "gacha": "2026-02-28"}).apply()

        self.assertEqual([category.name for category in narrowed], ["Metallurgiya"])

    def test_a_type_the_matrix_refuses_cannot_open_it(self) -> None:
        manager = make_user("category.manager", user_type=MENEJER)
        self.client.force_login(manager)

        response = self.client.get(page("mahsulot-tur"))

        self.assertEqual(response.status_code, 403)
