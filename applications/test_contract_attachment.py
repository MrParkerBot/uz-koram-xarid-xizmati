"""Tests for the contract attachment rule of TASK-UZK-036, against DEC-019.

REQ-SHARTNOMA-003 is one sentence with two halves - a contract carries a PDF
when it is entered, and also when it is edited - and the second half is the
one that needs care. An edit that silently dropped the document would look
exactly like an edit that kept it, right up until somebody asked for the
contract and there was nothing to produce.

So there are tests here for what an edit leaves behind as well as for what it
refuses, and tests that assert where the file is not: applications/
test_attachments.py established that shape for the department's application,
and a contract is the commercial evidence of all of it.

The edit path itself is built here because the rule needs somewhere to live.
REQ-SHARTNOMA-005 describes the Edit Button, nothing had built it, and
"refused when it is edited" cannot be shown without an edit.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserType
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    MENEJER,
    USERS,
    assign_user_type,
)
from applications.attachments import LARGEST_ATTACHMENT_BYTES
from applications.models import Application, Contract, ContractItem
from applications.test_support import PDF_BYTES, a_pdf
from reference.models import Department, MahsulotTuri, Supplier


def make_user(type_name: str = ADMIN, first_name: str = "Test"):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name=first_name,
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class ContractAttachmentTestCase(TestCase):
    """A contract, its document, and the form that put both there."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.supplier = Supplier.objects.create(
            name="Metall Savdo MCHJ", inn="123456789"
        )
        self.buyer = make_user(ADMIN, first_name="Alisher")
        self.specialist = make_user(KATTA_MUTAXASIS, first_name="Dilnoza")
        self.application = self.an_assigned_application()
        self.client.force_login(self.buyer)

    def an_assigned_application(self) -> Application:
        application = Application.raise_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": 500,
                    "olchov_birligi": "ta",
                }
            ],
            department=self.department,
        )
        application.accept(self.buyer)
        application.assign(self.buyer, self.specialist)

        return application

    def a_contract(self, **overrides) -> Contract:
        fields = {
            "application": self.application,
            "supplier": self.supplier,
            "created_by": self.buyer,
            "shartnoma_sanasi": "2026-09-17",
            "pdf": a_pdf("shartnoma.pdf"),
        }
        fields.update(overrides)

        return Contract.raise_contract(
            items=[
                {
                    "buyurtma_nomi": "Bolt M12",
                    "part_number": "PN-0001",
                    "buyurtma_soni": Decimal("500"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("250000.00"),
                }
            ],
            **fields,
        )

    def payload(self, rows: int = 1, **overrides) -> dict:
        form = {
            "application": self.application.pk,
            "supplier": self.supplier.pk,
            "shartnoma_turi": "",
            "status": "",
            "shartnoma_sanasi": "2026-09-17",
            "tolash_muddati": "",
            "muddat_talabi": "",
            "izoh": "",
            "form-TOTAL_FORMS": str(rows),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "1",
            "form-MAX_NUM_FORMS": "1000",
        }
        for index in range(rows):
            form |= {
                f"form-{index}-buyurtma_nomi": f"Bolt M{index + 1}",
                f"form-{index}-part_number": f"PN-000{index + 1}",
                f"form-{index}-buyurtma_soni": "500",
                f"form-{index}-olchov_birligi": "ta",
                f"form-{index}-narxi": "250000.00",
            }
        form.update(overrides)

        return form

    def create(self, rows: int = 1, pdf=None, **overrides):
        payload = self.payload(rows, **overrides)
        if pdf is not False:
            payload["pdf"] = pdf if pdf is not None else a_pdf("shartnoma.pdf")

        return self.client.post(reverse("shartnoma-yaratish"), payload)

    def edit(self, contract: Contract, rows: int = 1, pdf=False, **overrides):
        """Post the edit form. By default it uploads nothing, as an edit may."""
        payload = self.payload(rows, **overrides)
        payload["form-INITIAL_FORMS"] = str(contract.items.count())
        for index, row in enumerate(contract.items.all()):
            payload[f"form-{index}-id"] = row.pk
        if pdf is not False:
            payload["pdf"] = pdf

        return self.client.post(
            reverse("shartnoma-saqlash", args=[contract.pk]), payload
        )


class EntryRuleTests(ContractAttachmentTestCase):
    """REQ-SHARTNOMA-003 when a contract is entered."""

    def test_creating_with_a_pdf_stores_it(self) -> None:
        self.create()

        self.assertTrue(Contract.objects.get().pdf)

    def test_creating_without_one_is_refused(self) -> None:
        response = self.create(pdf=False)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contract.objects.count(), 0)
        self.assertEqual(ContractItem.objects.count(), 0)

    def test_the_refusal_says_what_is_wrong(self) -> None:
        page = self.create(pdf=False).content.decode()

        self.assertIn("PDF ilova yuklanishi shart", page)

    def test_a_file_that_is_not_named_pdf_is_refused(self) -> None:
        response = self.create(
            pdf=SimpleUploadedFile(
                "shartnoma.docx", PDF_BYTES, content_type="application/pdf"
            )
        )

        self.assertEqual(Contract.objects.count(), 0)
        self.assertIn("Faqat PDF fayl", response.content.decode())

    def test_a_file_that_only_claims_to_be_a_pdf_is_refused(self) -> None:
        # The name is what somebody typed; the first bytes are what the file
        # actually is, and the two disagreeing is the interesting case.
        response = self.create(
            pdf=SimpleUploadedFile(
                "shartnoma.pdf",
                b"<script>alert(1)</script>",
                content_type="application/pdf",
            )
        )

        self.assertEqual(Contract.objects.count(), 0)
        self.assertIn("Faqat PDF fayl", response.content.decode())

    def test_a_pdf_over_ten_megabytes_is_refused(self) -> None:
        oversized = SimpleUploadedFile(
            "shartnoma.pdf",
            PDF_BYTES + b"0" * LARGEST_ATTACHMENT_BYTES,
            content_type="application/pdf",
        )

        response = self.create(pdf=oversized)

        self.assertEqual(Contract.objects.count(), 0)
        self.assertIn("10 MB", response.content.decode())

    def test_raise_contract_refuses_a_contract_with_no_document(self) -> None:
        # The rule is about the contract rather than about the form, so it is
        # here as well as there - the same argument the review of #33 made
        # about an order quantity.
        with self.assertRaises(ValueError):
            self.a_contract(pdf=None)


