"""The Shartnoma PDF: the contract drawn from the record, once it is settled.

The column beside Ko'rish on Tuzilgan and the second button in the dialog
behind it are the same download, and both ask the same question first - has
the contract been approved. What is tested here is that the sheet says what
the record says, and that an unapproved contract has no sheet at all, whether
it is asked for through the page or by typing the URL.
"""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from tests.support import (
    SignedInAdminTestCase,
    a_contract,
    a_supplier,
    an_assigned_application,
    make_user,
    page,
)
from xarid.models import KATTA_MUTAXASIS, Contract, ShartnomaStatus

DOWNLOAD = "Shartnomani Yuklab Olish"


def pdf_text(response) -> str:
    """The drawn sheet as text, with its money spaces made ordinary ones.

    The pages group thousands with a non-breaking space, which is what makes
    a figure read as one number; pypdf hands it back as a plain space, so a
    test comparing the two has to agree on which space it means.
    """
    drawn = chr(10).join(
        sheet.extract_text() for sheet in PdfReader(BytesIO(response.content)).pages
    )
    return drawn.replace(chr(160), " ")


def as_written(value: str) -> str:
    """A figure from the record, spaced the way the extracted text spaces it."""
    return value.replace(chr(160), " ")


def document_of(contract: Contract) -> str:
    return page("shartnoma-hujjat-pdf", contract.pk)


class ContractDocumentTests(SignedInAdminTestCase):
    """What the drawn contract holds, and when it may be drawn at all."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("doc.specialist", user_type=KATTA_MUTAXASIS)

    def a_sent_contract(self, **fields) -> Contract:
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            **fields,
        )
        contract.send_for_approval(by=self.specialist)
        contract.refresh_from_db()
        return contract

    def an_approved_contract(self, **fields) -> Contract:
        contract = self.a_sent_contract(**fields)
        contract.accept(by=self.admin)
        contract.refresh_from_db()
        return contract

    def test_an_approved_contract_draws_its_own_sheet(self) -> None:
        contract = self.an_approved_contract(supplier=a_supplier("Texnoprom LLC", inn="123456789"))

        response = self.client.get(document_of(contract))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(
            f'filename="{contract.shartnoma_raqami}-shartnoma.pdf"',
            response["Content-Disposition"],
        )

        text = pdf_text(response)
        self.assertIn("SHARTNOMA", text)
        self.assertIn(contract.shartnoma_raqami, text)
        self.assertIn(contract.application.ariza_raqami, text)
        self.assertIn("Texnoprom LLC", text)
        self.assertIn("123456789", text)
        self.assertIn("Bolt M12x50", text)

    def test_the_sheet_carries_the_signature_that_settled_it(self) -> None:
        contract = self.an_approved_contract()

        text = pdf_text(self.client.get(document_of(contract)))

        self.assertIn("Tasdiqlash", text)
        self.assertIn("Test Admin", text)

    def test_the_priced_rows_add_up_to_the_value_in_the_heading(self) -> None:
        """A priced sheet whose rows do not make its total is the one fault."""
        application = an_assigned_application(self.admin, self.specialist)
        contract = Contract.raise_contract(
            items=[
                {
                    "buyurtma_nomi": "Bolt",
                    "part_number": "PN-1",
                    "buyurtma_soni": Decimal("2"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("1000.50"),
                },
                {
                    "buyurtma_nomi": "Gayka",
                    "part_number": "",
                    "buyurtma_soni": Decimal("3"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("1"),
                },
            ],
            created_by=self.specialist,
            application=application,
            supplier=a_supplier(),
        )
        contract.send_for_approval(by=self.specialist)
        contract.accept(by=self.admin)
        contract.refresh_from_db()

        text = pdf_text(self.client.get(document_of(contract)))

        self.assertIn("Jami", text)
        self.assertIn(as_written(contract.qiymati_display), text)
        self.assertIn("PN-1", text)

    def test_a_contract_awaiting_a_decision_has_no_sheet(self) -> None:
        """Typing the URL answers what the muted control says."""
        contract = self.a_sent_contract()

        self.assertEqual(self.client.get(document_of(contract)).status_code, 404)

    def test_a_contract_nobody_has_sent_has_no_sheet(self) -> None:
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )

        self.assertEqual(self.client.get(document_of(contract)).status_code, 404)

    def test_a_reader_who_may_not_open_the_page_may_not_draw_it(self) -> None:
        """The same permission the details dialog asks, on the same contract."""
        contract = self.an_approved_contract()
        self.client.force_login(make_user("doc.outsider"))

        self.assertEqual(self.client.get(document_of(contract)).status_code, 403)


class TuzilganColumnTests(SignedInAdminTestCase):
    """The Shartnoma PDF column, which is the link and nothing else."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("column.specialist", user_type=KATTA_MUTAXASIS)

    def a_sent_contract(self) -> Contract:
        contract = a_contract(
            an_assigned_application(self.admin, self.specialist), self.specialist
        )
        contract.send_for_approval(by=self.specialist)
        contract.refresh_from_db()
        return contract

    def test_the_column_offers_the_sheet_of_an_approved_contract(self) -> None:
        contract = self.a_sent_contract()
        contract.accept(by=self.admin)

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, "Shartnoma PDF")
        self.assertContains(response, document_of(contract))

    def test_the_column_offers_nothing_while_the_contract_waits(self) -> None:
        contract = self.a_sent_contract()

        response = self.client.get(page("tuzilgan"))

        self.assertContains(response, "Shartnoma PDF")
        self.assertNotContains(response, document_of(contract))


class DetailPanelButtonTests(SignedInAdminTestCase):
    """The second button under Shartnoma Ilova yuklab olish."""

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.specialist = make_user("panel.specialist", user_type=KATTA_MUTAXASIS)
        cls.status = ShartnomaStatus.objects.get(name="Boshlang`ich xolatda")

    def a_contract_to_read(self) -> Contract:
        return a_contract(
            an_assigned_application(self.admin, self.specialist),
            self.specialist,
            status=self.status,
        )

    def panel_of(self, contract: Contract) -> str:
        return page("shartnoma-tafsilot", contract.pk)

    def test_an_approved_contract_offers_the_download(self) -> None:
        contract = self.a_contract_to_read()
        contract.send_for_approval(by=self.specialist)
        contract.accept(by=self.admin)

        panel = self.client.get(self.panel_of(contract))

        self.assertContains(panel, DOWNLOAD)
        self.assertContains(panel, document_of(contract))
        self.assertNotContains(panel, "disabled")

    def test_an_unapproved_contract_shows_it_muted_and_links_nowhere(self) -> None:
        contract = self.a_contract_to_read()

        panel = self.client.get(self.panel_of(contract))

        self.assertContains(panel, DOWNLOAD)
        self.assertContains(panel, "disabled")
        self.assertNotContains(panel, document_of(contract))
