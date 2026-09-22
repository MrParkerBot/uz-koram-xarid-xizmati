"""Tests for the Ko'rish dialog on the two contract pages (TASK-UZK-063).

One fragment, fetched by both tables, readable exactly while the row that
opens it is. A contract moves between the two pages, so the view asks about
whichever page shows it now rather than naming one - the rule the
application documents already follow.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.test import TestCase

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    a_pdf,
    a_supplier,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import (
    ADMIN,
    KATTA_MUTAXASIS,
    Contract,
    ShartnomaStatus,
)


def detail_of(contract: Contract) -> str:
    return page("shartnoma-tafsilot", contract.pk)


class DetailFragmentTests(SignedInAdminTestCase):
    """What the dialog says about a contract."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("detail.specialist", user_type=KATTA_MUTAXASIS)

    def a_contract_to_read(self, **fields) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            with_pdf=True,
            **fields,
        )

    def test_it_names_the_contract_the_ariza_the_firma_and_the_department(self) -> None:
        contract = self.a_contract_to_read()

        response = self.client.get(detail_of(contract))

        self.assertContains(response, contract.shartnoma_raqami)
        self.assertContains(response, contract.application.ariza_raqami)
        self.assertContains(response, contract.supplier.name)
        self.assertContains(response, contract.application.department.name)

    def test_it_shows_the_value_and_who_entered_it(self) -> None:
        contract = self.a_contract_to_read()

        response = self.client.get(detail_of(contract))

        self.assertContains(response, contract.qiymati_display)
        self.assertContains(response, self.specialist.get_username())

    def test_it_lists_the_goods_with_their_unit_price_and_line_total(self) -> None:
        contract = self.a_contract_to_read()
        qator = contract.items.first()

        response = self.client.get(detail_of(contract))

        self.assertContains(response, qator.buyurtma_nomi)
        self.assertContains(response, qator.olchov_birligi)
        self.assertContains(response, qator.narxi_display)
        self.assertContains(response, qator.umumiy_narx_display)

    def test_a_contract_with_an_attachment_offers_it(self) -> None:
        contract = self.a_contract_to_read()

        response = self.client.get(detail_of(contract))

        self.assertContains(response, page("shartnoma-pdf", contract.pk))

    def test_a_contract_without_one_offers_no_download(self) -> None:
        """A button that can only answer 404 is worse than no button.

        Contracts entered before TASK-UZK-036A made the attachment mandatory
        have none.
        """
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )

        response = self.client.get(detail_of(contract))

        self.assertNotContains(response, page("shartnoma-pdf", contract.pk))

    def test_it_is_a_fragment_and_not_a_page(self) -> None:
        """The drawer injects what comes back, so a whole page would nest one."""
        contract = self.a_contract_to_read()

        response = self.client.get(detail_of(contract))

        self.assertNotContains(response, "<body")
        self.assertNotContains(response, "sidebar-nav")