class EditRuleTests(ContractAttachmentTestCase):
    """REQ-SHARTNOMA-003 when a contract is edited."""

    def test_the_edit_form_opens_filled_in(self) -> None:
        contract = self.a_contract()

        response = self.client.get(
            reverse("shartnoma-tahrirlash", args=[contract.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["editing"], contract)
        self.assertEqual(
            response.context["form"].instance.pk, contract.pk
        )
        self.assertIn(contract.shartnoma_raqami, response.content.decode())

    def test_editing_without_a_new_upload_keeps_the_stored_one(self) -> None:
        contract = self.a_contract()
        stored = contract.pdf.name

        self.edit(contract, izoh="Tuzatildi")

        contract.refresh_from_db()
        self.assertEqual(contract.pdf.name, stored)
        self.assertEqual(contract.izoh, "Tuzatildi")

    def test_editing_with_a_new_upload_replaces_it(self) -> None:
        contract = self.a_contract()
        stored = contract.pdf.name

        self.edit(contract, pdf=a_pdf("yangi-shartnoma.pdf"))

        contract.refresh_from_db()
        self.assertNotEqual(contract.pdf.name, stored)
        self.assertIn("yangi-shartnoma", contract.pdf.name)

    def test_editing_a_contract_with_no_document_is_refused(self) -> None:
        # A state REQ-SHARTNOMA-003 says cannot arise. It is written directly
        # because the rule has to hold for a row that got there some other
        # way - a restored backup, a shell - rather than only for rows this
        # application made.
        contract = self.a_contract()
        Contract.objects.filter(pk=contract.pk).update(pdf="")

        response = self.edit(contract, izoh="Tuzatildi")

        self.assertEqual(response.status_code, 200)
        contract.refresh_from_db()
        self.assertEqual(contract.izoh, "")

    def test_a_non_pdf_upload_on_edit_is_refused(self) -> None:
        contract = self.a_contract()
        stored = contract.pdf.name

        response = self.edit(
            contract,
            pdf=SimpleUploadedFile(
                "shartnoma.pdf", b"not a pdf", content_type="application/pdf"
            ),
            izoh="Tuzatildi",
        )

        self.assertIn("Faqat PDF fayl", response.content.decode())
        contract.refresh_from_db()
        self.assertEqual(contract.pdf.name, stored)
        self.assertEqual(contract.izoh, "")

    def test_the_form_offers_no_way_to_clear_the_attachment(self) -> None:
        # A clear checkbox is a way to leave a contract without the document
        # it is required to carry, so the widget is a plain file input.
        contract = self.a_contract()

        page = self.client.get(
            reverse("shartnoma-tahrirlash", args=[contract.pk])
        ).content.decode()

        self.assertNotIn("pdf-clear", page)


class EditedValueTests(ContractAttachmentTestCase):
    """An edit that changes the rows changes the contract value with them."""

    def test_editing_replaces_the_goods_rows(self) -> None:
        contract = self.a_contract()

        self.edit(contract, rows=3)

        contract.refresh_from_db()
        self.assertEqual(
            [row.buyurtma_nomi for row in contract.items.all()],
            ["Bolt M1", "Bolt M2", "Bolt M3"],
        )

    def test_the_value_follows_the_rows(self) -> None:
        contract = self.a_contract()
        self.assertEqual(contract.qiymati, Decimal("125000000.00"))

        self.edit(contract, rows=3)

        contract.refresh_from_db()
        self.assertEqual(contract.qiymati, Decimal("375000000.00"))

    def test_a_posted_value_is_ignored_on_edit_too(self) -> None:
        contract = self.a_contract()

        self.edit(contract, qiymati="1.00")

        contract.refresh_from_db()
        self.assertEqual(contract.qiymati, Decimal("125000000.00"))

    def test_revise_refuses_a_contract_with_no_rows(self) -> None:
        contract = self.a_contract()

        with self.assertRaises(ValueError):
            contract.revise(items=[])

    def test_revise_refuses_a_column_that_is_not_there(self) -> None:
        # raise_contract() goes through objects.create(), which raises for a
        # misspelled field before anything is written. This used to set the
        # attribute, save, and lose it in silence (the review of #54).
        contract = self.a_contract()

        with self.assertRaises(TypeError):
            contract.revise(
                items=[
                    {
                        "buyurtma_nomi": "Vint",
                        "buyurtma_soni": Decimal("1"),
                        "olchov_birligi": "ta",
                        "narxi": Decimal("10.00"),
                    }
                ],
                izohh="Tuzatildi",
            )

    def test_an_edit_can_take_a_row_off_the_contract(self) -> None:
        # The other direction from test_editing_replaces_the_goods_rows, and
        # the one the review of #54 found untested: three rows down to one,
        # posted the way the page posts it once a row has been removed.
        self.create(rows=3)
        contract = Contract.objects.get()
        kept = contract.items.all()[1]

        payload = self.payload(rows=1)
        payload["form-INITIAL_FORMS"] = "3"
        payload["form-0-id"] = kept.pk
        self.client.post(
            reverse("shartnoma-saqlash", args=[contract.pk]), payload
        )

        contract.refresh_from_db()
        self.assertEqual(contract.items.count(), 1)
        self.assertEqual(contract.qiymati, Decimal("125000000.00"))

    def test_the_form_offers_a_way_to_take_a_row_off(self) -> None:
        contract = self.a_contract()

        page = self.client.get(
            reverse("shartnoma-tahrirlash", args=[contract.pk])
        ).content.decode()

        self.assertIn("js-sht-qator-olib-tashlash", page)

    def test_a_contract_that_has_been_sent_cannot_be_edited(self) -> None:
        # DEC-024 describes correcting a rejected contract. One awaiting
        # somebody's approval changing underneath them is not described, so it
        # is refused rather than guessed at.
        contract = self.a_contract()
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.SENT
        )

        self.assertEqual(
            self.client.get(
                reverse("shartnoma-tahrirlash", args=[contract.pk])
            ).status_code,
            404,
        )
        self.assertEqual(self.edit(contract, izoh="Tuzatildi").status_code, 404)

    def test_a_rejected_contract_can_be_corrected(self) -> None:
        contract = self.a_contract()
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.REJECTED
        )

        self.edit(contract, izoh="Narx tuzatildi")

        contract.refresh_from_db()
        self.assertEqual(contract.izoh, "Narx tuzatildi")


