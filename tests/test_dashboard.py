"""Tests for the dashboard contract indicators (TASK-UZK-048).

The dashboard opens with the supplier count and the created and completed
contracts as percentages of it (REQ-DASH-001 to REQ-DASH-004). Which status
counts as completed is master data, not a name in the code (DEC-010), so the
tests move the marker and expect the figure to follow.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
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
from xarid.dashboard import (
    APPROVAL,
    DELIVERY,
    INVOICE,
    ORDER_ENTRY,
    SPENDINGS_PERIOD,
    STAGE_SPANS,
    Money,
    StageAverage,
    completed_at,
    dashboard_indicators,
    processing_times,
    span_of,
    spending_indicators,
    supplier_categories,
)
from xarid.filters import DatePeriod
from xarid.models import (
    KATTA_MUTAXASIS,
    MENEJER,
    Application,
    ApplicationItem,
    Contract,
    ContractStatusChange,
    MahsulotTuri,
    ShartnomaStatus,
    Supplier,
    deactivate,
)

DELIVERED = "Yetkazib berilgan"
DRAWN_UP = "Shartnoma tuzilgan"

# A fixed moment the stage fixtures are dated from, so an average never
# depends on when the suite happened to run.
AT_NOON = timezone.make_aware(datetime(2026, 3, 2, 12, 0))

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

    def test_signed_contracts_are_a_percentage_of_the_suppliers(self) -> None:
        a_supplier(name="MetalGrup JV", inn="223456789")
        a_supplier(name="UzElektro", inn="323456789")
        a_supplier(name="GazTrade", inn="423456789")
        a_supplier(name="QurilishMat", inn="523456789")
        self.a_contract_in(self.drawn_up)

        created = dashboard_indicators().created

        # Five suppliers: the four above and the one a_contract() raises with.
        self.assertEqual((created.count, created.measured_against, created.percentage), (1, 5, 20))

    def test_it_counts_only_the_status_marked_signed(self) -> None:
        """DEC-039: the figure counts signed contracts, not every one raised."""
        self.a_contract_in(self.drawn_up)
        self.a_contract_in(self.delivered)
        self.a_contract_in(None)

        self.assertEqual(dashboard_indicators().created.count, 1)

    def test_the_signed_figure_follows_the_marker(self) -> None:
        """Move the marker and the same contracts are counted differently."""
        self.a_contract_in(self.drawn_up)
        self.a_contract_in(self.delivered)
        self.delivered.is_signed = True
        self.delivered.save()

        self.assertEqual(dashboard_indicators().created.count, 1)
        self.assertEqual(
            dashboard_indicators().created.count,
            ShartnomaStatus.objects.get(name=DELIVERED).contracts.count(),
        )

    def test_marking_one_status_signed_takes_the_marker_off_the_other(self) -> None:
        self.delivered.is_signed = True
        self.delivered.save()

        self.assertFalse(ShartnomaStatus.objects.get(name=DRAWN_UP).is_signed)
        self.assertEqual(ShartnomaStatus.objects.filter(is_signed=True).count(), 1)

    def test_nothing_is_signed_when_no_status_carries_the_marker(self) -> None:
        self.a_contract_in(self.drawn_up)
        ShartnomaStatus.objects.update(is_signed=False)

        self.assertEqual(dashboard_indicators().created.count, 0)

    def test_completed_counts_only_the_status_marked_completed(self) -> None:
        self.a_contract_in(self.delivered)
        self.a_contract_in(self.drawn_up)
        self.a_contract_in(None)

        indicators = dashboard_indicators()

        self.assertEqual(indicators.created.count, 1)
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

    def test_a_type_that_may_not_open_it_is_sent_to_their_own_page(self) -> None:
        """The matrix still closes the page: what changes is where they go.

        The dashboard answers at the site root, which is where a browser goes
        when it is given the host alone, so a reader who may not open it is
        sent to the first page that is theirs rather than told 403 for
        visiting the application (page_or_landing).
        """
        self.client.force_login(make_user("dash.outsider", user_type=KATTA_MUTAXASIS))

        response = self.client.get(page("dashboard"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], page("tayinlangan"))


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


class ProcessingTimeTests(TestCase):
    """The four stage averages (REQ-DASH-012, DEC-025)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("stage.manager", user_type=MENEJER)
        cls.specialist = make_user("stage.specialist", user_type=KATTA_MUTAXASIS)
        cls.department = a_department()

    def setUp(self) -> None:
        super().setUp()
        self.delivered = ShartnomaStatus.objects.get(name=DELIVERED)
        self.drawn_up = ShartnomaStatus.objects.get(name=DRAWN_UP)

    def a_contract_processed(
        self,
        *,
        arrived: datetime,
        raised: datetime,
        approved: datetime | None = None,
        delivered: datetime | None = None,
        invoiced: date | None = None,
    ) -> Contract:
        """One contract with its four moments written where the code reads them.

        The arrival and the raising are auto_now_add columns, so they are
        written after the fact; the delivery is a real status move whose
        changed_at is then set to the moment asked for.
        """
        application = an_assigned_application(
            self.manager, self.specialist, department=self.department
        )
        Application.objects.filter(pk=application.pk).update(kelib_tushgan_sana=arrived)
        contract = a_contract(application, self.specialist)
        Contract.objects.filter(pk=contract.pk).update(
            yaratilingan_sana=raised,
            tasdiqlangan_sana=approved,
            invoice_sanasi=invoiced,
        )
        if delivered is not None:
            contract.refresh_from_db()
            contract.set_status(self.delivered, by=self.specialist)
            ContractStatusChange.objects.filter(
                contract=contract, to_status=self.delivered
            ).update(changed_at=delivered)

        return contract

    def stage(self, label: str) -> StageAverage:
        """One stage of the panel, by its name."""
        return next(stage for stage in processing_times() if stage.label == label)

    def test_the_four_stages_are_listed_in_the_documents_order(self) -> None:
        self.assertEqual(
            [stage.label for stage in processing_times()],
            [ORDER_ENTRY, APPROVAL, DELIVERY, INVOICE],
        )

    def test_order_entry_is_the_arrival_to_the_contract_being_raised(self) -> None:
        self.a_contract_processed(arrived=AT_NOON, raised=AT_NOON + timedelta(days=3))

        entry = self.stage(ORDER_ENTRY)

        self.assertEqual((entry.days, entry.measured_from), (3, 1))

    def test_approval_is_measured_from_the_raising_not_the_last_send(self) -> None:
        """DEC-024 overwrites yuborilgan_sana on a resend; the average must not follow it."""
        contract = self.a_contract_processed(
            arrived=AT_NOON,
            raised=AT_NOON,
            approved=AT_NOON + timedelta(days=10),
        )
        Contract.objects.filter(pk=contract.pk).update(
            yuborilgan_sana=AT_NOON + timedelta(days=9)
        )

        approval = self.stage(APPROVAL)

        self.assertEqual((approval.days, approval.measured_from), (10, 1))

    def test_delivery_is_the_approval_to_the_first_arrival_at_completed(self) -> None:
        self.a_contract_processed(
            arrived=AT_NOON,
            raised=AT_NOON,
            approved=AT_NOON + timedelta(days=1),
            delivered=AT_NOON + timedelta(days=8),
        )

        delivery = self.stage(DELIVERY)

        self.assertEqual((delivery.days, delivery.measured_from), (7, 1))

    def test_a_contract_that_left_completed_and_returned_counts_its_first_arrival(self) -> None:
        contract = self.a_contract_processed(
            arrived=AT_NOON,
            raised=AT_NOON,
            approved=AT_NOON,
            delivered=AT_NOON + timedelta(days=4),
        )
        contract.refresh_from_db()
        contract.set_status(self.drawn_up, by=self.specialist)
        contract.set_status(self.delivered, by=self.specialist)

        self.assertEqual(self.stage(DELIVERY).days, 4)

    def test_invoice_is_the_delivery_to_the_date_on_the_contract(self) -> None:
        self.a_contract_processed(
            arrived=AT_NOON,
            raised=AT_NOON,
            approved=AT_NOON,
            delivered=AT_NOON,
            invoiced=AT_NOON.date() + timedelta(days=6),
        )

        invoice = self.stage(INVOICE)

        self.assertEqual((invoice.days, invoice.measured_from), (6, 1))

    def test_an_average_is_the_mean_of_what_completed_the_stage(self) -> None:
        self.a_contract_processed(arrived=AT_NOON, raised=AT_NOON + timedelta(days=2))
        self.a_contract_processed(arrived=AT_NOON, raised=AT_NOON + timedelta(days=4))
        self.a_contract_processed(arrived=AT_NOON, raised=AT_NOON + timedelta(days=9))

        entry = self.stage(ORDER_ENTRY)

        self.assertEqual((entry.days, entry.measured_from), (5, 3))

    def test_a_stage_nothing_completed_has_no_average_rather_than_zero(self) -> None:
        self.a_contract_processed(arrived=AT_NOON, raised=AT_NOON + timedelta(days=1))

        approval = self.stage(APPROVAL)

        self.assertIsNone(approval.days)
        self.assertFalse(approval.was_measured)
        self.assertEqual(approval.measured_from, 0)

    def test_a_contract_missing_one_end_is_left_out_of_that_stage_only(self) -> None:
        self.a_contract_processed(
            arrived=AT_NOON, raised=AT_NOON + timedelta(days=2), approved=None
        )
        self.a_contract_processed(
            arrived=AT_NOON,
            raised=AT_NOON + timedelta(days=2),
            approved=AT_NOON + timedelta(days=6),
        )

        self.assertEqual(self.stage(ORDER_ENTRY).measured_from, 2)
        self.assertEqual(self.stage(APPROVAL).measured_from, 1)
        self.assertEqual(self.stage(APPROVAL).days, 4)

    def test_nothing_at_all_leaves_every_stage_unmeasured(self) -> None:
        for stage in processing_times():
            with self.subTest(stage=stage.label):
                self.assertIsNone(stage.days)
                self.assertEqual(stage.measured_from, 0)

    def test_the_deliveries_are_read_without_listing_every_contract(self) -> None:
        """Two queries whatever the table holds, not one variable per contract.

        One to find the status marked completed and one for every move into
        it. SQLite refuses an IN list past its own parameter limit, so a
        department with enough contracts would have got a dashboard that did
        not render rather than a slow one.
        """
        for _ in range(3):
            self.a_contract_processed(
                arrived=AT_NOON, raised=AT_NOON, approved=AT_NOON, delivered=AT_NOON
            )

        with self.assertNumQueries(2):
            arrivals = completed_at()

        self.assertEqual(len(arrivals), 3)

    def test_a_stage_with_no_span_recorded_still_says_which_stage_it_is(self) -> None:
        self.assertIn("Tekshiruv", span_of("Tekshiruv"))


