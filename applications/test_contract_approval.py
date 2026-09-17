"""Tests for the department head's decision (TASK-UZK-039).

REQ-SHARTNOMA-001 is the table and REQ-SHARTNOMA-002 is the two buttons on it.
Three things carry this task.

Four user types may open this page and one of them decides. DEC-013 and the
project context make Admin the Xarid bo`lim boshlig`i, so a page-level
permission on its own would let a Menejer approve a contract that binds the
company. That is tested from the wrong direction as well as the right one.

The comment is the point of a rejection rather than a decoration on it, so
there are tests for the empty one and the whitespace one - the rule
Application.reject() holds one section earlier for the same requirement.

And where a rejection lands. REQ-SHARTNOMA-002 says the data is returned back,
and the test that proves it is not that the stage changed: it is that the
contract is on the Kelishinlingan page with its comment and a Re-Send control,
which is where its specialist left it.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
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
from applications.models import Application, Contract
from applications.test_support import a_pdf
from reference.models import (
    Department,
    MahsulotTuri,
    ShartnomaStatus,
    Supplier,
)


def make_user(type_name: str = ADMIN, first_name: str = "Test"):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name=first_name,
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    return user


class ContractApprovalTestCase(TestCase):
    """A contract waiting for the department head."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.supplier = Supplier.objects.create(
            name="Metall Savdo MCHJ", inn="123456789"
        )
        self.head = make_user(ADMIN, first_name="Alisher")
        self.specialist = make_user(KATTA_MUTAXASIS, first_name="Dilnoza")
        self.client.force_login(self.head)

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
        application.accept(self.head)
        application.assign(self.head, self.specialist)

        return application

    def an_agreed_contract(self) -> Contract:
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
            application=self.an_assigned_application(),
            supplier=self.supplier,
            created_by=self.specialist,
            shartnoma_sanasi="2026-09-17",
            pdf=a_pdf("shartnoma.pdf"),
            status=ShartnomaStatus.objects.active().first(),
        )

    def a_sent_contract(self) -> Contract:
        """A contract carried here the way TASK-UZK-038 carries one."""
        contract = self.an_agreed_contract()
        contract.send_for_approval(self.specialist)

        return contract

    def accept(self, contract: Contract):
        return self.client.post(
            reverse("shartnoma-tasdiqlash", args=[contract.pk])
        )

    def reject(self, contract: Contract, comment: str = "Narx juda baland."):
        return self.client.post(
            reverse("shartnoma-inkor", args=[contract.pk]),
            {"inkor_izohi": comment},
        )

    def page(self, name: str = "tuzilgan") -> str:
        return self.client.get(reverse(name)).content.decode()

    def table(self) -> str:
        page = self.page()

        return page.split('<tbody id="tuzilgan-tbody">', 1)[1].split(
            "</tbody>", 1
        )[0]


class ListTests(ContractApprovalTestCase):
    """Every column REQ-SHARTNOMA-001 names, on real data."""

    def test_the_headings_are_the_specified_ones(self) -> None:
        page = self.page()

        for heading in (
            "Ariza",
            "Bo'lim",
            "Buyurtma nomi",
            "Shartnoma",
            "Firma",
            "Kim tuzdi",
            "Yaratilgan",
            "Ko'rish",
            "Amallar",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, page)

    def test_a_sent_contract_is_listed(self) -> None:
        contract = self.a_sent_contract()

        row = self.table()

        self.assertIn(contract.shartnoma_raqami, row)
        self.assertIn(contract.application.ariza_raqami, row)
        self.assertIn("Texnik bolim", row)
        self.assertIn("Metall Savdo MCHJ", row)
        self.assertIn("Dilnoza", row)
        self.assertIn(contract.qiymati_display, row)

    def test_a_contract_still_with_its_specialist_is_not_listed(self) -> None:
        contract = self.an_agreed_contract()

        self.assertNotIn(contract.shartnoma_raqami, self.table())

    def test_an_empty_list_says_so(self) -> None:
        self.assertIn("Hozircha tasdiqlashga yuborilgan", self.table())

    def test_the_prototype_rows_are_gone(self) -> None:
        # The page held three contracts in a JavaScript array, which survived
        # nothing and meant nothing.
        page = self.page()

        self.assertNotIn("Texnoprom LLC", page)
        self.assertNotIn("SHT-2025-042", page)

    def test_the_page_does_not_cost_a_query_per_row(self) -> None:
        def cost() -> int:
            with CaptureQueriesContext(connection) as captured:
                self.client.get(reverse("tuzilgan"))

            return len(captured.captured_queries)

        self.a_sent_contract()
        with_one = cost()

        for _ in range(4):
            self.a_sent_contract()

        self.assertEqual(cost(), with_one)


