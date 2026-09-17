"""Tests for the contract status transitions of TASK-UZK-037.

The interesting question is what "permitted" means, and the honest answer is
narrower than the acceptance criterion sounds. DEC-010 makes the statuses rows
an administrator invents and extends, and ShartnomaStatus carries no code
column - unlike ArizaStatus, deliberately - so no code anywhere can name a
particular status, let alone draw a graph between two of them. A transition
table over names would be a table the Shartnoma Status page could invalidate,
which is the thing DEC-010 exists to prevent.

So the refusals tested here are the ones the data can express: a status that is
not in use, a contract that has left the page its specialist works from, and
nothing chosen at all. The ordering the department works to is an open point,
and a test asserting an invented one would make it look answered.

The other half is the record. REQ-ROLE-008 and REQ-ROLE-010 both say the
specialist keeps changing a contract's state, and "keeps changing" is a
sequence: a contract sitting at Yetkazib berilgan with no record of when it
passed Shartnoma tuzilgan cannot answer what the department is asking.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import ProtectedError
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
from applications.models import (
    Application,
    Contract,
    ContractStatusChange,
)
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


class ContractStatusTestCase(TestCase):
    """A contract, and the statuses DEC-010 seeded as examples."""

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
        self.statuses = list(ShartnomaStatus.objects.active())
        self.first, self.second = self.statuses[0], self.statuses[1]
        self.client.force_login(self.buyer)

    def an_application(self) -> Application:
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
            "application": self.an_application(),
            "supplier": self.supplier,
            "created_by": self.buyer,
            "shartnoma_sanasi": "2026-09-17",
            "pdf": a_pdf("shartnoma.pdf"),
            "status": None,
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

    def move(self, contract: Contract, status=None, chosen=None):
        """Post the status control the way the page posts it."""
        if chosen is None:
            chosen = "" if status is None else str(status.pk)

        return self.client.post(
            reverse("shartnoma-holat", args=[contract.pk]),
            {"status": chosen},
        )

    def page(self) -> str:
        return self.client.get(reverse("kelishinlingan")).content.decode()


class MovingTests(ContractStatusTestCase):
    """A permitted move (REQ-ROLE-008)."""

    def test_a_move_changes_the_status(self) -> None:
        contract = self.a_contract()

        response = self.move(contract, self.first)

        self.assertRedirects(response, reverse("kelishinlingan"))
        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)

    def test_moving_again_changes_it_again(self) -> None:
        contract = self.a_contract(status=self.first)

        self.move(contract, self.second)

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.second)

    def test_set_status_says_whether_it_moved(self) -> None:
        contract = self.a_contract()

        self.assertTrue(contract.set_status(self.first, self.buyer))
        self.assertFalse(contract.set_status(self.first, self.buyer))

    def test_a_second_click_writes_no_history(self) -> None:
        contract = self.a_contract()
        contract.set_status(self.first, self.buyer)

        contract.set_status(self.first, self.buyer)

        self.assertEqual(contract.status_changes.count(), 1)

    def test_every_active_status_is_offered(self) -> None:
        # DEC-010 seeds five as examples and an administrator adds more, so
        # the drop-down reads the table rather than a list in the code.
        added = ShartnomaStatus.objects.create(name="Kutilmoqda")
        self.a_contract()

        page = self.page()

        for status in [*self.statuses, added]:
            with self.subTest(status=status.name):
                self.assertIn(status.name, page)


class RefusalTests(ContractStatusTestCase):
    """The moves that are not permitted, and the status left unchanged."""

    def test_no_status_at_all_is_refused(self) -> None:
        contract = self.a_contract(status=self.first)

        self.move(contract, chosen="")

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)
        self.assertEqual(contract.status_changes.count(), 0)

    def test_choosing_nothing_does_not_clear_the_status(self) -> None:
        contract = self.a_contract(status=self.first)

        with self.assertRaises(ValueError):
            contract.set_status(None, self.buyer)

    def test_a_retired_status_is_refused(self) -> None:
        # Deleting master data deactivates it (DEC-009). The row is still
        # there, so a request that did not come from the drop-down can still
        # name it.
        retired = ShartnomaStatus.objects.create(name="Eskirgan")
        retired.delete()
        contract = self.a_contract(status=self.first)

        self.move(contract, retired)

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)

    def test_a_choice_that_is_not_a_number_is_nobodys_status(self) -> None:
        contract = self.a_contract(status=self.first)

        response = self.move(contract, chosen="tanlanmagan")

        self.assertRedirects(response, reverse("kelishinlingan"))
        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)

    def test_a_contract_awaiting_approval_cannot_be_moved(self) -> None:
        contract = self.a_contract(status=self.first)
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.SENT
        )

        self.move(contract, self.second)

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)
        self.assertEqual(contract.status_changes.count(), 0)

    def test_a_rejected_contract_can_still_be_moved(self) -> None:
        # DEC-024 has a rejected contract corrected and resent, so it is still
        # its specialist's to work on.
        contract = self.a_contract()
        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.REJECTED
        )

        self.move(contract, self.first)

        contract.refresh_from_db()
        self.assertEqual(contract.status, self.first)

    def test_the_refusals_are_told_apart(self) -> None:
        contract = self.a_contract(status=self.first)

        nothing_chosen = self.client.post(
            reverse("shartnoma-holat", args=[contract.pk]),
            {"status": ""},
            follow=True,
        )
        self.assertContains(nothing_chosen, "holat tanlanishi shart")

        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.SENT
        )
        already_sent = self.client.post(
            reverse("shartnoma-holat", args=[contract.pk]),
            {"status": str(self.second.pk)},
            follow=True,
        )
        self.assertContains(already_sent, "tasdiqlashga yuborilgan")


class HistoryTests(ContractStatusTestCase):
    """REQ-ROLE-010: who moved it, when, and from what."""

    def test_a_move_is_recorded(self) -> None:
        contract = self.a_contract(status=self.first)

        self.move(contract, self.second)

        change = ContractStatusChange.objects.get()
        self.assertEqual(change.contract, contract)
        self.assertEqual(change.from_status, self.first)
        self.assertEqual(change.to_status, self.second)
        self.assertEqual(change.changed_by, self.buyer)
        self.assertIsNotNone(change.changed_at)

    def test_the_first_move_records_no_previous_status(self) -> None:
        # A contract can be entered with no status at all, because DEC-010
        # lets an administrator retire every row. Refusing to record the move
        # away from nothing would lose the most interesting one.
        contract = self.a_contract()

        self.move(contract, self.first)

        self.assertIsNone(ContractStatusChange.objects.get().from_status)

    def test_the_moves_are_kept_in_order(self) -> None:
        contract = self.a_contract()

        for status in self.statuses[:3]:
            self.move(contract, status)

        self.assertEqual(
            [change.to_status for change in contract.status_changes.all()],
            list(reversed(self.statuses[:3])),
        )

    def test_the_move_is_recorded_against_whoever_made_it(self) -> None:
        contract = self.a_contract()
        self.client.force_login(self.specialist)

        self.move(contract, self.first)

        self.assertEqual(
            ContractStatusChange.objects.get().changed_by, self.specialist
        )

    def test_a_status_with_a_history_cannot_be_deleted(self) -> None:
        contract = self.a_contract()
        self.move(contract, self.first)

        with self.assertRaises(ProtectedError):
            ShartnomaStatus.objects.filter(pk=self.first.pk).delete()

    def test_the_page_shows_the_last_move(self) -> None:
        contract = self.a_contract()
        self.move(contract, self.first)
        self.move(contract, self.second)

        page = self.page()

        self.assertIn(self.second.name, page)
        self.assertIn("Alisher", page)

    def test_last_status_change_is_none_before_any(self) -> None:
        self.assertIsNone(self.a_contract().last_status_change)


class ViewingTests(ContractStatusTestCase):
    """REQ-SHARTNOMA-005's View Button, on the rows already on the page."""

    def test_the_goods_rows_are_on_the_page(self) -> None:
        contract = self.a_contract()
        row = contract.items.get()

        page = self.page()

        self.assertIn("PN-0001", page)
        self.assertIn("Umumiy Narx", page)
        # Through the model's own rendering rather than a literal: the group
        # separator is a non-breaking space, and a test that typed an ordinary
        # one would be asserting a different string that looks the same.
        self.assertIn(row.narxi_display, page)
        self.assertIn(row.umumiy_narx_display, page)

    def test_the_detail_row_belongs_to_its_contract(self) -> None:
        contract = self.a_contract()

        self.assertIn(f'id="sht-tafsilot-{contract.pk}"', self.page())

    def test_the_control_points_at_it(self) -> None:
        contract = self.a_contract()

        self.assertIn(
            f'data-tafsilot="sht-tafsilot-{contract.pk}"', self.page()
        )


