"""Tests for the dashboard contract indicators (TASK-UZK-048).

The dashboard opens with the supplier count and the created and completed
contracts as percentages of it (REQ-DASH-001 to REQ-DASH-004). Which status
counts as completed is master data, not a name in the code (DEC-010), so the
tests move the marker and expect the figure to follow.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    a_department,
    a_supplier,
    an_assigned_application,
    make_user,
    page,
)
from xarid.filters import DatePeriod
from xarid.models import (
    KATTA_MUTAXASIS,
    MENEJER,
    Contract,
    ShartnomaStatus,
    Supplier,
    deactivate,
)
from xarid.reports import (
    SPENDINGS_PERIOD,
    Money,
    dashboard_indicators,
    spending_indicators,
)

DELIVERED = "Yetkazib berilgan"
DRAWN_UP = "Shartnoma tuzilgan"

# What money_display() groups thousands with: a non-breaking space, so that a
# browser cannot wrap an amount across two lines.
GROUP_SEPARATOR = " "


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

    def test_a_deleted_status_still_holds_the_marker(self) -> None:
        """Deleting deactivates (DEC-009); what was finished stays finished."""
        delivered = ShartnomaStatus.objects.get(name=DELIVERED)
        deactivate(delivered)

        self.assertEqual(ShartnomaStatus.completed_status(), delivered)


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
        self.assertEqual((created.count, created.measured_against, created.percentage), (1, 5, 20))

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

    def test_a_half_percent_rounds_up(self) -> None:
        """12.5% is 13% on the card, which is the arithmetic a person does."""
        for name, inn in (
            ("MetalGrup JV", "223456789"),
            ("UzElektro", "323456789"),
            ("GazTrade", "423456789"),
            ("QurilishMat", "523456789"),
            ("Kimyo Invest", "623456789"),
            ("Neft Trade", "723456789"),
            ("Agro Mash", "823456789"),
        ):
            a_supplier(name=name, inn=inn)
        self.a_contract_in(self.drawn_up)

        created = dashboard_indicators().created

        # One contract, eight suppliers: the seven above and a_contract()'s own.
        self.assertEqual((created.count, created.measured_against), (1, 8))
        self.assertEqual(created.percentage, 13)

    def test_more_contracts_than_suppliers_pass_a_hundred_percent(self) -> None:
        """A supplier may hold several contracts, so the ratio is not clamped."""
        self.a_contract_in(self.drawn_up)
        self.a_contract_in(self.drawn_up)
        self.a_contract_in(self.drawn_up)

        created = dashboard_indicators().created

        self.assertEqual(
            (created.count, created.measured_against, created.percentage), (3, 1, 300)
        )
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
        # The card itself, not the progress bar's width:100% on the same card.
        self.assertContains(response, '<div class="kpi-value">100%</div>', html=False)
        self.assertContains(response, '<div class="kpi-value">1</div>', html=False)

    def test_an_empty_database_still_renders(self) -> None:
        response = self.client.get(page("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0 / 0 jami")

    def test_a_type_that_may_not_open_it_is_refused(self) -> None:
        """The DEC-015 matrix still closes the page; it has a real view now."""
        self.client.force_login(make_user("dash.outsider", user_type=KATTA_MUTAXASIS))

        response = self.client.get(page("dashboard"))

        self.assertEqual(response.status_code, 403)


class SpendingTests(TestCase):
    """What the Sariflangan card adds up (REQ-DASH-008, REQ-DASH-010)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("spend.manager", user_type=MENEJER)
        cls.specialist = make_user("spend.specialist", user_type=KATTA_MUTAXASIS)
        cls.department = a_department()

    @property
    def today(self) -> date:
        """Read per test: a class attribute would go stale across midnight."""
        return timezone.localdate()

    def a_contract_worth(self, amount: str, on: date | None = None) -> Contract:
        """One contract of a known value, dated on a known day.

        The value is the sum of the goods rows, which raise_contract computes
        and refuses to be given, so it is written afterwards; `on` is the
        contract's own date, and None leaves it absent the way a contract
        loaded outside the entry form would be.
        """
        application = an_assigned_application(
            self.manager, self.specialist, department=self.department
        )
        contract = a_contract(application, self.specialist)
        Contract.objects.filter(pk=contract.pk).update(
            qiymati=Decimal(amount), shartnoma_sanasi=on
        )
        return contract

    def period_between(self, start: date, end: date) -> DatePeriod:
        """The period bar's own object, built the way a request builds it."""
        return DatePeriod(
            SPENDINGS_PERIOD,
            {"dan": start.isoformat(), "gacha": end.isoformat()},
        )

    def test_the_period_total_is_the_sum_of_the_contracts_inside_it(self) -> None:
        self.a_contract_worth("100.00", on=self.today - timedelta(days=1))
        self.a_contract_worth("250.00", on=self.today)
        self.a_contract_worth("999.00", on=self.today + timedelta(days=1))

        period = self.period_between(self.today - timedelta(days=1), self.today)

        self.assertEqual(spending_indicators(period).period.amount, Decimal("350.00"))

    def test_a_period_with_no_contracts_is_zero(self) -> None:
        self.a_contract_worth("100.00", on=self.today)

        period = self.period_between(
            self.today - timedelta(days=30), self.today - timedelta(days=20)
        )

        self.assertEqual(spending_indicators(period).period.amount, Decimal("0"))

    def test_no_period_means_every_contract_on_file(self) -> None:
        self.a_contract_worth("100.00", on=self.today - timedelta(days=400))
        self.a_contract_worth("250.00", on=self.today)

        self.assertEqual(spending_indicators(None).period.amount, Decimal("350.00"))

    def test_the_year_covers_the_calendar_year_and_nothing_outside_it(self) -> None:
        year = self.today.year
        self.a_contract_worth("500.00", on=date(year, 1, 1))
        self.a_contract_worth("700.00", on=date(year, 12, 31))
        self.a_contract_worth("900.00", on=date(year - 1, 12, 31))

        indicators = spending_indicators(None)

        self.assertEqual(indicators.year_number, year)
        self.assertEqual(indicators.year.amount, Decimal("1200.00"))

    def test_the_year_ignores_the_chosen_period(self) -> None:
        """Narrowing to one day moves the spend and leaves the year alone."""
        self.a_contract_worth("500.00", on=date(self.today.year, 1, 1))
        self.a_contract_worth("700.00", on=self.today)

        narrowed = spending_indicators(self.period_between(self.today, self.today))

        self.assertEqual(narrowed.period.amount, Decimal("700.00"))
        self.assertEqual(narrowed.year.amount, Decimal("1200.00"))

    def test_a_contract_with_no_date_of_its_own_counts_on_the_day_it_was_raised(self) -> None:
        """The column allows null even though the entry form requires it."""
        self.a_contract_worth("400.00", on=None)

        today_only = self.period_between(self.today, self.today)

        self.assertEqual(spending_indicators(today_only).period.amount, Decimal("400.00"))

    def test_a_refused_period_is_not_applied(self) -> None:
        """A start after the end narrows nothing, as on every other page."""
        self.a_contract_worth("100.00", on=self.today)
        backwards = self.period_between(self.today, self.today - timedelta(days=5))

        self.assertIsNotNone(backwards.refusal)
        self.assertEqual(spending_indicators(backwards).period.amount, Decimal("100.00"))

    def test_an_amount_prints_grouped_and_without_tiyin_on_the_card(self) -> None:
        money = Money(Decimal("1240000000.00"))
        billion = GROUP_SEPARATOR.join(("1", "240", "000", "000"))

        self.assertEqual(money.display, f"{billion},00")
        self.assertEqual(money.whole_display, billion)

    def test_a_whole_soum_amount_never_renders_as_nothing(self) -> None:
        """The headline drops the tiyin; it must not drop the amount with it."""
        for amount in ("0", "1", "999", "1000000"):
            with self.subTest(amount=amount):
                self.assertTrue(Money(Decimal(amount)).whole_display.strip())