class DownloadTests(ContractAttachmentTestCase):
    """DEC-019: the only way to a stored contract."""

    def url_for(self, contract: Contract) -> str:
        return reverse("shartnoma-pdf", args=[contract.pk])

    def test_the_document_downloads(self) -> None:
        contract = self.a_contract()

        response = self.client.get(self.url_for(contract))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b"".join(response.streaming_content), PDF_BYTES
        )

    def test_it_is_handed_back_as_a_download_under_its_own_number(
        self,
    ) -> None:
        contract = self.a_contract()

        response = self.client.get(self.url_for(contract))

        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn(
            f"{contract.shartnoma_raqami}.pdf", response["Content-Disposition"]
        )

    def test_it_cannot_be_talked_into_running_as_script(self) -> None:
        # as_attachment and nosniff together: the browser is told to save it
        # rather than render it, and told not to guess a different type.
        contract = self.a_contract()

        response = self.client.get(self.url_for(contract))

        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_the_stored_file_has_no_address(self) -> None:
        contract = self.a_contract()

        with self.assertRaises(ValueError):
            contract.pdf.url  # noqa: B018

    def test_the_file_is_not_under_anything_published(self) -> None:
        # Every directory the static machinery serves from, not only
        # STATIC_ROOT. The review of #54 found this looking at one of the two,
        # which would have passed with the attachments directory sitting
        # inside static/ - the arrangement attachments.py exists to prevent.
        contract = self.a_contract()

        stored = (Path(settings.ATTACHMENT_ROOT) / contract.pdf.name).resolve()
        self.assertTrue(stored.exists())

        for published in [settings.STATIC_ROOT, *settings.STATICFILES_DIRS]:
            with self.subTest(published=str(published)):
                self.assertNotIn(Path(published).resolve(), stored.parents)

    def test_somebody_who_may_not_open_the_page_is_refused(self) -> None:
        contract = self.a_contract()

        for type_name in (DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                self.assertEqual(
                    self.client.get(self.url_for(contract)).status_code, 403
                )

    def test_the_permitted_types_may_download(self) -> None:
        contract = self.a_contract()

        for type_name in (ADMIN, BOLIM_BOSHLIGI, MENEJER, KATTA_MUTAXASIS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                self.assertEqual(
                    self.client.get(self.url_for(contract)).status_code, 200
                )

    def test_the_document_follows_the_contract_to_the_next_page(self) -> None:
        # DEC-015 gives Direktor the Tuzilgan page and not Kelishinlingan, so
        # a contract that has been sent becomes readable by somebody it was
        # not readable by before - which is the point of asking about the page
        # the contract is on rather than about the route.
        contract = self.a_contract()
        self.client.force_login(make_user(DIREKTOR))
        self.assertEqual(
            self.client.get(self.url_for(contract)).status_code, 403
        )

        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.SENT
        )

        self.assertEqual(
            self.client.get(self.url_for(contract)).status_code, 200
        )

    def test_signing_in_is_required(self) -> None:
        contract = self.a_contract()
        self.client.logout()

        response = self.client.get(self.url_for(contract))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_the_list_links_to_it(self) -> None:
        contract = self.a_contract()

        page = self.client.get(reverse("kelishinlingan")).content.decode()

        self.assertIn(self.url_for(contract), page)