class ViewingTests(ContractApprovalTestCase):
    """REQ-SHARTNOMA-002: View shows the products of the marked contract."""

    def test_the_goods_rows_are_on_the_page(self) -> None:
        contract = self.a_sent_contract()
        row = contract.items.get()

        page = self.page()

        self.assertIn("PN-0001", page)
        self.assertIn(row.narxi_display, page)
        self.assertIn(row.umumiy_narx_display, page)

    def test_the_detail_row_belongs_to_its_contract(self) -> None:
        contract = self.a_sent_contract()

        self.assertIn(f'id="tz-tafsilot-{contract.pk}"', self.page())

    def test_the_rows_are_the_contracts_own(self) -> None:
        # The prototype's drawer showed one hard-coded line whatever you
        # clicked, which is the failure this replaces.
        first = self.a_sent_contract()
        second = self.a_sent_contract()
        second.items.update(buyurtma_nomi="Kabel 4mm", part_number="PN-9999")

        page = self.page()

        self.assertIn("PN-0001", page)
        self.assertIn("PN-9999", page)
        self.assertNotEqual(first.pk, second.pk)


class AcceptTests(ContractApprovalTestCase):
    """REQ-SHARTNOMA-002: Accept."""

    def test_accepting_signs_the_contract(self) -> None:
        contract = self.a_sent_contract()

        response = self.accept(contract)

        self.assertRedirects(response, reverse("tuzilgan"))
        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SIGNED)

    def test_accepting_records_who_and_when(self) -> None:
        contract = self.a_sent_contract()

        self.accept(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.tasdiqlagan, self.head)
        self.assertIsNotNone(contract.tasdiqlangan_sana)

    def test_an_accepted_contract_stays_on_the_page(self) -> None:
        # This is the only page on which anybody can see that it was
        # approved, so removing it would lose the fact.
        contract = self.a_sent_contract()

        self.accept(contract)

        row = self.table()
        self.assertIn(contract.shartnoma_raqami, row)
        self.assertIn("Tasdiqlandi", row)
        self.assertIn("Alisher", row)

    def test_accepting_twice_changes_nothing(self) -> None:
        contract = self.a_sent_contract()
        self.accept(contract)
        approved_at = Contract.objects.get(pk=contract.pk).tasdiqlangan_sana

        self.accept(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.tasdiqlangan_sana, approved_at)

    def test_a_contract_still_with_its_specialist_cannot_be_accepted(
        self,
    ) -> None:
        contract = self.an_agreed_contract()

        self.accept(contract)

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.AGREED)
        self.assertIsNone(contract.tasdiqlagan)

    def test_the_accept_that_lands_second_changes_nothing(self) -> None:
        contract = self.a_sent_contract()
        somebody_else = make_user(ADMIN, "Bekzod")
        reading = Contract.refresh_from_db

        def gets_there_first(instance, *args, **kwargs):
            reading(instance, *args, **kwargs)
            Contract.objects.filter(pk=instance.pk).update(
                stage=Contract.Stage.SIGNED, tasdiqlagan=somebody_else
            )

        with patch.object(Contract, "refresh_from_db", gets_there_first):
            approved = contract.accept(self.head)

        self.assertFalse(approved)
        contract.refresh_from_db()
        self.assertEqual(contract.tasdiqlagan, somebody_else)