class QueryTests(ContractStatusTestCase):
    """The cost of the page, which the review of #38 made a habit of."""

    def cost_of_the_page(self) -> int:
        with CaptureQueriesContext(connection) as captured:
            self.client.get(reverse("kelishinlingan"))

        return len(captured.captured_queries)

    def test_the_history_does_not_cost_a_query_per_row(self) -> None:
        contract = self.a_contract()
        self.move(contract, self.first)
        with_one = self.cost_of_the_page()

        for _ in range(4):
            moved = self.a_contract()
            self.move(moved, self.first)
            self.move(moved, self.second)

        self.assertEqual(self.cost_of_the_page(), with_one)


class PermissionTests(ContractStatusTestCase):
    """DEC-015 decides who may move a contract."""

    def test_the_permitted_types_may_move_one(self) -> None:
        for type_name in (ADMIN, BOLIM_BOSHLIGI, MENEJER, KATTA_MUTAXASIS):
            with self.subTest(user_type=type_name):
                contract = self.a_contract()
                self.client.force_login(make_user(type_name))

                self.move(contract, self.first)

                contract.refresh_from_db()
                self.assertEqual(contract.status, self.first)

    def test_the_others_may_not(self) -> None:
        contract = self.a_contract()

        for type_name in (DIREKTOR, USERS):
            with self.subTest(user_type=type_name):
                self.client.force_login(make_user(type_name))

                self.assertEqual(self.move(contract, self.first).status_code, 403)

        contract.refresh_from_db()
        self.assertIsNone(contract.status)

    def test_the_status_is_posted_rather_than_fetched(self) -> None:
        contract = self.a_contract()

        self.assertEqual(
            self.client.get(
                reverse("shartnoma-holat", args=[contract.pk])
            ).status_code,
            405,
        )
