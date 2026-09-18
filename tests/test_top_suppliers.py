"""Tests for the Top suppliers page and panel (TASK-UZK-051).

Firms are ranked by what their contracts come to inside the period (DEC-025),
narrowed by the level held on the supplier record (REQ-DASH-006). A firm with
no contracts in the period is not ranked at all.
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
    an_assigned_application,
    make_user,
    page,
)
from xarid.filters import DatePeriod
from xarid.models import DIREKTOR, KATTA_MUTAXASIS, MENEJER, Contract, Supplier
from xarid.reports import SPENDINGS_PERIOD, daraja_options, top_suppliers

# What the page and the panel both say when nothing is ranked. Template text,
# so it renders as written rather than HTML-escaped.
EMPTY_RANKING = "shartnomasi bo'lgan firma topilmadi"


class RankingTests(TestCase):
    """What the ranking counts and how it orders."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.manager = make_user("top.manager", user_type=MENEJER)
        cls.specialist = make_user("top.specialist", user_type=KATTA_MUTAXASIS)
        cls.department = a_department()

    @property
    def today(self) -> date:
        return timezone.localdate()

    def a_supplier_with(self, name: str, inn: str, daraja: str = "") -> Supplier:
        supplier, _ = Supplier.objects.get_or_create(
            name=name, defaults={"inn": inn, "daraja": daraja}
        )
        return supplier

    def a_contract_worth(self, amount: str, supplier: Supplier, on: date | None = None) -> None:
        """One contract of a known value against a known firm, on a known day."""
        application = an_assigned_application(
            self.manager, self.specialist, department=self.department
        )
        contract = a_contract(application, self.specialist, supplier=supplier)
        Contract.objects.filter(pk=contract.pk).update(
            qiymati=Decimal(amount), shartnoma_sanasi=on or self.today
        )

    def period_between(self, start: date, end: date) -> DatePeriod:
        return DatePeriod(
            SPENDINGS_PERIOD, {"dan": start.isoformat(), "gacha": end.isoformat()}
        )

    def test_firms_are_ranked_by_what_their_contracts_come_to(self) -> None:
        big = self.a_supplier_with("MetalGrup JV", "223456789")
        small = self.a_supplier_with("UzElektro", "323456789")
        self.a_contract_worth("100", small)
        self.a_contract_worth("900", big)

        ranking = top_suppliers(None)

        self.assertEqual([row.supplier for row in ranking], [big, small])
        self.assertEqual([row.place for row in ranking], [1, 2])
        self.assertEqual(ranking[0].total.amount, Decimal("900"))

    def test_a_firm_with_several_contracts_has_them_counted_and_added(self) -> None:
        firm = self.a_supplier_with("MetalGrup JV", "223456789")
        self.a_contract_worth("100", firm)
        self.a_contract_worth("250", firm)

        ranking = top_suppliers(None)

        self.assertEqual(ranking[0].contracts, 2)
        self.assertEqual(ranking[0].total.amount, Decimal("350"))

    def test_an_equal_total_is_broken_by_name_so_the_order_holds_still(self) -> None:
        first = self.a_supplier_with("Agro Mash", "223456789")
        second = self.a_supplier_with("Zenit Trade", "323456789")
        self.a_contract_worth("500", second)
        self.a_contract_worth("500", first)

        self.assertEqual([row.supplier for row in top_suppliers(None)], [first, second])

    def test_the_period_narrows_what_is_counted(self) -> None:
        firm = self.a_supplier_with("MetalGrup JV", "223456789")
        self.a_contract_worth("100", firm, on=self.today)
        self.a_contract_worth("900", firm, on=self.today - timedelta(days=40))

        ranking = top_suppliers(self.period_between(self.today, self.today))

        self.assertEqual(ranking[0].total.amount, Decimal("100"))
        self.assertEqual(ranking[0].contracts, 1)

    def test_a_firm_with_nothing_in_the_period_is_not_ranked(self) -> None:
        listed = self.a_supplier_with("MetalGrup JV", "223456789")
        self.a_supplier_with("Quiet Firm", "323456789")
        self.a_contract_worth("100", listed)

        self.assertEqual([row.supplier for row in top_suppliers(None)], [listed])

    def test_the_daraja_filter_keeps_only_that_level(self) -> None:
        gold = self.a_supplier_with("MetalGrup JV", "223456789", daraja="Oltin")
        silver = self.a_supplier_with("UzElektro", "323456789", daraja="Kumush")
        self.a_contract_worth("900", silver)
        self.a_contract_worth("100", gold)

        ranking = top_suppliers(None, daraja="Oltin")

        self.assertEqual([row.supplier for row in ranking], [gold])

    def test_the_daraja_options_leave_out_a_firm_with_no_level(self) -> None:
        self.a_supplier_with("MetalGrup JV", "223456789", daraja="Oltin")
        self.a_supplier_with("UzElektro", "323456789")

        levels = [supplier.daraja for supplier in daraja_options()]

        self.assertEqual(levels, ["Oltin"])

    def test_the_limit_takes_the_head_of_the_ranking(self) -> None:
        for number, amount in enumerate(("100", "200", "300"), start=1):
            firm = self.a_supplier_with(f"Firma {number}", f"12345678{number}")
            self.a_contract_worth(amount, firm)

        ranking = top_suppliers(None, limit=2)

        self.assertEqual([row.place for row in ranking], [1, 2])
        self.assertEqual([row.total.amount for row in ranking], [Decimal("300"), Decimal("200")])

    def test_the_leader_fills_its_bar_and_the_rest_are_a_share_of_it(self) -> None:
        leader = self.a_supplier_with("MetalGrup JV", "223456789")
        follower = self.a_supplier_with("UzElektro", "323456789")
        self.a_contract_worth("1000", leader)
        self.a_contract_worth("250", follower)

        ranking = top_suppliers(None)

        self.assertEqual([row.share_of_leader for row in ranking], [100, 25])

    def test_nothing_ranked_is_an_empty_ranking_rather_than_an_error(self) -> None:
        self.assertEqual(top_suppliers(None), ())