class RejectTests(ContractApprovalTestCase):
    """REQ-SHARTNOMA-002: Reject, with the comment that is its point."""

    def test_rejecting_sends_it_back(self) -> None:
        contract = self.a_sent_contract()

        response = self.reject(contract)

        self.assertRedirects(response, reverse("tuzilgan"))
        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.REJECTED)

    def test_rejecting_records_the_comment_and_the_decider(self) -> None:
        contract = self.a_sent_contract()

        self.reject(contract, "Byudjetdan oshib ketdi.")

        contract.refresh_from_db()
        self.assertEqual(contract.inkor_izohi, "Byudjetdan oshib ketdi.")
        self.assertEqual(contract.inkor_qilgan, self.head)
        self.assertIsNotNone(contract.inkor_sanasi)

    def test_rejecting_without_a_comment_is_refused(self) -> None:
        contract = self.a_sent_contract()

        self.reject(contract, "")

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)
        self.assertEqual(contract.inkor_izohi, "")

    def test_rejecting_with_only_whitespace_is_refused(self) -> None:
        contract = self.a_sent_contract()

        self.reject(contract, "   \n  ")

        contract.refresh_from_db()
        self.assertEqual(contract.stage, Contract.Stage.SENT)

    def test_the_comment_is_stripped(self) -> None:
        contract = self.a_sent_contract()

        self.reject(contract, "  Narx juda baland.  ")

        contract.refresh_from_db()
        self.assertEqual(contract.inkor_izohi, "Narx juda baland.")

    def test_the_refusals_are_told_apart(self) -> None:
        contract = self.a_sent_contract()

        no_comment = self.client.post(
            reverse("shartnoma-inkor", args=[contract.pk]),
            {"inkor_izohi": ""},
            follow=True,
        )
        self.assertContains(no_comment, "izoh kiritilishi shart")

        self.accept(contract)
        wrong_stage = self.client.post(
            reverse("shartnoma-inkor", args=[contract.pk]),
            {"inkor_izohi": "Kech"},
            follow=True,
        )
        self.assertContains(wrong_stage, "tasdiqlashga yuborilmagan")

    def test_a_rejected_contract_is_back_where_its_specialist_left_it(
        self,
    ) -> None:
        # REQ-SHARTNOMA-002's "the data is returned back". Not the stage: the
        # page, the comment and the control DEC-024 names.
        contract = self.a_sent_contract()

        self.reject(contract, "Narx juda baland.")

        self.client.force_login(self.specialist)
        kelishinlingan = self.page("kelishinlingan")
        self.assertIn(contract.shartnoma_raqami, kelishinlingan)
        self.assertIn("Narx juda baland.", kelishinlingan)
        self.assertIn("Re-Send", kelishinlingan)

    def test_a_rejected_contract_leaves_this_page(self) -> None:
        contract = self.a_sent_contract()

        self.reject(contract)

        self.assertNotIn(contract.shartnoma_raqami, self.table())

    def test_reject_refuses_a_contract_that_was_never_sent(self) -> None:
        contract = self.an_agreed_contract()

        with self.assertRaises(ValueError):
            contract.reject(self.head, "Narx juda baland.")


class WhoDecidesTests(ContractApprovalTestCase):
    """REQ-SHARTNOMA-002 gives the decision to the department head."""

    def test_the_other_types_may_open_the_page(self) -> None:
        contract = self.a_sent_contract()

        for type_name in (KATTA_MUTAXASIS, MENEJER, DIREKTOR):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                self.assertIn(contract.shartnoma_raqami, self.table())

    def test_they_are_not_offered_the_buttons(self) -> None:
        self.a_sent_contract()

        for type_name in (KATTA_MUTAXASIS, MENEJER, DIREKTOR):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))
                row = self.table()

                self.assertNotIn("Qabul", row)
                self.assertIn("Tasdiqlash kutilmoqda", row)

    def test_they_cannot_decide_by_posting(self) -> None:
        # The buttons are not there; this is the rule.
        for type_name in (KATTA_MUTAXASIS, MENEJER, DIREKTOR):
            with self.subTest(user_type=type_name):
                contract = self.a_sent_contract()
                self.client.force_login(make_user(type_name))

                self.assertEqual(self.accept(contract).status_code, 403)
                self.assertEqual(self.reject(contract).status_code, 403)

                contract.refresh_from_db()
                self.assertEqual(contract.stage, Contract.Stage.SENT)

    def test_the_types_with_no_page_may_not_open_it(self) -> None:
        for type_name in (BOLIM_BOSHLIGI, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                self.assertEqual(
                    self.client.get(reverse("tuzilgan")).status_code, 403
                )

    def test_the_head_is_offered_the_buttons(self) -> None:
        self.a_sent_contract()

        row = self.table()

        self.assertIn("Qabul", row)
        self.assertIn("Inkor", row)

    def test_signing_in_is_required(self) -> None:
        self.client.logout()

        response = self.client.get(reverse("tuzilgan"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_both_decisions_are_posted(self) -> None:
        contract = self.a_sent_contract()

        for route in ("shartnoma-tasdiqlash", "shartnoma-inkor"):
            with self.subTest(route=route):
                self.assertEqual(
                    self.client.get(
                        reverse(route, args=[contract.pk])
                    ).status_code,
                    405,
                )
