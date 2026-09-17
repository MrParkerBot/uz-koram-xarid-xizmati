"""Tests for REQ-ARIZA-017, the status that follows a contract (TASK-UZK-033).

The thing worth being careful about is what the requirement does not say.
Section 4.9 says the current status changes according to the contract's state;
UNKNOWN-005 asked which statuses exist and how they correspond, and DEC-010
answered the half about the statuses being editable examples. It defines no
mapping between an ArizaStatus and a ShartnomaStatus, and an administrator
extends the two tables independently - so there is no translation to test, and
a test asserting an invented one would make the gap look filled.

What is tested instead is that the contract's status is what the page shows, as
it is, and that the record's own status column is left alone. The second half
matters: the request still knows what it was raised as, and nothing about
REQ-ARIZA-017 says it should forget.

The chain is four records long - a request, its approval, the department's
application, and a contract - so the fixtures here build all four rather than
writing the state directly. A shortcut would test a state the workflow may not
produce.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.crypto import get_random_string

from accounts.models import UserProfile, UserType
from accounts.roles import (
    ADMIN,
    BOLIM_BOSHLIGI,
    DIREKTOR,
    KATTA_MUTAXASIS,
    USERS,
    assign_user_type,
)
from applications.models import Contract, PurchaseApplication
from applications.test_support import a_pdf
from reference.models import (
    ArizaStatus,
    Department,
    MahsulotTuri,
    ShartnomaStatus,
    Supplier,
)


def make_user(type_name: str, department: Department | None = None):
    user = get_user_model().objects.create_user(
        username=f"user.{get_random_string(8).lower()}",
        password=get_random_string(24),
        first_name="Test",
        last_name=type_name,
    )
    assign_user_type(user, UserType.objects.get(name=type_name))
    if department is not None:
        UserProfile.objects.filter(user=user).update(department=department)
    return user


class PurchaseStatusTestCase(TestCase):
    """A request carried all the way to a contract."""

    def setUp(self) -> None:
        self.department = Department.objects.create(name="Texnik bolim")
        self.category = MahsulotTuri.objects.create(
            category_number=100042, name="Metallurgiya"
        )
        self.supplier = Supplier.objects.create(
            name="Metall Savdo MCHJ", inn="123456789"
        )
        self.requester = make_user(USERS, self.department)
        self.head = make_user(BOLIM_BOSHLIGI, self.department)
        self.direktor = make_user(DIREKTOR, self.department)
        self.admin = make_user(ADMIN, self.department)
        self.specialist = make_user(KATTA_MUTAXASIS, self.department)
        self.statuses = list(ShartnomaStatus.objects.active())
        self.yangi = ArizaStatus.objects.filter(
            code=ArizaStatus.Code.NEW
        ).first()

    def a_request(self) -> PurchaseApplication:
        return PurchaseApplication.raise_purchase_application(
            items=[
                {
                    "mahsulot_turi": self.category,
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": 500,
                    "olchov_birligi": "ta",
                }
            ],
            department=self.department,
            shartnoma_nomi="Bolt yetkazib berish shartnomasi",
            izoh="Shoshilinch",
            pdf=a_pdf(),
            created_by=self.requester,
            status=self.yangi,
        )

    def approved(self) -> PurchaseApplication:
        """A request carried through both approvals, so it has raised one."""
        request = self.a_request()
        request.approve(by=self.head)
        request.approve(by=self.direktor)
        request.refresh_from_db()

        return request

    def a_contract(self, request: PurchaseApplication, **overrides) -> Contract:
        application = request.raised_application
        application.accept(self.admin)
        application.assign(self.admin, self.specialist)

        fields = {
            "application": application,
            "supplier": self.supplier,
            "created_by": self.specialist,
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

    def page(self, as_user=None) -> str:
        self.client.force_login(as_user or self.admin)

        return self.client.get(reverse("xarid-ariza")).content.decode()


class WithoutAContractTests(PurchaseStatusTestCase):
    """What a request shows before there is anything to follow."""

    def test_a_new_request_shows_its_own_status(self) -> None:
        request = self.a_request()

        self.assertEqual(request.shown_status, self.yangi)
        self.assertFalse(request.status_follows_contract)
        self.assertIsNone(request.contract)

    def test_an_approved_request_with_no_contract_shows_its_own(self) -> None:
        request = self.approved()

        self.assertEqual(request.shown_status, self.yangi)
        self.assertIsNone(request.contract)

    def test_the_page_says_nothing_about_a_contract(self) -> None:
        self.a_request()

        self.assertNotIn("bo'yicha", self.page())


class FollowingTheContractTests(PurchaseStatusTestCase):
    """REQ-ARIZA-017 once there is a contract."""

    def test_the_contract_is_found(self) -> None:
        request = self.approved()
        contract = self.a_contract(request)

        self.assertEqual(request.contract, contract)

    def test_a_contract_status_is_what_the_request_shows(self) -> None:
        request = self.approved()
        self.a_contract(request, status=self.statuses[0])

        self.assertEqual(request.shown_status, self.statuses[0])
        self.assertTrue(request.status_follows_contract)

    def test_moving_the_contract_moves_what_the_request_shows(self) -> None:
        # The whole requirement, in one test: nothing is called on the
        # request, and what it shows changes anyway.
        request = self.approved()
        contract = self.a_contract(request, status=self.statuses[0])

        contract.set_status(self.statuses[1], self.specialist)

        self.assertEqual(
            PurchaseApplication.objects.get(pk=request.pk).shown_status,
            self.statuses[1],
        )

    def test_a_contract_with_no_status_leaves_the_request_showing_its_own(
        self,
    ) -> None:
        # Contract.status is nullable because DEC-010 lets an administrator
        # retire every row, so a contract can exist with none. Showing nothing
        # in that case would lose the status the request does have.
        request = self.approved()
        self.a_contract(request)

        self.assertEqual(request.shown_status, self.yangi)
        self.assertFalse(request.status_follows_contract)

    def test_the_newest_contract_wins(self) -> None:
        request = self.approved()
        self.a_contract(request, status=self.statuses[0])
        newest = Contract.raise_contract(
            items=[
                {
                    "buyurtma_nomi": "Bolt M12",
                    "buyurtma_soni": Decimal("10"),
                    "olchov_birligi": "ta",
                    "narxi": Decimal("100.00"),
                }
            ],
            application=request.raised_application,
            supplier=self.supplier,
            created_by=self.specialist,
            shartnoma_sanasi="2026-09-18",
            pdf=a_pdf("ikkinchi.pdf"),
            status=self.statuses[1],
        )

        self.assertEqual(
            PurchaseApplication.objects.get(pk=request.pk).contract, newest
        )

    def test_the_status_column_is_left_alone(self) -> None:
        # Derived, not copied. The request still knows what it was raised as,
        # and nothing in REQ-ARIZA-017 says it should forget.
        request = self.approved()
        contract = self.a_contract(request, status=self.statuses[0])
        contract.set_status(self.statuses[1], self.specialist)

        self.assertEqual(
            PurchaseApplication.objects.get(pk=request.pk).status, self.yangi
        )


class PageTests(PurchaseStatusTestCase):
    """What the Xarid Arizasi row shows, and what it says about it."""

    def test_the_contract_status_is_rendered(self) -> None:
        request = self.approved()
        self.a_contract(request, status=self.statuses[0])

        self.assertIn(self.statuses[0].name, self.page())

    def test_the_row_names_the_contract_it_followed(self) -> None:
        # A word that changed from one table to another with no explanation is
        # worse than no word at all: the two status lists are extended
        # independently, so they need not even look related.
        request = self.approved()
        contract = self.a_contract(request, status=self.statuses[0])

        page = self.page()

        self.assertIn(contract.shartnoma_raqami, page)
        self.assertIn("bo'yicha", page)

    def test_the_requester_sees_the_status(self) -> None:
        # REQ-ARIZA-017 is about what the person who asked for the purchase
        # can see: DEC-015 gives Users this page because it is the only one
        # they have. Every other test here opens it as Admin, which the review
        # of #58 pointed out is not the seat the requirement is written from.
        request = self.approved()
        self.a_contract(request, status=self.statuses[0])

        page = self.page(as_user=self.requester)

        self.assertIn(self.statuses[0].name, page)
        self.assertIn("Shartnoma bo'yicha", page)

    def test_the_requester_is_not_told_the_contract_number(self) -> None:
        # A contract number is a fact from a page DEC-015 does not give them,
        # and this list is not filtered by requester - so printing it here
        # would hand every Users account every contract number in the company.
        request = self.approved()
        contract = self.a_contract(request, status=self.statuses[0])

        page = self.page(as_user=self.requester)

        self.assertNotIn(contract.shartnoma_raqami, page)

    def test_somebody_who_may_open_the_contract_page_is_told_it(self) -> None:
        request = self.approved()
        contract = self.a_contract(request, status=self.statuses[0])

        page = self.page(as_user=self.admin)

        self.assertIn(contract.shartnoma_raqami, page)

    def test_the_number_follows_the_contract_to_the_next_page(self) -> None:
        # DEC-015 gives Direktor the Tuzilgan page and not Kelishinlingan, so
        # the number becomes theirs to see when the contract reaches it - the
        # same rule the attachment download follows.
        request = self.approved()
        contract = self.a_contract(request, status=self.statuses[0])
        direktor = self.direktor

        self.assertNotIn(
            contract.shartnoma_raqami, self.page(as_user=direktor)
        )

        Contract.objects.filter(pk=contract.pk).update(
            stage=Contract.Stage.SENT
        )

        self.assertIn(contract.shartnoma_raqami, self.page(as_user=direktor))

    def test_the_page_does_not_cost_a_query_per_row(self) -> None:
        def cost() -> int:
            self.client.force_login(self.admin)
            with CaptureQueriesContext(connection) as captured:
                self.client.get(reverse("xarid-ariza"))

            return len(captured.captured_queries)

        self.a_contract(self.approved(), status=self.statuses[0])
        with_one = cost()

        for _ in range(4):
            self.a_contract(self.approved(), status=self.statuses[1])

        self.assertEqual(cost(), with_one)
