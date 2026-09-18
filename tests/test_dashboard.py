"""Tests for the dashboard contract indicators (TASK-UZK-048).

The dashboard opens with the supplier count and the created and completed
contracts as percentages of it (REQ-DASH-001 to REQ-DASH-004). Which status
counts as completed is master data, not a name in the code (DEC-010), so the
tests move the marker and expect the figure to follow.
"""

from __future__ import annotations

from django.test import TestCase

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    a_department,
    a_supplier,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import KATTA_MUTAXASIS, MENEJER, ShartnomaStatus, Supplier, deactivate
from xarid.reports import dashboard_indicators

DELIVERED = "Yetkazib berilgan"
DRAWN_UP = "Shartnoma tuzilgan"


class CompletedStatusTests(TestCase):
    """The marker that says which status means completed."""

    def test_the_seeded_delivered_status_carries_the_marker(self) -> None:
        """The migration configures the DEC-010 example, so a fresh database has one."""
        completed = ShartnomaStatus.completed_status()

        self.assertIsNotNone(completed)
        self.assertEqual(completed.name, DELIVERED)

    def test_marking_another_status_moves_the_marker(self) -> None:
        """Only one status may mean completed, so marking one clears the other."""
        drawn_up = ShartnomaStatus.objects.get(name=DRAWN_UP)
        drawn_up.is_completed = True
        drawn_up.save()

        self.assertEqual(ShartnomaStatus.completed_status(), drawn_up)
        self.assertFalse(ShartnomaStatus.objects.get(name=DELIVERED).is_completed)

    def test_nothing_marked_means_nothing_is_completed(self) -> None:
        """Master data may be edited into having no completed state at all."""
        ShartnomaStatus.objects.update(is_completed=False)

        self.assertIsNone(ShartnomaStatus.completed_status())


class IndicatorTests(TestCase):
    """What the three figures count."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("dash.manager", user_type=MENEJER)
        cls.specialist = make_user("dash.specialist", user_type=KATTA_MUTAXASIS)
        cls.department = a_department()
        cls.delivered = ShartnomaStatus.objects.get(name=DELIVERED)
        cls.drawn_up = ShartnomaStatus.objects.get(name=DRAWN_UP)

    def a_contract_in(self, status: ShartnomaStatus | None) -> None:
        """One contract against a fresh application, in the given status."""
        application = an_assigned_application(
            self.manager,
            self.specialist,
            department=self.department,
        )
        a_contract(application, self.specialist, status=status)

    def test_the_supplier_count_is_the_number_of_supplier_records(self) -> None:
        a_supplier(name="Texnoprom LLC", inn="123456789")
        a_supplier(name="MetalGrup JV", inn="223456789")

        self.assertEqual(dashboard_indicators().supplier_count, 2)

    def test_a_deleted_supplier_is_not_counted(self) -> None:
        """DEC-009 deletes a firma by deactivating it; the count follows."""
        a_supplier(name="Texnoprom LLC", inn="123456789")
        deactivate(a_supplier(name="UzElektro", inn="323456789"))

        self.assertEqual(dashboard_indicators().supplier_count, 1)

    def test_created_is_every_contract_as_a_percentage_of_the_suppliers(self) -> None:
        a_supplier(name="MetalGrup JV", inn="223456789")
        a_supplier(name="UzElektro", inn="323456789")
        a_supplier(name="GazTrade", inn="423456789")
        a_supplier(name="QurilishMat", inn="523456789")
        self.a_contract_in(self.drawn_up)

        created = dashboard_indicators().created

        # Five suppliers: the four above and the one a_contract() raises with.
        self.assertEqual((created.count, created.of, created.percentage), (1, 5, 20))

    def test_completed_counts_only_the_status_marked_completed(self) -> None:
        self.a_contract_in(self.delivered)
        self.a_contract_in(self.drawn_up)
        self.a_contract_in(None)

        indicators = dashboard_indicators()

        self.assertEqual(indicators.created.count, 3)
        self.assertEqual(indicators.completed.count, 1)

    def test_the_completed_figure_follows_the_marker(self) -> None:
        """Move the marker and the same contracts are counted differently."""
        self.a_contract_in(self.delivered)
        self.a_contract_in(self.drawn_up)
        self.drawn_up.is_completed = True
        self.drawn_up.save()

        self.assertEqual(dashboard_indicators().completed.count, 1)
        self.assertEqual(
            dashboard_indicators().completed.count,
            ShartnomaStatus.objects.get(name=DRAWN_UP).contracts.count(),
        )

    def test_no_completed_status_means_no_completed_contracts(self) -> None:
        self.a_contract_in(self.delivered)
        ShartnomaStatus.objects.update(is_completed=False)

        completed = dashboard_indicators().completed

        self.assertEqual((completed.count, completed.percentage), (0, 0))

    def test_no_suppliers_divides_by_nothing(self) -> None:
        """An empty database renders zeros rather than raising."""
        self.assertFalse(Supplier.objects.exists())

        indicators = dashboard_indicators()

        self.assertEqual(indicators.supplier_count, 0)
        self.assertEqual(indicators.created.percentage, 0)
        self.assertEqual(indicators.completed.percentage, 0)

    def test_more_contracts_than_suppliers_pass_a_hundred_percent(self) -> None:
        """A supplier may hold several contracts, so the ratio is not clamped."""
        self.a_contract_in(self.drawn_up)
        self.a_contract_in(self.drawn_up)
        self.a_contract_in(self.drawn_up)

        created = dashboard_indicators().created

        self.assertEqual((created.count, created.of, created.percentage), (3, 1, 300))
        self.assertEqual(created.bar_width, 100)


class DashboardPageTests(SignedInAdminTestCase):
    """What the page itself renders."""

    def test_the_page_prints_the_counted_figures(self) -> None:
        manager = make_user("page.manager", user_type=MENEJER)
        specialist = make_user("page.specialist", user_type=KATTA_MUTAXASIS)
        application = an_assigned_application(manager, specialist, department=a_department())
        a_contract(application, specialist, status=ShartnomaStatus.objects.get(name=DELIVERED))

        response = self.client.get(page("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 / 1 jami")
        self.assertContains(response, "100%")

    def test_an_empty_database_still_renders(self) -> None:
        response = self.client.get(page("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0 / 0 jami")

    def test_a_type_that_may_not_open_it_is_refused(self) -> None:
        """The DEC-015 matrix still closes the page; it has a real view now."""
        self.client.force_login(make_user("dash.outsider", user_type=KATTA_MUTAXASIS))

        response = self.client.get(page("dashboard"))

        self.assertEqual(response.status_code, 403)