class BuyurtmaLineTests(TestCase):
    """The card names one item and counts the rest (TASK-UZK-063)."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.head = make_user("buyurtma.head", user_type=ADMIN)
        cls.specialist = make_user("buyurtma.specialist", user_type=KATTA_MUTAXASIS)

    def a_contract_of(self, *names) -> Contract:
        return Contract.raise_contract(
            items=[
                {
                    "buyurtma_nomi": name,
                    "part_number": "",
                    "buyurtma_soni": Decimal("1"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("10"),
                }
                for name in names
            ],
            created_by=self.specialist,
            application=an_assigned_application(self.head, self.specialist),
            supplier=a_supplier(),
        )

    def test_one_row_reads_as_that_row(self) -> None:
        contract = self.a_contract_of("Bolt M12x50")

        self.assertEqual(contract.buyurtma_xulosasi, "Bolt M12x50")

    def test_several_rows_name_the_first_and_count_the_rest(self) -> None:
        contract = self.a_contract_of("Bolt M12x50", "Gayka M12", "Shayba")

        self.assertEqual(contract.buyurtma_xulosasi, "Bolt M12x50 +2 ta")


class WhoMayReadTests(SignedInAdminTestCase):
    """Readable while the row is, and no longer."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("read.specialist", user_type=KATTA_MUTAXASIS)

    def a_contract_to_read(self) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            with_pdf=True,
        )

    def test_somebody_elses_contract_is_readable(self) -> None:
        """The table shows every row, so the dialog behind them opens too.

        Whose work a contract is decides who may change it, not who may read
        it - the page already prints the firma, the value and the goods.
        """
        other = make_user("read.other", user_type=KATTA_MUTAXASIS)
        theirs = a_contract(an_assigned_application(self.admin, other), other)
        self.client.force_login(self.specialist)

        response = self.client.get(detail_of(theirs))

        self.assertEqual(response.status_code, 200)

    def test_a_sent_contract_is_read_through_the_page_that_now_shows_it(self) -> None:
        contract = self.a_contract_to_read()
        contract.send_for_approval(by=self.specialist)

        response = self.client.get(detail_of(contract))

        self.assertEqual(response.status_code, 200)

    def test_a_type_that_may_open_neither_page_is_refused(self) -> None:
        contract = self.a_contract_to_read()
        outsider = make_user("read.outsider")
        self.client.force_login(outsider)

        response = self.client.get(detail_of(contract))

        self.assertEqual(response.status_code, 403)

    def test_an_anonymous_visitor_is_sent_to_sign_in(self) -> None:
        contract = self.a_contract_to_read()
        self.client.logout()

        response = self.client.get(detail_of(contract))

        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response["Location"])

    def test_the_attachment_asks_the_same_question(self) -> None:
        contract = self.a_contract_to_read()
        outsider = make_user("read.pdf.outsider")
        self.client.force_login(outsider)

        response = self.client.get(page("shartnoma-pdf", contract.pk))

        self.assertEqual(response.status_code, 403)

    def test_the_attachment_downloads_for_a_reader(self) -> None:
        contract = self.a_contract_to_read()

        response = self.client.get(page("shartnoma-pdf", contract.pk))

        self.assertEqual(response.status_code, 200)
        self.assertIn(contract.shartnoma_raqami, response["Content-Disposition"])

    def test_the_attachment_downloads_as_an_ilova_of_the_contract(self) -> None:
        """The number it belongs to, and Ilova for what it is."""
        contract = self.a_contract_to_read()

        response = self.client.get(page("shartnoma-pdf", contract.pk))

        self.assertIn(
            f'filename="{contract.shartnoma_raqami}-Ilova.pdf"', response["Content-Disposition"]
        )

    def test_the_panel_calls_the_attachment_shartnoma_ilova(self) -> None:
        """What the eye icon opens says the same name the dialog asked for."""
        contract = self.a_contract_to_read()

        panel = self.client.get(detail_of(contract))

        self.assertContains(panel, "Shartnoma Ilova")
        self.assertNotContains(panel, "Shartnoma.pdf")

    def test_a_contract_with_no_attachment_is_a_404_not_a_crash(self) -> None:
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )

        response = self.client.get(page("shartnoma-pdf", contract.pk))

        self.assertEqual(response.status_code, 404)


class ButtonsOnBothPagesTests(SignedInAdminTestCase):
    """Both tables draw the control and carry the panel it fills."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("button.specialist", user_type=KATTA_MUTAXASIS)
        cls.status = ShartnomaStatus.objects.active().first()

    def a_contract_to_read(self) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            status=self.status,
        )

    def test_kelishinlingan_draws_the_button_and_the_drawer(self) -> None:
        contract = self.a_contract_to_read()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, f'data-detail-url="{detail_of(contract)}"')
        self.assertContains(response, 'id="sht-tafsilot-overlay"')
        # The label, not just the icon: TASK-UZK-063 replaced a disabled one.
        self.assertContains(response, "Ko'rish</button>")
        self.assertNotContains(response, "Ko'rish keyingi bosqichda")

    def test_tuzilgan_draws_the_button_and_the_drawer(self) -> None:
        contract = self.a_contract_to_read()
        contract.send_for_approval(by=self.specialist)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, f'data-detail-url="{detail_of(contract)}"')
        self.assertContains(response, 'id="sht-tafsilot-overlay"')

    def test_the_drawer_is_the_project_s_own_slide_over(self) -> None:
        """Not a second slide-over beside the Izoh drawers.

        Its close and its backdrop are bound by the drawer code, which reads
        data-close-drawer and the overlay class - a panel of its own would
        have to repeat both.
        """
        self.a_contract_to_read()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(response, 'class="drawer-overlay hidden"')
        self.assertContains(response, 'class="drawer-panel"')
        self.assertContains(response, 'data-close-drawer="sht-tafsilot"')

    def test_the_button_carries_the_heading_the_drawer_opens_with(self) -> None:
        contract = self.a_contract_to_read()

        response = self.client.get(page("kelishinlingan"))

        self.assertContains(
            response, f'data-detail-title="{contract.shartnoma_raqami} — Tafsilotlar"'
        )

    def test_the_page_costs_the_same_whatever_the_number_of_contracts(self) -> None:
        """The dialog is fetched, so rows must not each add markup or queries."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.a_contract_to_read()
        with CaptureQueriesContext(connection) as one:
            self.client.get(page("kelishinlingan"))

        for _ in range(4):
            self.a_contract_to_read()
        with CaptureQueriesContext(connection) as five:
            self.client.get(page("kelishinlingan"))

        self.assertEqual(len(one), len(five))