class TopSuppliersPageTests(SignedInAdminTestCase):
    """The page itself."""

    def a_ranked_firm(self, name: str, inn: str, amount: str, daraja: str = "") -> Supplier:
        manager = make_user(f"page.top.manager.{inn}", user_type=MENEJER)
        specialist = make_user(f"page.top.specialist.{inn}", user_type=KATTA_MUTAXASIS)
        supplier, _ = Supplier.objects.get_or_create(
            name=name, defaults={"inn": inn, "daraja": daraja}
        )
        application = an_assigned_application(manager, specialist, department=a_department())
        contract = a_contract(application, specialist, supplier=supplier)
        Contract.objects.filter(pk=contract.pk).update(
            qiymati=Decimal(amount), shartnoma_sanasi=timezone.localdate()
        )
        return supplier

    def test_the_page_lists_the_ranking(self) -> None:
        self.a_ranked_firm("MetalGrup JV", "223456789", "900", daraja="Oltin")

        response = self.client.get(page("top-suppliers"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "MetalGrup JV")
        self.assertContains(response, "Oltin")

    def test_an_empty_page_says_why_it_is_empty(self) -> None:
        response = self.client.get(page("top-suppliers"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, EMPTY_RANKING)

    def test_the_page_offers_the_daraja_and_period_controls(self) -> None:
        self.a_ranked_firm("MetalGrup JV", "223456789", "900", daraja="Oltin")

        response = self.client.get(page("top-suppliers"))

        self.assertContains(response, 'name="daraja"')
        self.assertContains(response, 'name="dan"')

    def test_the_dashboard_panel_shows_the_same_head_and_links_to_the_page(self) -> None:
        self.a_ranked_firm("MetalGrup JV", "223456789", "900")
        self.a_ranked_firm("UzElektro", "323456789", "100")

        response = self.client.get(page("dashboard"))
        rendered = response.content.decode()

        self.assertIn(page("top-suppliers"), rendered)
        self.assertLess(rendered.index("MetalGrup JV"), rendered.index("UzElektro"))

    def test_the_dashboard_panel_says_when_there_is_nothing_to_rank(self) -> None:
        response = self.client.get(page("dashboard"))

        self.assertContains(response, EMPTY_RANKING)


class TopSuppliersPermissionTests(TestCase):
    """Who may open it."""

    def test_the_types_that_may_open_the_dashboard_may_open_this(self) -> None:
        for user_type in (MENEJER, DIREKTOR):
            with self.subTest(user_type=user_type):
                self.client.force_login(make_user(f"top.{user_type}", user_type=user_type))

                self.assertEqual(self.client.get(page("top-suppliers")).status_code, 200)

    def test_a_type_that_may_not_open_the_dashboard_is_refused(self) -> None:
        self.client.force_login(make_user("top.outsider", user_type=KATTA_MUTAXASIS))

        self.assertEqual(self.client.get(page("top-suppliers")).status_code, 403)