class ProcessingTimePageTests(SignedInAdminTestCase):
    """The panel as the page renders it."""

    def test_the_panel_names_every_stage_and_what_it_spans(self) -> None:
        response = self.client.get(page("dashboard"))

        self.assertEqual(response.status_code, 200)
        for label in (ORDER_ENTRY, APPROVAL, DELIVERY, INVOICE):
            with self.subTest(stage=label):
                self.assertContains(response, label)
                self.assertContains(response, STAGE_SPANS[label])

    def test_an_unmeasured_stage_prints_a_dash_rather_than_zero(self) -> None:
        """The stage's own cell, rather than every em dash on the page."""
        response = self.client.get(page("dashboard"))
        rendered = response.content.decode()

        for label in (ORDER_ENTRY, APPROVAL, DELIVERY, INVOICE):
            with self.subTest(stage=label):
                row = rendered.split(label, 1)[1].split("</tr>", 1)[0]
                self.assertIn("&mdash;", row)
                self.assertNotIn("badge-primary", row)

    def test_the_contract_form_offers_the_invoice_date(self) -> None:
        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, 'name="invoice_sanasi"')


class SupplierCategoryTests(TestCase):
    """The supplier category block (REQ-DASH-007, REQ-DASH-009)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("cat.manager", user_type=MENEJER)
        cls.specialist = make_user("cat.specialist", user_type=KATTA_MUTAXASIS)
        cls.department = a_department()

    def a_category(self, number: int, name: str) -> MahsulotTuri:
        category, _ = MahsulotTuri.objects.get_or_create(
            category_number=number, defaults={"name": name}
        )
        return category

    def a_supply(
        self, firm: Supplier, *categories: MahsulotTuri, delivered: bool = False
    ) -> None:
        """One contract with that firm, against an application ordering those types.

        `delivered` puts the contract in the status marked completed, which
        is what the delivered-types figure counts - a contract that merely
        exists is not a delivery.
        """
        application = an_assigned_application(
            self.manager, self.specialist, department=self.department
        )
        ApplicationItem.objects.filter(application=application).delete()
        for category in categories:
            ApplicationItem.objects.create(
                application=application,
                mahsulot_turi=category,
                buyurtma_nomi=f"{category.name} mahsuloti",
                buyurtma_soni=Decimal("1"),
                olchov_birligi="ta",
            )
        status = ShartnomaStatus.objects.get(name=DELIVERED) if delivered else None
        a_contract(application, self.specialist, supplier=firm, status=status)

    def a_firm(self, name: str, inn: str) -> Supplier:
        firm, _ = Supplier.objects.get_or_create(name=name, defaults={"inn": inn})
        return firm

    def counts_by_name(self) -> dict[str, int]:
        """The counts, by type name.

        Includes the type tests/support.py seeds for an application's order
        line, so a test reads the names it created rather than the whole
        table.
        """
        return {row.category.name: row.firms for row in supplier_categories().rows}

    def test_each_type_is_counted_once_with_the_firms_supplying_it(self) -> None:
        metal = self.a_category(100001, "Metall prokat")
        chemical = self.a_category(100002, "Kimyoviy")
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal)
        self.a_supply(self.a_firm("UzElektro", "323456789"), metal)
        self.a_supply(self.a_firm("Kimyo Invest", "423456789"), chemical)

        counts = self.counts_by_name()

        self.assertEqual((counts["Metall prokat"], counts["Kimyoviy"]), (2, 1))

    def test_a_firm_with_several_contracts_for_one_type_counts_once(self) -> None:
        metal = self.a_category(100001, "Metall prokat")
        firm = self.a_firm("MetalGrup JV", "223456789")
        self.a_supply(firm, metal)
        self.a_supply(firm, metal)
        self.a_supply(firm, metal)

        self.assertEqual(self.counts_by_name()["Metall prokat"], 1)

    def test_a_firm_supplying_two_types_counts_under_both(self) -> None:
        metal = self.a_category(100001, "Metall prokat")
        chemical = self.a_category(100002, "Kimyoviy")
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal, chemical)

        counts = self.counts_by_name()

        self.assertEqual((counts["Metall prokat"], counts["Kimyoviy"]), (1, 1))

    def test_a_type_nobody_supplies_is_listed_with_zero(self) -> None:
        metal = self.a_category(100001, "Metall prokat")
        self.a_category(100002, "Kimyoviy")
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal)

        counts = self.counts_by_name()

        self.assertEqual((counts["Metall prokat"], counts["Kimyoviy"]), (1, 0))

    def test_a_deleted_type_stops_being_listed(self) -> None:
        """DEC-009 deletes a type by deactivating it."""
        metal = self.a_category(100001, "Metall prokat")
        deactivate(self.a_category(100002, "Kimyoviy"))
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal)

        self.assertNotIn("Kimyoviy", self.counts_by_name())

    def test_the_shares_add_up_to_a_hundred(self) -> None:
        metal = self.a_category(100001, "Metall prokat")
        chemical = self.a_category(100002, "Kimyoviy")
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal, delivered=True)
        self.a_supply(self.a_firm("UzElektro", "323456789"), metal)
        self.a_supply(self.a_firm("Kimyo Invest", "423456789"), chemical, delivered=True)
        self.a_supply(self.a_firm("Neft Trade", "523456789"), chemical)

        categories = supplier_categories()

        self.assertEqual(sum(row.share for row in categories.rows), 100)
        self.assertEqual(categories.placements, 4)
        self.assertEqual(categories.delivered_types, 2)

    def test_shares_that_do_not_divide_evenly_stay_within_rounding(self) -> None:
        """Three thirds are 33 each: a hundred within rounding, not on the nose."""
        for number, name, inn in (
            (100001, "Metall prokat", "223456789"),
            (100002, "Kimyoviy", "323456789"),
            (100003, "Qurilish", "423456789"),
        ):
            self.a_supply(self.a_firm(name + " LLC", inn), self.a_category(number, name))

        shares = [
            row.share
            for row in supplier_categories().rows
            if row.category.name in {"Metall prokat", "Kimyoviy", "Qurilish"}
        ]

        self.assertEqual(shares, [33, 33, 33])
        self.assertLessEqual(abs(sum(shares) - 100), len(shares))

    def test_nothing_supplied_leaves_every_share_at_zero(self) -> None:
        self.a_category(100001, "Metall prokat")

        categories = supplier_categories()

        self.assertEqual({row.share for row in categories.rows}, {0})
        self.assertEqual((categories.placements, categories.delivered_types), (0, 0))

    def test_the_delivered_total_counts_types_that_reached_completed(self) -> None:
        metal = self.a_category(100001, "Metall prokat")
        chemical = self.a_category(100002, "Kimyoviy")
        self.a_category(100003, "Qurilish")
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal, delivered=True)
        self.a_supply(self.a_firm("Kimyo Invest", "423456789"), chemical)

        self.assertEqual(supplier_categories().delivered_types, 1)

    def test_a_type_only_contracted_for_is_not_a_type_delivered(self) -> None:
        """REQ-DASH-007 says delivered, and a contract is not a delivery."""
        metal = self.a_category(100001, "Metall prokat")
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal)

        categories = supplier_categories()

        self.assertEqual(categories.rows[0].firms, 1)
        self.assertEqual(categories.delivered_types, 0)

    def test_nothing_marked_completed_means_nothing_delivered(self) -> None:
        """Master data may be edited into having no completed state (DEC-010)."""
        metal = self.a_category(100001, "Metall prokat")
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal, delivered=True)
        ShartnomaStatus.objects.update(is_completed=False)

        self.assertEqual(supplier_categories().delivered_types, 0)

    def test_the_busiest_type_is_listed_first(self) -> None:
        metal = self.a_category(100001, "Metall prokat")
        chemical = self.a_category(100002, "Kimyoviy")
        self.a_supply(self.a_firm("Kimyo Invest", "423456789"), chemical)
        self.a_supply(self.a_firm("MetalGrup JV", "223456789"), metal)
        self.a_supply(self.a_firm("UzElektro", "323456789"), metal)

        listed = [
            row.category.name
            for row in supplier_categories().rows
            if row.category.name in {"Metall prokat", "Kimyoviy"}
        ]

        self.assertEqual(listed, ["Metall prokat", "Kimyoviy"])


class SupplierCategoryPageTests(SignedInAdminTestCase):
    """The block as the dashboard renders it."""

    def test_the_table_and_the_chart_are_given_the_same_rows(self) -> None:
        manager = make_user("cat.page.manager", user_type=MENEJER)
        specialist = make_user("cat.page.specialist", user_type=KATTA_MUTAXASIS)
        category, _ = MahsulotTuri.objects.get_or_create(
            category_number=100001, defaults={"name": "Metall prokat"}
        )
        application = an_assigned_application(manager, specialist, department=a_department())
        ApplicationItem.objects.filter(application=application).delete()
        ApplicationItem.objects.create(
            application=application,
            mahsulot_turi=category,
            buyurtma_nomi="Prokat",
            buyurtma_soni=Decimal("1"),
            olchov_birligi="ta",
        )
        firm, _ = Supplier.objects.get_or_create(
            name="MetalGrup JV", defaults={"inn": "223456789"}
        )
        a_contract(application, specialist, supplier=firm)

        rendered = self.client.get(page("dashboard")).content.decode()
        chart_data = rendered.split('id="category-chart-data"', 1)[1].split("</script>", 1)[0]

        self.assertIn("Metall prokat", rendered)
        self.assertIn('"label": "Metall prokat"', chart_data)
        self.assertIn('"firms": 1', chart_data)

    def test_an_empty_database_renders_the_block(self) -> None:
        """The panel's heading is drawn from the catalogue, in Uzbek by default."""
        response = self.client.get(page("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Yetkazib beruvchilar toifalari taqsimoti")