class SpendingPageTests(SignedInAdminTestCase):
    """The card and the period bar as the page renders them."""

    def a_contract_worth(self, amount: str, on: date) -> None:
        manager = make_user(f"page.spend.manager.{amount}", user_type=MENEJER)
        specialist = make_user(f"page.spend.specialist.{amount}", user_type=KATTA_MUTAXASIS)
        application = an_assigned_application(manager, specialist, department=a_department())
        contract = a_contract(application, specialist)
        Contract.objects.filter(pk=contract.pk).update(
            qiymati=Decimal(amount), shartnoma_sanasi=on
        )

    def test_the_card_prints_the_period_total_in_uzs(self) -> None:
        today = timezone.localdate()
        self.a_contract_worth("1500", on=today)

        response = self.client.get(page("dashboard"), {"dan": today.isoformat()})

        self.assertEqual(response.status_code, 200)
        # The figure itself, grouped as the department reads it, rather than
        # whatever money_display() happens to return today.
        self.assertContains(response, f"1{GROUP_SEPARATOR}500 UZS")
        self.assertContains(response, f"1{GROUP_SEPARATOR}500,00 UZS")
        self.assertContains(response, "tanlangan davr")

    def test_the_page_offers_the_period_bar(self) -> None:
        response = self.client.get(page("dashboard"))

        self.assertContains(response, 'name="dan"')
        self.assertContains(response, 'name="gacha"')
        self.assertContains(response, "jami")

    def test_a_refused_period_is_reported_to_the_reader(self) -> None:
        today = timezone.localdate()

        response = self.client.get(
            page("dashboard"),
            {"dan": today.isoformat(), "gacha": (today - timedelta(days=1)).isoformat()},
            follow=True,
        )

        self.assertContains(response, "Davr boshlanishi tugashidan keyin")
